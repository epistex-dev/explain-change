"""Outward actions: what a shell command did that leaves the working copy (a push, a new repo, a deploy, a deleted tree).

`classify(cmd)` is a pure function over one command string. It splits the string the way a shell does (quotes, `&&` `||` `;` `|` `&`,
subshells, `$(...)`, heredocs, comments, redirects), then looks only at the command word of each simple command, so text that merely
mentions `git push` (an echo, a grep, a heredoc, a comment, a commit message) is never an action. `bash -c '...'`, `eval` and a
heredoc fed to a shell are read as commands too. It never raises and runs in linear time; nesting stops at MAX_DEPTH.

`classify_call` adds the rule that a failed call counts for nothing. `repo_paths` names the directories that the git and gh
commands of a command string ran in.
"""
import os
import re

class Action(tuple):
    """(kind, label) as a plain 2-tuple, plus `.scratch`: True for a delete whose every target is under /tmp/ or $TMPDIR (worker temp dirs)."""
    scratch = False

    def __new__(cls, kind, label, scratch=False):
        a = tuple.__new__(cls, (kind, label))
        a.scratch = bool(scratch)
        return a


KINDS = ('repo_created', 'push', 'force_push', 'history_rewrite', 'delete', 'deploy', 'pr', 'message', 'other')
MAX_DEPTH = 8
MAX_ACTIONS = 1000
SHELLS = frozenset(('bash', 'sh', 'zsh', 'dash', 'ksh'))
KEYWORDS = frozenset(('{', '}', '!', 'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until', 'for', 'case', 'esac', 'time', 'coproc'))
# wrapper -> flags that take a value (the wrapper and its flags are skipped to reach the real command)
WRAPPERS = {'sudo': {'-u', '-g', '-h', '-p', '-C', '-D', '-R', '-T', '-U'}, 'env': {'-u', '-C', '-S'}, 'command': set(), 'exec': {'-a'}, 'nohup': set(),
            'nice': {'-n'}, 'timeout': {'-s', '-k'}, 'stdbuf': set(), 'setsid': set(), 'builtin': set(), 'doas': {'-u'}}
FAILED = re.compile(r'\s*exit code [1-9]', re.I)

DEPLOY = {  # program -> subcommands that publish or apply (looked for among the first two non-flag words)
    'fly': {'deploy'}, 'flyctl': {'deploy'}, 'kubectl': {'apply', 'delete'}, 'docker': {'push'}, 'podman': {'push'},
    'npm': {'publish'}, 'pnpm': {'publish'}, 'yarn': {'publish'}, 'bun': {'publish'}, 'cargo': {'publish'}, 'twine': {'upload'},
    'terraform': {'apply'}, 'tofu': {'apply'}, 'helm': {'install', 'upgrade'}, 'firebase': {'deploy'}, 'netlify': {'deploy'},
    'wrangler': {'deploy', 'publish'}, 'poetry': {'publish'}, 'uv': {'publish'}, 'gem': {'push'}, 'heroku': {'deploy'},
}
VERCEL_QUIET = frozenset(('env', 'ls', 'list', 'whoami', 'login', 'logout', 'link', 'pull', 'dev', 'build', 'logs', 'inspect', 'help', 'switch', 'domains', 'dns', 'teams', 'project', 'bisect', 'curl'))
GIT_VALUE_FLAGS = frozenset(('-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--super-prefix', '--config-env'))
GH_VALUE_FLAGS = frozenset(('-R', '--repo', '--hostname'))
PUSH_VALUE_FLAGS = frozenset(('-o', '--push-option', '--repo', '--receive-pack', '--exec', '--signed', '--recurse-submodules'))
SEP = ';&|\n()`'


def classify(cmd, cwd=None):
    """[(kind, label)] for one shell command (`cwd`: the directory it started in, which a relative delete target is read against); [] when nothing leaves the working copy. kind is one of KINDS; label names the action
    ("git push --force"). One entry per action: `git push && git push -f` gives two."""
    if isinstance(cmd, (bytes, bytearray)):
        cmd = bytes(cmd).decode('utf-8', 'replace')
    if not isinstance(cmd, str) or not cmd.strip():
        return []
    out = []
    try:
        _run(cmd, 0, out, cwd)
    except RecursionError:  # pragma: no cover - MAX_DEPTH keeps the stack shallow
        pass
    return out[:MAX_ACTIONS]


def classify_call(cmd, is_error=False, result=None):
    """classify(cmd) for a tool call that ran: a call with an error result, or whose result starts "Exit code N" (N > 0), did not happen."""
    return [] if failed(is_error, result) else classify(cmd)


def failed(is_error, result):
    """True for a tool result that says the command did not succeed: is_error, or text that starts "Exit code N" with N > 0."""
    return bool(is_error) or (isinstance(result, str) and bool(FAILED.match(result)))


def kinds(cmd, **kw):
    return [k for k, _ in classify_call(cmd, **kw)]


# ---- shell splitting -------------------------------------------------------------------------------------------------

def _run(text, depth, out, cwd=None):
    cur = cwd
    for words, heredoc in _split(text, depth):
        if len(out) >= MAX_ACTIONS:
            return
        w = _peel(words)
        if w and w[0] == 'cd' and len(w) > 1:  # a later relative delete is read against the new directory; subshell scope is not modelled
            cur = _join(cur, w[-1])
        _simple(words, heredoc, depth, out, cur)


def _heredoc_delim(text, i):
    """(delimiter, strip_tabs, index after the delimiter word) for a heredoc whose `<<` ends just before text[i]."""
    n = len(text)
    strip = text[i:i + 1] == '-'
    i += 1 if strip else 0
    while i < n and text[i] in ' \t':
        i += 1
    j, delim = i, []
    while j < n and text[j] not in ' \t\n;&|()<>':
        if text[j] in '\'"':
            k = text.find(text[j], j + 1)
            k = n if k < 0 else k
            delim.append(text[j + 1:k])
            j = k + 1
        else:
            if text[j] == '\\' and j + 1 < n:
                j += 1
            delim.append(text[j])
            j += 1
    return ''.join(delim), strip, j


def _heredoc_body(text, i, delim, strip):
    """(body lines, index after the closing delimiter line) for a body that starts at text[i]; it runs to the end when no line closes it."""
    n, body = len(text), []
    while i < n:
        j = text.find('\n', i)
        j = n if j < 0 else j
        line = text[i:j]
        i = min(j + 1, n)
        if (line.lstrip('\t') if strip else line).rstrip('\r') == delim:
            break
        body.append(line)
    return body, i


def _matching(s, i):
    """Index of the `)` that closes the `$(` or `(` before position i (s[i] is the first char inside); len(s) when there is none. Reads like the shell:
    single and double quotes, backslashes, nested `$(...)` and `(...)`, comments and heredoc bodies (a quote or paren in a body does not count)."""
    stack, n, pend = ['p'], len(s), []  # 'p': inside (...) in command text; 'q': inside "..."
    while i < n:
        c = s[i]
        if c == '\\':
            i += 2
        elif stack[-1] == 'q':
            if c == '"':
                stack.pop()
            elif c == '$' and s[i + 1:i + 2] == '(':
                stack.append('p')
                i += 1
            i += 1
        elif c == "'":
            j = s.find("'", i + 1)
            i = n if j < 0 else j + 1
        elif c == '"':
            stack.append('q')
            i += 1
        elif c == '(':
            stack.append('p')
            i += 1
        elif c == ')':
            stack.pop()
            if not stack:
                return i
            i += 1
        elif c == '#' and s[i - 1] in ' \t\n;&|()':
            j = s.find('\n', i)
            i = n if j < 0 else j
        elif c == '<' and s.startswith('<<', i) and not s.startswith('<<<', i):
            delim, strip, i = _heredoc_delim(s, i + 2)
            pend.append((delim, strip))
        elif c == '\n':
            i += 1
            while pend:
                delim, strip = pend.pop(0)
                i = _heredoc_body(s, i, delim, strip)[1]
        else:
            i += 1
    return n


def _split(text, depth):
    """List of (words, heredoc_body_or_None), one per simple command. Quotes are removed from words; redirect targets and heredoc bodies
    are not words. A `$(...)` inside double quotes is split out as commands of its own."""
    cmds, words, cur = [], [], []
    inword = False
    n, i = len(text), 0
    pend_hd = []  # [(delimiter, strip_tabs, index into cmds-or-current)] waiting for the newline that starts the body
    hd_for = {}  # id(words list) -> heredoc body
    skip_next = False  # the next word is a redirect target
    cur_hd = []

    def end_word():
        nonlocal inword, skip_next
        if inword:
            w = ''.join(cur)
            if skip_next:
                skip_next = False
            else:
                words.append(w)
        cur.clear()
        inword = False

    def end_cmd():
        nonlocal words, cur_hd
        end_word()
        if words:
            cmds.append((words, cur_hd[-1] if cur_hd else None))
        words = []
        cur_hd = []

    def sub(inner):
        if depth < MAX_DEPTH:
            cmds.extend(_split(inner, depth + 1))

    while i < n:
        c = text[i]
        if c == '\\':
            if i + 1 < n and text[i + 1] == '\n':
                i += 2
                continue
            cur.append(text[i + 1] if i + 1 < n else '')
            inword = True
            i += 2
        elif c == "'":
            j = text.find("'", i + 1)
            j = n if j < 0 else j
            cur.append(text[i + 1:j])
            inword = True
            i = j + 1
        elif c == '"':
            j, buf = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    buf.append(text[j + 1] if text[j + 1] in '"\\$`' else text[j:j + 2])
                    j += 2
                    continue
                if text[j] == '$' and text[j + 1:j + 2] == '(':
                    k = _matching(text, j + 2)
                    sub(text[j + 2:k])
                    buf.append(text[j:k + 1])
                    j = k + 1
                    continue
                buf.append(text[j])
                j += 1
            cur.append(''.join(buf))
            inword = True
            i = j + 1
        elif c == '#' and not inword:
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif c in ' \t\r':
            end_word()
            i += 1
        elif c == '\n':
            end_cmd()
            i += 1
            while pend_hd:  # the heredoc body starts on the next line
                delim, strip = pend_hd.pop(0)
                body, i = _heredoc_body(text, i, delim, strip)
                hd_for[len(cmds) - 1] = '\n'.join(body)
                if cmds:
                    cmds[-1] = (cmds[-1][0], hd_for[len(cmds) - 1])
        elif c in '<>':
            fd = ''.join(cur)
            if inword and fd.isdigit():  # 2> : the digits name a descriptor, they are not an argument
                cur.clear()
                inword = False
            else:
                end_word()
            if text.startswith('<<<', i):
                i += 3
                skip_next = True
            elif text.startswith('<<', i) and not text.startswith('<<<', i):
                delim, strip, i = _heredoc_delim(text, i + 2)
                pend_hd.append((delim, strip))
                cur_hd.append(None)
            else:
                i += 1
                if text[i:i + 1] == '(':  # <(cmd) and >(cmd): a command, not a redirect
                    continue
                if text[i:i + 1] in ('>', '|', '&'):
                    i += 1
                skip_next = True
        elif c == '&' and text[i + 1:i + 2] == '>':  # &> file
            end_word()
            i += 2
            if text[i:i + 1] == '>':
                i += 1
            skip_next = True
        elif c in SEP:
            end_cmd()
            skip_next = False
            i += 1
        elif c == '$' and text[i + 1:i + 2] == '(':
            end_word()
            i += 2
            if text[i:i + 1] == '(':  # $(( arithmetic ))
                continue
            k = _matching(text, i)
            sub(text[i:k])
            i = k + 1
            cur.append('$(…)')
            inword = True
        else:
            cur.append(c)
            inword = True
            i += 1
    end_cmd()
    return cmds


# ---- one simple command ----------------------------------------------------------------------------------------------

def _peel(words):
    """Drop leading shell keywords, VAR=value assignments and wrappers (sudo, env, timeout 5, nice -n 3, ...)."""
    w = list(words)
    for _ in range(64):
        while w and (w[0] in KEYWORDS or re.match(r'[A-Za-z_]\w*=', w[0])):
            w.pop(0)
        if not w:
            return w
        prog = w[0].rsplit('/', 1)[-1]
        if prog not in WRAPPERS:
            return w
        valued = WRAPPERS[prog]
        w.pop(0)
        if prog == 'timeout':
            while w and w[0].startswith('-'):
                w.pop(0) if w[0] not in valued else (w.pop(0), w.pop(0) if w else None)
            if w and re.match(r'\d', w[0]):
                w.pop(0)
            continue
        while w and w[0].startswith('-') and w[0] != '--':
            f = w.pop(0)
            if f in valued and w:
                w.pop(0)
        if w and w[0] == '--':
            w.pop(0)
    return w


def _flags(args):
    """(set of long flags, string of short-flag letters, positional words) for words after a subcommand; `--` ends flags."""
    longs, shorts, pos = set(), '', []
    done = False
    for a in args:
        if done or not a.startswith('-') or a == '-':
            pos.append(a)
        elif a == '--':
            done = True
        elif a.startswith('--'):
            name, _, val = a.partition('=')
            if not (name == '--dry-run' and val in ('none', 'false')):  # kubectl --dry-run=none really runs
                longs.add(name)
        else:
            shorts += a[1:]
    return longs, shorts, pos


def _simple(words, heredoc, depth, out, cwd=None):
    w = _peel(words)
    if not w:
        return
    prog, args = w[0].rsplit('/', 1)[-1], w[1:]
    if prog in SHELLS:
        script = _dash_c(args)
        if script is not None:
            if depth < MAX_DEPTH:
                _run(script, depth + 1, out, cwd)
        elif heredoc is not None and depth < MAX_DEPTH:
            _run(heredoc, depth + 1, out, cwd)
        return
    if prog == 'eval':
        if depth < MAX_DEPTH:
            _run(' '.join(args), depth + 1, out, cwd)
    elif prog == 'git':
        _git(args, out, cwd)
    elif prog == 'gh':
        _gh(args, out)
    elif prog in ('rm', 'rmdir', 'find'):
        _delete(prog, args, depth, out, cwd)
    elif prog == 'vercel':
        _vercel(args, out)
    elif prog in DEPLOY:
        longs, _, pos = _flags(args)
        if _dry(longs):
            return
        hit = DEPLOY[prog] & set(pos[:2])
        if prog == 'docker' and not hit and longs & {'--push'}:  # docker buildx build --push
            hit = {'push'}
        if hit:
            out.append(Action('delete' if sorted(hit) == ['delete'] else 'deploy', '%s %s' % (prog, sorted(hit)[0])))


def _dash_c(args):
    for i, a in enumerate(args):
        if a == '--':
            return None
        if re.fullmatch(r'-[A-Za-z]*c[A-Za-z]*', a) and i + 1 < len(args):
            return args[i + 1]
        if not a.startswith('-'):
            return None
    return None


def _dry(longs):
    return any(f == '--dry-run' for f in longs)


def _git(args, out, cwd=None):
    i = 0
    while i < len(args) and args[i].startswith('-') and args[i] != '--':
        i += 2 if args[i] in GIT_VALUE_FLAGS else 1
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]
    longs, shorts, pos = _flags(rest)
    if sub == 'push':
        if _dry(longs) or 'n' in shorts.replace('o', ''):
            return
        pos = _push_positional(rest)
        forced = bool(longs & {'--force', '--force-with-lease', '--force-if-includes', '--mirror'}) or 'f' in shorts or any(p.startswith('+') for p in pos)
        gone = bool(longs & {'--delete'}) or 'd' in shorts or any(p.startswith(':') for p in pos)
        if gone:
            out.append(Action('delete', 'git push --delete'))
        else:
            out.append(Action('force_push', 'git push --force') if forced else Action('push', 'git push'))
    elif sub in ('filter-repo', 'filter-branch'):
        out.append(Action('history_rewrite', 'git ' + sub))
    elif sub == 'worktree' and pos[:1] == ['remove']:
        out.append(Action('delete', 'git worktree remove', _scratch(pos[1:2], cwd)))
    elif sub == 'branch':
        forced = '--force' in longs or 'f' in shorts
        if 'D' in shorts or (forced and ('d' in shorts or '--delete' in longs)):
            out.append(Action('delete', 'git branch -D'))
    elif sub == 'clean' and 'f' in shorts + ''.join(l[2:] for l in longs if l == '--force') and not (_dry(longs) or 'n' in shorts):
        out.append(Action('delete', 'git clean'))


def _push_positional(rest):
    pos, skip, done = [], False, False
    for a in rest:
        if skip:
            skip = False
        elif done or not a.startswith('-'):
            pos.append(a)
        elif a == '--':
            done = True
        elif a in PUSH_VALUE_FLAGS:
            skip = True
    return pos


def _gh(args, out):
    i = 0
    while i < len(args) and args[i].startswith('-'):
        i += 2 if args[i] in GH_VALUE_FLAGS else 1
    longs, shorts, pos = _flags(args[i:])
    pos = pos[:2]
    if len(pos) < 2 and pos[:1] != ['api']:
        return
    key = ' '.join(pos)
    if key == 'repo create':
        out.append(Action('repo_created', 'gh repo create'))
        if '--push' in longs:
            out.append(Action('push', 'git push'))
    elif key in ('pr create', 'pr merge'):
        out.append(Action('pr', 'gh ' + key))
    elif key == 'release create':
        out.append(Action('deploy', 'gh release create'))
    elif key in ('repo delete', 'release delete'):
        out.append(Action('delete', 'gh ' + key))
    elif key in ('pr comment', 'pr review', 'issue create', 'issue comment'):
        out.append(Action('message', 'gh ' + key))
    elif pos[:1] == ['api']:
        method = _api_method(args[i:])
        if method and method != 'GET':
            out.append(Action('other', 'gh api ' + method))


def _api_method(args):
    has_fields = False
    for j, a in enumerate(args):
        if a in ('-X', '--method') and j + 1 < len(args):
            return args[j + 1].upper()
        if a.startswith('--method='):
            return a.split('=', 1)[1].upper()
        if a in ('-f', '-F', '--field', '--raw-field', '--input'):
            has_fields = True
    return 'POST' if has_fields else None


def _vercel(args, out):
    longs, _, pos = _flags(args)
    if _dry(longs):
        return
    if not pos or pos[0] in ('deploy', 'promote', 'rollback') or ('--prod' in longs and pos[0] not in VERCEL_QUIET):
        out.append(Action('deploy', 'vercel ' + (pos[0] if pos else 'deploy')))


def _delete(prog, args, depth, out, cwd):
    longs, shorts, pos = _flags(args)
    if prog == 'rmdir':
        out.append(Action('delete', 'rmdir', _scratch(pos, cwd)))
    elif prog == 'rm':
        if '--recursive' in longs or 'r' in shorts or 'R' in shorts or any(p.endswith('/') for p in pos):
            out.append(Action('delete', 'rm -r', _scratch(pos, cwd)))
    elif '-delete' in args:  # find: its single-dash tests are words, not flags
        roots = []
        for a in args:
            if a.startswith(('-', '(', '!')) and a != '-':
                break
            roots.append(a)
        out.append(Action('delete', 'find -delete', _scratch(roots, cwd)))
    else:
        for j, a in enumerate(args):
            if a in ('-exec', '-execdir', '-ok', '-okdir'):
                k = j + 1
                while k < len(args) and args[k] not in (';', '+'):
                    k += 1
                if depth < MAX_DEPTH:
                    _simple(args[j + 1:k], None, depth + 1, out, cwd)


def _scratch(paths, cwd=None):
    """True when there is a target and every one lies under /tmp/ or $TMPDIR (a worker's temp dir). A relative path counts only against a known `cwd`
    (the call's directory or an earlier absolute `cd`). `~`, a `$VAR` other than a leading $TMPDIR, a `..` that climbs out, or `/tmp` itself is not
    scratch: the doubt goes to the real side, which the page shows."""
    return bool(paths) and all(_is_scratch(p, cwd) for p in paths)


def _is_scratch(p, cwd):
    roots = ['/tmp']
    t = os.environ.get('TMPDIR', '').rstrip('/')
    if t.startswith('/') and t not in roots:
        roots.append(t)
    for var in ('${TMPDIR}', '$TMPDIR'):
        if p.startswith(var + '/'):
            p = '/tmp' + p[len(var):]
            break
    if '$' in p or '`' in p or p.startswith('~'):
        return False
    if not p.startswith('/'):
        if not cwd or '$' in cwd:
            return False
        p = os.path.join(cwd, p)
    p = os.path.normpath(p)
    return any(p.startswith(r + '/') for r in roots)


# ---- where git ran ---------------------------------------------------------------------------------------------------

def _join(cur, p):
    if not p or '$' in p or '`' in p or p == '-':
        return None
    p = os.path.expanduser(p)
    if os.path.isabs(p):
        return os.path.normpath(p)
    return os.path.normpath(os.path.join(cur, p)) if cur else None


def _git_calls(cmd, cwd=None, _depth=0):
    """[(dir, prog, args)] for each git and gh command in `cmd`: `dir` is where it ran (`git -C dir`, each -C relative to the one before; `gh -R owner/name`;
    else `cwd` as moved by an earlier `cd`; None when it cannot be named: a $VAR, `cd -`), `args` the words after the program with git's global flags removed."""
    out = []
    if not isinstance(cmd, str) or _depth > MAX_DEPTH:
        return out
    cur = cwd
    for words, _ in _split(cmd, _depth):
        w = _peel(words)
        if not w:
            continue
        prog, args = w[0].rsplit('/', 1)[-1], w[1:]
        if prog in SHELLS:
            script = _dash_c(args)
            if script is not None:
                out += _git_calls(script, cur, _depth + 1)
        elif prog == 'cd' and args:
            cur = _join(cur, args[-1])
        elif prog == 'git':
            d, i = cur, 0
            while i < len(args) and args[i].startswith('-') and args[i] != '--':
                if args[i] == '-C' and i + 1 < len(args):
                    d = _join(d, args[i + 1])
                i += 2 if args[i] in GIT_VALUE_FLAGS else 1
            out.append((d, 'git', args[i:]))
        elif prog == 'gh':
            repo = next((args[i + 1] for i, a in enumerate(args[:-1]) if a in ('-R', '--repo')), None)
            out.append((repo or cur, 'gh', args))
    return out[:MAX_ACTIONS]


def repo_paths(cmd, cwd=None):
    """Directories that the git and gh commands in `cmd` ran in, in order (see _git_calls); a directory that cannot be named is skipped."""
    return [d for d, _, _ in _git_calls(cmd, cwd) if d]


WORKTREE_VALUE_FLAGS = frozenset(('-b', '-B', '--reason'))


def worktree_adds(cmd, cwd=None):
    """[(repo dir, worktree path)] for each `git [-C dir] worktree add [flags] <path> [<commit-ish>]` in `cmd`, both absolute. Reads the text only: the
    paths may be gone, and nothing is run or looked up. A command with no path argument, or with a path or repo that cannot be named, gives nothing."""
    out = []
    for d, prog, args in _git_calls(cmd, cwd):
        if prog != 'git' or not d or args[:2] != ['worktree', 'add']:
            continue
        rest, path, i = args[2:], None, 0
        while i < len(rest):
            a = rest[i]
            if a == '--':
                path = rest[i + 1] if i + 1 < len(rest) else None
                break
            if a in WORKTREE_VALUE_FLAGS:
                i += 2
                continue
            if not a.startswith('-'):
                path = a
                break
            i += 1
        wt = _join(d, path)
        if wt and wt != d:
            out.append((d, wt))
    return out
