"""Validate an explain-flow/1 doc (references/explain-flow-schema.md): a logic flow of existing code, every source read from the pinned commit.
Returns (errors, stats). All problems come back together, one `path: reason` line each."""
import re

from . import gitio, transcript

KIND = 'explain-flow/1'
LANGS = ('vi', 'en')
WHERES = ('inside', 'outside')
EXITS = ('problems', 'end')
# the names a part may give as `icon`: the symbols of assets/ui/icons.svg, session-icons.svg and flow-icons.svg (a test keeps this list equal to them)
ICONS = ('arrow-right', 'ban', 'branch', 'bug', 'circle-check', 'circle-dashed', 'circle-help', 'circle-x', 'database', 'file-code', 'file-search', 'flask-conical',
         'globe', 'history', 'key-round', 'layout', 'list', 'map', 'message', 'monitor', 'panel-right', 'panel-right-close', 'plus', 'redirect', 'server',
         'shield-check', 'sparkles', 'trash', 'triangle-alert', 'undo', 'upload', 'user', 'x')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,39}\Z')
SHA = re.compile(r'[0-9a-f]{40}([0-9a-f]{24})?\Z')
MAX_SPAN = 80
MIN_EXCERPT, MAX_EXCERPT = 8, 300
MAX_BYTES = 2_000_000
CODE_TEXT = ('title', 'summary')  # plus the per-item fields below; `question` is the user's own words, so only the secret check applies
BLOCK = re.compile(r'`|[!+\-*/%<>]?=>?|->|::|&&|\|\||[{}\[\]]|[:;]\s*$|</?[A-Za-z][^>]*>|\w\(\)|\.\w+:\d+\b|\w\s*[<>]\s*\w|\blambda\b[^:]*:')
STATEMENT = re.compile(r'(return|raise|yield|assert|del|def|elif)\s+\S+\Z')  # "return foo": a statement word, then one name
PLURAL = re.compile(r'\w+\(s')  # "claim(s)"
# the tail of a bare file or product name or a domain (README.md, Node.js, example.com): prose, unlike a member such as doc.text
NAME_TAIL = frozenset(('js jsx ts tsx mjs cjs md py json yml yaml toml txt html css sh rs go java rb php c h cpp cs ini cfg conf lock csv sql xml svg png jpg gif '
                       'pdf com org net io dev ai vn').split())


def is_flow(doc):
    return isinstance(doc, dict) and doc.get('kind') == KIND


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _str(v):
    return isinstance(v, str) and bool(v.strip())


def _utf8(v):
    """True when the string can be written as UTF-8 (a lone surrogate from a JSON escape such as \\ud800 cannot)."""
    try:
        v.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def code_reason(text):
    """Why a text reads as code, else None: markup, an operator or assignment (`=`, `>`), a statement (`return x`, `lambda`, a trailing `:`), a call, a
    bracket, a member (`doc.text`), a snake_case name, or a file with a line number (`app.py:12`). Built on transcript.code_shaped.
    Prose passes: "e.g.", "claim(s)", "$5.50", "v1.2.3", and a bare file, product or domain name such as README.md, Node.js or example.com."""
    m = BLOCK.search(text) or STATEMENT.match(text.strip())
    if m:
        return 'has %r' % m.group(0).strip()
    for tok in text.split():
        t = tok.strip(transcript.TRIM)
        if not t or PLURAL.fullmatch(t) or not re.search(r'[._(\[$]', t) or not transcript.code_shaped(t):
            continue
        if re.match(r'\$\d', t):
            continue  # "$5.50"; "$HOME" is an environment reference
        if '.' in t and not re.search(r'[(\[$]', t):
            parts = t.split('.')
            if any(len(x) < 2 for x in parts) and '_' not in t:
                continue  # "e.g", "i.e"
            if parts[-1].lower() in NAME_TAIL:
                continue  # "README.md", "Node.js", "check_flow.py", "example.com"
        return 'has %r' % t
    return None


def _read(repo, commit, path):
    """(None, reason) or (lines, None): the text of `path` at `commit`, as a list of lines."""
    p = gitio.git(repo, 'ls-tree', '-z', commit, '--', path, check=False).decode('utf-8', 'replace')
    found = None
    for ent in p.split('\0'):
        meta, _, name = ent.partition('\t')
        if name == path:
            found = meta.split()
    if not found:
        return None, 'no such file at commit %s' % commit[:12]
    mode, kind = found[0], found[1]
    if mode == '120000':
        return None, 'is a symlink in the tree; cite the file it points to'
    if kind != 'blob':
        return None, 'is a %s, not a file' % ('folder' if kind == 'tree' else kind)
    data = gitio.read_version(repo, commit, path)
    if data is None:
        return None, 'cannot be read at commit %s' % commit[:12]
    if len(data) > MAX_BYTES:
        return None, 'is over %d KB' % (MAX_BYTES // 1000)
    if gitio.is_binary(data):
        return None, 'is a binary file'
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        return None, 'is not valid UTF-8'
    return text.splitlines(), None


def validate(doc, repo):
    errs, stats = _validate(doc, repo)
    return [transcript.redact(e) for e in errs], stats


def _validate(doc, repo):
    errs, warns = [], []
    stats = {'kind': 'flow', 'warnings': warns, 'parts': 0, 'outside': 0, 'steps': 0, 'branch_points': 0, 'errors': 0, 'sources': 0}

    def err(path, msg):
        errs.append('%s: %s' % (path, msg))

    if not isinstance(doc, dict):
        return ['$: the doc must be an object'], stats
    if doc.get('kind') != KIND:
        err('kind', 'must be %r' % KIND)
    if doc.get('lang', 'vi') not in LANGS:
        err('lang', 'must be one of %s (default vi)' % (LANGS,))

    def text(obj, field, path, code=True):
        v = obj.get(field) if isinstance(obj, dict) else None
        p = '%s.%s' % (path, field) if path else field
        if not _str(v):
            err(p, 'required non-empty string')
            return None
        if not _utf8(v):
            err(p, 'has a character that cannot be written as UTF-8 (a lone surrogate); the page could not be saved')
            return None
        if code:
            why = code_reason(v)
            if why:
                err(p, 'reads as code (%s); the page shows no code: say it in plain words' % why)
        if transcript.has_secret(v):
            err(p, 'contains what looks like a password, token or key; the page would show it. Leave the secret out')
        return v

    def items(obj, field, path, minimum=0):
        v = obj.get(field) if isinstance(obj, dict) else None
        p = '%s.%s' % (path, field) if path else field
        if not isinstance(v, list):
            if v is not None or minimum:
                err(p, 'must be a list')
            return []
        if len(v) < minimum:
            err(p, 'needs at least %d' % minimum)
        return v

    for f in CODE_TEXT:
        text(doc, f, '')
    text(doc, 'question', '', code=False)

    commit = doc.get('commit')
    sha = None
    if not isinstance(commit, str) or not SHA.match(commit):
        err('commit', 'must be the full 40-character SHA the doc was written against')
    else:
        if gitio.git(repo, 'cat-file', '-t', commit, check=False).strip() == b'commit':
            sha = commit
        else:
            err('commit', 'unknown commit %s in this repository' % commit[:12])

    cache = {}

    def source(src, path):
        stats['sources'] += 1
        if not isinstance(src, dict):
            return err(path, 'must be {path, lines, excerpt}')
        fp, lines, ex = src.get('path'), src.get('lines'), src.get('excerpt')
        ok = True
        if not _str(fp):
            err(path + '.path', 'required non-empty string')
            ok = False
        elif fp.startswith('/') or re.match(r'[A-Za-z]:', fp) or '\\' in fp or any(c in fp for c in '\0\n\r') or not _utf8(fp):
            err(path + '.path', 'must be a repo-relative path with forward slashes, not an absolute one')
            ok = False
        elif any(seg in ('..', '.', '') for seg in fp.split('/')) or fp.startswith('-'):
            err(path + '.path', 'must not hold "..", "." or empty parts, or start with "-"')
            ok = False
        if not (isinstance(lines, list) and len(lines) == 2 and all(_int(x) for x in lines)):
            err(path + '.lines', 'must be [first, last], two whole numbers')
            ok = False
        elif lines[0] < 1:
            err(path + '.lines', 'lines start at 1')
            ok = False
        elif lines[0] > lines[1]:
            err(path + '.lines', 'first line %d is after last line %d' % tuple(lines))
            ok = False
        elif lines[1] - lines[0] + 1 > MAX_SPAN:
            err(path + '.lines', 'spans %d lines; cite at most %d' % (lines[1] - lines[0] + 1, MAX_SPAN))
            ok = False
        norm = ' '.join(ex.split()) if isinstance(ex, str) else ''
        if not norm:
            err(path + '.excerpt', 'required non-empty string')
            ok = False
        elif not MIN_EXCERPT <= len(norm) <= MAX_EXCERPT:
            err(path + '.excerpt', '%d characters after whitespace is squeezed; it must be %d to %d' % (len(norm), MIN_EXCERPT, MAX_EXCERPT))
            ok = False
        if not ok or sha is None:
            return
        if fp not in cache:
            cache[fp] = _read(repo, sha, fp)
        body, why = cache[fp]
        if why:
            return err(path + '.path', '%s %s' % (fp, why))
        if lines[1] > len(body):
            return err(path + '.lines', '%s has %d lines at this commit, not %d' % (fp, len(body), lines[1]))
        if norm not in ' '.join(' '.join(body[lines[0] - 1:lines[1]]).split()):
            err(path + '.excerpt', 'not found in %s lines %d-%d at commit %s' % (fp, lines[0], lines[1], sha[:12]))

    def sources(obj, path, minimum):
        lst = items(obj, 'sources', path, minimum)
        for k, s in enumerate(lst):
            source(s, '%s.sources[%d]' % (path, k))

    ids = {}

    def ident(obj, path, what):
        v = obj.get('id') if isinstance(obj, dict) else None
        if not isinstance(v, str) or not ID.match(v):
            err(path + '.id', 'required: 1 to 40 letters, digits, "-" or "_", starting with a letter or digit')
            return None
        if v in EXITS:
            err(path + '.id', '%r is reserved for a branch target' % v)
        elif v in ids:
            err(path + '.id', 'duplicate id %r (first used by %s)' % (v, ids[v]))
        else:
            ids[v] = what
        return v

    parts = {}
    part_list = items(doc, 'parts', '', 1)
    for i, p in enumerate(part_list):
        path = 'parts[%d]' % i
        if not isinstance(p, dict):
            err(path, 'must be an object')
            continue
        pid = ident(p, path, path)
        text(p, 'name', path)
        text(p, 'role', path)
        icon = p.get('icon')
        if icon is not None and not (isinstance(icon, str) and icon in ICONS):
            err(path + '.icon', 'must be one of %s' % (', '.join(ICONS),))
        if p.get('where') not in WHERES:
            err(path + '.where', 'must be one of %s' % (WHERES,))
        sources(p, path, 1 if p.get('where') == 'inside' else 0)
        if pid and ids.get(pid) == path:
            parts[pid] = p
    stats['parts'] = len(part_list)
    stats['outside'] = sum(1 for p in part_list if isinstance(p, dict) and p.get('where') == 'outside')

    step_list = items(doc, 'steps', '', 1)
    steps = {}
    order = []
    for i, s in enumerate(step_list):
        path = 'steps[%d]' % i
        if not isinstance(s, dict):
            err(path, 'must be an object')
            order.append(None)
            continue
        sid = ident(s, path, path)
        order.append(sid if sid and ids.get(sid) == path else None)
        if order[-1]:
            steps[sid] = s
        text(s, 'name', path)
        text(s, 'takes_in', path)
        text(s, 'gives_back', path)
        if not (isinstance(s.get('part'), str) and s['part'] in parts):
            err(path + '.part', 'must be the id of a part of this doc')
        sources(s, path, 1)
        for k, b in enumerate(items(s, 'branches', path)):
            bp = '%s.branches[%d]' % (path, k)
            if not isinstance(b, dict):
                err(bp, 'must be {when, to}')
                continue
            text(b, 'when', bp)
        reads = s.get('reads')
        if reads is not None and not isinstance(reads, list):
            err(path + '.reads', 'must be a list of part ids')
        for k, r in enumerate(reads if isinstance(reads, list) else []):
            if not (isinstance(r, str) and r in parts):
                err('%s.reads[%d]' % (path, k), 'must be the id of a part of this doc')
            elif r == s.get('part'):
                err('%s.reads[%d]' % (path, k), 'is the part of the step itself; list another part it reads from')
            elif reads.index(r) != k:
                err('%s.reads[%d]' % (path, k), 'duplicate %r' % r)
        for k, e in enumerate(items(s, 'errors', path)):
            ep = '%s.errors[%d]' % (path, k)
            if not isinstance(e, dict):
                err(ep, 'must be {id, name, result, sources}')
                continue
            ident(e, ep, ep)
            text(e, 'name', ep)
            text(e, 'result', ep)
            sources(e, ep, 1)
            stats['errors'] += 1
    stats['steps'] = len(step_list)

    # graph: a step with branches leaves by them alone; a step without goes to the next step, the last one to the end
    edges, branching = {}, 0
    for i, s in enumerate(step_list):
        sid = order[i]
        if not sid:
            continue
        outs = []
        brs = s.get('branches') if isinstance(s.get('branches'), list) else []
        for k, b in enumerate(brs):
            to = b.get('to') if isinstance(b, dict) else None
            if isinstance(to, str) and (to in EXITS or to in steps):
                outs.append(to)
            elif isinstance(b, dict):
                err('steps[%d].branches[%d].to' % (i, k), 'must be a step id, "problems" or "end"; %r is neither' % (to,))
        if brs:
            branching += 1
        else:
            nxt = order[i + 1] if i + 1 < len(order) else 'end'
            if nxt:  # a next step with a bad id is reported on its own; it is not the end
                outs.append(nxt)
        edges[sid] = outs
    stats['branch_points'] = branching
    if order and order[0]:
        seen, todo = set(), [order[0]]
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            todo += [t for t in edges.get(n, []) if t in steps]
        for i, sid in enumerate(order):
            if sid and sid not in seen:
                err('steps[%d]' % i, 'unreachable from step 1: no step or branch leads to %r' % sid)
        if not any('end' in edges.get(n, []) for n in seen):
            err('steps', 'no path from step 1 reaches "end"')
    return errs, stats
