"""Claude Code session transcripts (JSONL under ~/.claude/projects): candidates, a digest for the agent, and the
streaming lookups that ground quotes, tool calls and URLs.

Only files under ~/.claude/projects are ever read. Every file is read line by line; a line that is not valid UTF-8 or
not valid JSON is skipped and counted (Stats), never fatal.

Files of one session: `<stem>.jsonl` ("main": the user talks here) and `<stem>/subagents/agent-*.jsonl` (workers; their
"user" messages are briefs from the orchestrator, not the user, so user quotes are looked up in main only).
"""
import json
import os
import re
import unicodedata

from . import neutral
from .gitio import ExplainError

TEST_WORDS = re.compile(r'(?i)(?<![\w-])(test|tests|vitest|pytest|phpunit|artisan test|npm run|lint|build|ci|playwright)(?![\w-])')
STRONG = re.compile(r'(?i)(?<![\w-])(vitest|pytest|unittest|phpunit|artisan test|npm (run|test|ci)|npx|playwright|eslint|lint|jest|mocha|rspec|tox|nox|mypy|ruff|tsc|shellcheck|'
                    r'composer (test|lint)|(go|cargo|make|mix|dotnet|gradle|mvn) (test|check)|docker (compose )?build|glab ci|pipelines?|red_check|prove[_-]fix|check\.mjs)(?![\w-])')
INLINE = re.compile(r'<<-?\s*[\'"]?\w|(?<![\w-])(python3?|node|ruby|perl|php|bash|sh)\s+(-c|-e|-r)\b|(?<![\w-])python3?\s+-(\s|$)')  # a heredoc or an inline script
READ_ONLY = re.compile(r'^\s*(cd [^;&|]+(&&|;)\s*)?(git (show|log|ls-tree|diff|grep|fetch|status|branch|worktree)|grep|sed|cat|head|tail|ls|find|wc|echo|date|mkdir)\b')
# `mk` (short for "mật khẩu") also names CSS (`--mk:32px;`, `.mk:hover`): _css_name() tells those apart by shape, so tk_mk:, user.mk: and --mk= still teach
_LABEL = r'(?<![A-Za-z0-9])(?:pass(?:word|wd)?|mật khẩu|mk|token|secret|api[_-]?key)(?:\s+chung)?\s*[:=]\s*'
SECRET = re.compile(  # a labelled value | a token with a known prefix | a bearer token
    r'(?i)(?P<label>' + _LABEL + r')(?=\S*[\d!@#$%^&*_])(?P<val>\S{6,})'
    r'|(?<![A-Za-z0-9])(?P<pre>glpat-|ghp_|sk-)(?P<tok>[\w-]{8,})|(?P<bpre>Bearer\s+)(?P<btok>[\w.~+/=-]{8,})')
CODE_CHARS = re.compile(r'[\w$.()\[\]{}]+')
MASK = '[ẩn]'
MIN_LEARNED = 6
TRIM = '\'"`,;.:!?)]}>('  # punctuation around a value in prose, a command or a JSON line
INJECTED = re.compile(r'<(t3_context|system-reminder|ide_[a-z_]+)\b.*?</\1>', re.S)
REPORT_PREFIX = ('<task-notification>', 'Delegated task ')  # a worker's report arriving as a user-role message
NOT_USER_PREFIX = REPORT_PREFIX + ('<system-reminder>', '<command-name>', '<local-command', 'Caveat:', 'This session is being continued')
COMPACT_FLAGS = ('isCompactSummary', 'isVisibleInTranscriptOnly')  # the summary Claude Code writes as a user record after a compaction
COMMAND_TOOLS = ('Bash',)  # tool calls whose input.command is a command that ran: the only ones that can ground a `tool_call` source
FETCH_TOOL = re.compile(r'(?i)(^|__)(web_?fetch|web_?search|preview_(navigate|open))')  # tools that open a URL
URL_KEYS = ('url', 'urls', 'query')  # a string, or a list of strings (mcp__exa__web_fetch_exa takes `urls: [...]`)
AGENT_ID = re.compile(r'agent-[A-Za-z0-9]+\Z')
MIN_NEEDLE = 4
DIGEST_CAP = 30000


def projects_root():
    return os.path.realpath(os.environ.get('EXPLAIN_PROJECTS_DIR') or os.path.expanduser('~/.claude/projects'))


def safe_path(path, fmt='auto'):
    """Real path of a transcript, refused unless it lies under ~/.claude/projects. A transcript of another harness (fmt auto detects it, or
    names it) is read by its adapter under that harness's official root and comes back as a neutral.NPath, a str holding its parsed session."""
    if isinstance(path, neutral.NPath):
        return path
    rp = os.path.realpath(os.path.expanduser(path))
    root = projects_root()
    inside = rp == root or rp.startswith(root + os.sep)
    if fmt not in neutral.CHOICES:
        raise neutral.FormatError('unknown format %r; supported: %s' % (fmt, neutral.formats_line()))
    if fmt != 'claude' and not (fmt == 'auto' and inside):
        other = neutral.open_transcript(path, fmt)
        if other is not None:
            return other
    if not inside:
        msg = 'transcript must be under %s (got %s)' % (root, path)
        if fmt == 'auto' and os.path.isfile(rp) and not neutral.claude_shaped(rp):
            raise neutral.FormatError('%s, and no supported format matched it (supported: %s)' % (msg, neutral.formats_line()))
        raise ExplainError(msg)
    if not os.path.isfile(rp):
        raise ExplainError('transcript not found: %s' % path)
    return rp


def norm(s):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', s)).strip()


class Stats:
    def __init__(self):
        self.lines = self.bad_json = self.bad_utf8 = 0

    @property
    def skipped(self):
        return self.bad_json + self.bad_utf8

    def warning(self, name):
        return ('%s: skipped %d of %d lines (%d invalid UTF-8, %d malformed JSON)' % (name, self.skipped, self.lines, self.bad_utf8, self.bad_json)
                if self.skipped else None)


def records(path, stats):
    """Yield one dict per valid JSON line, streaming."""
    with open(path, 'rb') as fh:
        for raw in fh:
            if not raw.strip():
                continue
            stats.lines += 1
            try:
                line = raw.decode('utf-8')
            except UnicodeDecodeError:
                stats.bad_utf8 += 1
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                stats.bad_json += 1
                continue
            if isinstance(rec, dict):
                yield rec


def iter_parts(src, st):
    """Yield (timestamp, cwd, kind, text, extra) for every part of a transcript file: a Claude Code JSONL path, or a neutral.NFile."""
    if isinstance(src, neutral.NFile):
        yield from neutral.iter_parts(src, st)
        return
    for rec in records(src, st):
        ts, cwd = rec.get('timestamp'), rec.get('cwd')
        for kind, text, extra in parts(rec):
            yield ts, cwd, kind, text, extra


def _blocks(rec):
    msg = rec.get('message')
    content = msg.get('content') if isinstance(msg, dict) else None
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _result_text(block):
    c = block.get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(b.get('text', '') for b in c if isinstance(b, dict) and isinstance(b.get('text'), str))
    return ''


def is_real_user(rec):
    if rec.get('type') != 'user' or rec.get('isMeta') or rec.get('isSidechain') or rec.get('origin'):
        return False
    return not any(rec.get(k) for k in COMPACT_FLAGS)


def parts(rec):
    """Yield (kind, text, extra) for one record. kind: user | assistant | tool_use | tool_result.
    user = something the human typed (injected context, notifications and delegated-task results removed).
    report = a worker's report that arrived as a user-role message (task notification, delegated-task result).
    tool_use extra = (id, name, command, input); tool_result extra = (id, is_error).
    (iter_parts adds, for other harnesses, a fifth item is_shell to tool_use and a third item unknown to tool_result.)"""
    t = rec.get('type')
    if t == 'assistant':
        for b in _blocks(rec):
            if b.get('type') == 'text' and isinstance(b.get('text'), str):
                yield 'assistant', b['text'], None
            elif b.get('type') == 'tool_use':
                inp = b.get('input') if isinstance(b.get('input'), dict) else {}
                cmd = inp.get('command') if isinstance(inp.get('command'), str) else json.dumps(inp, ensure_ascii=False)
                yield 'tool_use', json.dumps(inp, ensure_ascii=False), (b.get('id'), b.get('name'), cmd, inp)
    elif t == 'user':
        human = is_real_user(rec)
        for b in _blocks(rec):
            if b.get('type') == 'text' and isinstance(b.get('text'), str) and b['text'].lstrip().startswith(REPORT_PREFIX) and not rec.get('isMeta'):
                yield 'report', b['text'], None
                continue
            if b.get('type') == 'tool_result':
                yield 'tool_result', _result_text(b), (b.get('tool_use_id'), bool(b.get('is_error')))
            elif b.get('type') == 'text' and isinstance(b.get('text'), str) and human:
                txt = INJECTED.sub('', b['text']).strip()
                if txt and not txt.startswith(NOT_USER_PREFIX):
                    yield 'user', txt, None


def is_command_call(extra):
    """True for a tool_use that ran a command (allow-list COMMAND_TOOLS with a string input.command). A brief to a worker or the content of a
    written file can contain any text; only an executed command grounds a `tool_call` source."""
    return bool(extra) and (extra[1] in COMMAND_TOOLS or (len(extra) > 4 and extra[4])) and isinstance(extra[3].get('command'), str)


def url_text(extra):
    """The text of a tool call in which a URL counts as seen: a command that ran, or the target of a fetch/search tool."""
    if is_command_call(extra):
        return extra[3]['command']
    if extra and isinstance(extra[1], str) and FETCH_TOOL.search(extra[1]):
        vals = []
        for k in URL_KEYS:
            v = extra[3].get(k)
            vals += [v] if isinstance(v, str) else [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
        return ' '.join(vals)
    return None


# ---- lookups used by the validator ---------------------------------------------------------------------------------

class Query:
    """kind quote: `text` occurs in one message of a role in `roles`.  kind url: `text` occurs anywhere.
    kind tool: `command` occurs in a tool call's command and `excerpt` in that same call's result."""

    def __init__(self, kind, tid='main', roles=(), text=None, command=None, excerpt=None, label=''):
        self.kind, self.tid, self.roles, self.label = kind, tid, set(roles), label
        self.text = norm(text) if text is not None else None
        self.command = norm(command) if command is not None else None
        self.excerpt = norm(excerpt) if excerpt is not None else None
        self.found = False
        self.found_ok = False  # tool kind: found in a result that was not an error (is_error false)
        self.command_seen = False
        self.unknown_seen = False  # tool kind: the call that ran the command has no recorded output or exit code (result unknown)
        self.unknown = False       # tool kind: the only results found for it are unknown

    def too_short(self):
        for s in (self.text, self.command, self.excerpt):
            if s is not None and len(s) < MIN_NEEDLE:
                return True
        return False


def session_files(main_path):
    """{'main': path, 'agent-xxx': path, ...} for the session whose main transcript is main_path."""
    if isinstance(main_path, neutral.NPath):
        return neutral.session_files(main_path)
    out = {'main': main_path}
    sub = os.path.join(os.path.splitext(main_path)[0], 'subagents')
    if os.path.isdir(sub):
        for name in sorted(os.listdir(sub)):
            if name.endswith('.jsonl') and AGENT_ID.match(name[:-6]):
                out[name[:-6]] = os.path.join(sub, name)
    return out


def resolve_queries(main_path, queries):
    """Fill q.found for every query, one streaming pass per transcript file that a query names.
    Returns {tid: Stats}. An unknown transcript id leaves its queries not found."""
    files = session_files(main_path)
    stats = {}
    for tid in sorted({q.tid for q in queries}):
        qs = [q for q in queries if q.tid == tid and not q.too_short()]
        if tid not in files or not qs:
            continue
        stats[tid] = st = Stats()
        pending = {}  # tool_use id -> queries whose command matched
        for _, _, kind, text, extra in iter_parts(files[tid], st):
            n = None
            for q in qs:
                if q.found and (q.kind != 'tool' or q.found_ok):
                    continue
                if q.kind in ('quote', 'url') and (kind in q.roles):
                    n = norm(text) if n is None else n
                    q.found = q.text in n
                elif q.kind == 'url' and kind == 'tool_use':
                    seen = url_text(extra)
                    q.found = seen is not None and q.text in norm(seen)
                elif q.kind == 'tool' and kind == 'tool_use' and is_command_call(extra) and q.command in norm(extra[2]):
                    q.command_seen = True
                    pending.setdefault(extra[0], []).append(q)
            if kind == 'tool_result' and extra and extra[0] in pending:
                n = norm(text)
                unknown = len(extra) > 2 and extra[2]
                for q in pending.pop(extra[0]):
                    q.unknown_seen = q.unknown_seen or unknown
                    if q.excerpt in n:
                        q.found = True
                        q.found_ok = q.found_ok or not (extra[1] or unknown)
                        q.unknown = not q.found_ok and bool(unknown) and not extra[1]
    return stats


# ---- candidates and digest for collect.py --------------------------------------------------------------------------

def slug_variants(path):
    p = os.path.realpath(path)
    return {re.sub(r'[^A-Za-z0-9-]', '-', p), p.replace('/', '-').replace('.', '-')}


def project_dirs(repo, parents=2):
    """Existing ~/.claude/projects/<slug> dirs for the repo path and up to `parents` parents (sessions are often started
    in a parent folder). Slugs match case-insensitively: folders get renamed after their sessions were recorded."""
    root = projects_root()
    if not os.path.isdir(root):
        return []
    have = {n.lower(): n for n in os.listdir(root)}
    out, d = [], os.path.realpath(repo)
    for _ in range(parents + 1):
        for s in sorted(slug_variants(d)):
            real = have.get(s.lower())
            if real and os.path.join(root, real) not in out:
                out.append(os.path.join(root, real))
        up = os.path.dirname(d)
        if up == d or d == os.path.expanduser('~'):
            break
        d = up
    return out


def _stamp(rec):
    ts = rec.get('timestamp')
    return ts if isinstance(ts, str) else None


def first_user_message(path, limit=3000):
    st = Stats()
    for i, rec in enumerate(records(path, st)):
        if i > limit:
            break
        for kind, text, _ in parts(rec):
            if kind == 'user':
                return text
    return None


def time_span(path):
    """(first timestamp, last timestamp) without reading the whole file: head lines and the last 256 KB."""
    first = last = None
    st = Stats()
    for i, rec in enumerate(records(path, st)):
        if _stamp(rec):
            first = _stamp(rec)
            break
        if i > 200:
            break
    size = os.path.getsize(path)
    with open(path, 'rb') as fh:
        fh.seek(max(0, size - 262144))
        tail = fh.read().splitlines()
    for raw in reversed(tail):
        try:
            rec = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(rec, dict) and _stamp(rec):
            last = _stamp(rec)
            break
    return first, last


def candidates(repo, top=3):
    files = []
    for d in project_dirs(repo):
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if name.endswith('.jsonl') and os.path.isfile(p):
                files.append((os.path.getmtime(p), p))
    files.sort(reverse=True)
    out = []
    for _, p in files[:top]:
        first, last = time_span(p)
        out.append({'path': p, 'first_user': first_user_message(p), 'start': first, 'end': last, 'size': os.path.getsize(p),
                    'subagents': len(session_files(p)) - 1})
    return out


def other_candidates(repo, top=3):
    """Sessions of the other harnesses recorded in `repo`: [(harness, [candidate dict])], for the harnesses that have any."""
    return neutral.candidates(os.path.realpath(repo), top)


def code_shaped(v):
    """True for a value that is code, not a credential: an identifier, member expression, call or index (letters, digits, _, $, '.',
    '()', '[]'), or an environment reference such as $NAME. A bare word that carries a digit (Abc12345) is not code."""
    v = v.rstrip(',;')
    if not v or not CODE_CHARS.fullmatch(v):
        return False
    if v[0] == '$':
        return True
    if not re.match(r'[A-Za-z_]', v) or re.search(r'\.(?![A-Za-z_$])', v):
        return False
    return bool(re.search(r'[.(\[]', v)) or not re.search(r'\d', v)


_PSEUDO = re.compile(r'[a-z][a-z-]*(?:\([^)]*\))?(?:[{,\s>+~:.\[)]|$)')


def _css_name(m):
    """True when a labelled match is CSS, not a credential: a custom property `--mk:32px;` (no space, the value ends in ; or }) or a selector `.mk:hover` /
    `a.mk:nth-child(2)` (a pseudo-class right after the colon). `--mk=`, `user.mk: x` and `tk_mk:` are not CSS. When unsure, it is a credential."""
    s, lab = m.string, m.group('label')
    if not lab.lower().startswith('mk') or not lab.endswith(':'):  # a space after the colon is a config key, not CSS
        return False
    before, v = s[:m.start('label')], m.group('val')
    if before.endswith('--') and not re.search(r'\w$', before[:-2]):
        return bool(re.search(r'[;}]', v))
    if before.endswith('.'):
        return bool(_PSEUDO.match(v))
    return False


def _flagged(m):
    if m.group('val') is None:
        return True
    return not code_shaped(m.group('val')) and not _css_name(m)


def has_secret(s):
    """True when `s` holds something that looks like a credential (not a code-shaped value after a label)."""
    return any(_flagged(m) for m in SECRET.finditer(s))


def secret_values(s):
    """The credential strings in `s`: what a user or a command typed after a label, or a token with a known prefix."""
    out = set()
    for m in SECRET.finditer(s):
        if not _flagged(m):
            continue
        if m.group('val') is not None:
            v = m.group('val')
            out |= {v, v.strip(TRIM)}
        elif m.group('tok'):
            if learnable(m.group('tok')):  # glpat-AAAAAAAAAAAA is a fixture
                out |= {m.group('pre') + m.group('tok'), m.group('tok')}
        else:
            out.add(m.group('btok'))
    return {v for v in out if len(v) >= MIN_LEARNED and learnable(v)}


def learnable(v):
    """A value worth hiding everywhere: not code in any trimmed form (`parts[1`, `z.string().min(8`) and not one repeated character
    (`AAAAAAAAAAAA`, `000000`), which is a test fixture, not a credential."""
    if any(f and code_shaped(f) for f in (v, v.rstrip(',;'), v.strip(TRIM))):
        return False
    return len(set((v.strip(TRIM) or v).lower())) > 1


_LEARNED = set()  # credentials this process saw in a session transcript: they are hidden wherever they appear, label or not


def forget():
    _LEARNED.clear()


def learned():
    return frozenset(_LEARNED)


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def learn(main_path, fmt='auto'):
    """Learn the credentials of a session from every text a `transcript` quote can match (what `parts` yields: user, report, assistant and
    tool_result text, plus tool-call inputs) in the main and worker files, so that a bare occurrence of the value, with no label before it,
    is recognised too. Returns how many values are known. Never raises."""
    try:
        files = session_files(safe_path(main_path, fmt))
    except ExplainError:
        return len(_LEARNED)
    for path in files.values():
        try:
            for _, _, kind, text, extra in iter_parts(path, Stats()):
                if kind == 'tool_use':
                    for t in _strings(extra[3] if extra else {}):
                        _LEARNED.update(secret_values(t))
                else:
                    _LEARNED.update(secret_values(text))
        except OSError:
            continue
    return len(_LEARNED)


def contains_learned(s):
    return any(v in s for v in _LEARNED)


def redact(s):
    """Hide credentials in text that is shown (digest lines, candidates, the page, error lines): every value learned from the
    session wherever it stands, and what looks like a credential by its label."""
    for v in sorted(_LEARNED, key=len, reverse=True):
        s = s.replace(v, MASK)

    def sub(m):
        if not _flagged(m):
            return m.group(0)
        return (m.group('label') or m.group('pre') or m.group('bpre')) + MASK
    return SECRET.sub(sub, s)


READING = frozenset('sed cat head tail grep rg ls find wc echo printf date mkdir rm cp mv touch cd stat file du free sleep diff sort uniq which export source tr cut awk jq xxd montage convert'.split())
PART_SPLIT = re.compile(r'\s*(?:&&|\|\||;|\||\n)\s*')
LEAD = re.compile(r'^(?:[({]\s*|\w+=\S*\s+|time\s+|timeout\s+\d+\s+|nice\s+|env\s+)+')


def runs_strong(cmd):
    """True when a part of the command that runs something (not a reader such as sed, grep, ls or git show) names a test, lint,
    build or CI runner. `sed -n 1,9p tests/red_check.py` reads a file called red_check; `python3 tests/red_check.py` runs it. A heredoc body
    and the script text of `python3 -c '...'` are not looked at: only what is invoked."""
    for part in PART_SPLIT.split(invocation(cmd)):
        part = LEAD.sub('', part.strip())
        prog = part.split(None, 1)[0].rsplit('/', 1)[-1] if part else ''
        if not prog or prog in READING or READ_ONLY.match(part):
            continue
        if STRONG.search(part):
            return True
    return False


def invocation(cmd):
    """The command without the body of its heredocs, and with the text of an inline -c/-e script cut at its first quote: what is run,
    not what a script says. STRONG is matched against this for inline calls, so a script that merely mentions 'lint' is not a lint run."""
    out, tag = [], None
    for line in cmd.split('\n'):
        if tag is not None:
            if line.strip() == tag:
                tag = None
            continue
        out.append(line)
        m = re.search(r'<<-?\s*[\'"]?(\w+)[\'"]?', line)
        if m:
            tag = m.group(1)
    text = '\n'.join(out)
    m = re.search(r'(?<![\w-])(?:python3?|node|ruby|perl|php|bash|sh)\s+-[cer]\s+[\'"]', text)
    return text[:m.end()] if m else text


def _clip(s, n):
    s = redact(norm(s))
    return s if len(s) <= n else s[:n - 1] + '…'


def _fit(lines, budget):
    """Keep lines in order within `budget` characters: the first third and the latest ones; a note says how many are dropped."""
    if sum(len(x) + 1 for x in lines) <= budget:
        return lines
    head, tail, used = [], [], 0
    for x in lines[:max(1, len(lines) // 3)]:
        if used + len(x) + 1 > budget // 3:
            break
        head.append(x)
        used += len(x) + 1
    for x in reversed(lines[len(head):]):
        if used + len(x) + 1 > budget:
            break
        tail.append(x)
        used += len(x) + 1
    tail.reverse()
    dropped = len(lines) - len(head) - len(tail)
    return head + ['  ... %d entries omitted here (digest size cap) ...' % dropped] + tail


def _fit_tiers(tiers, budget):
    """Fill `budget` characters from the first tier down: a tier is cut (first third and latest, as _fit) only when what it needs is
    more than what is left, after a small share kept for the tiers below. Returns one list of lines per tier."""
    sizes = [sum(len(x) + 1 for x in t) for t in tiers]
    out, left = [], budget
    for i, t in enumerate(tiers):
        below = sum(sizes[i + 1:])
        room = left - min(below, budget // 6) if below else left
        got = _fit(t, max(room, 0)) if t else []
        out.append(got)
        left -= sum(len(x) + 1 for x in got)
    return out


def digest(main_path, cap=DIGEST_CAP):
    """Text digest: the user's messages and the test-like tool calls of the whole session (main + workers).
    Returns (text, warnings)."""
    learn(main_path)
    warnings, users, calls = [], [], []
    for tid, path in session_files(main_path).items():
        st = Stats()
        uses = {}
        for stamp, _, kind, text, extra in iter_parts(path, st):
            ts = (stamp if isinstance(stamp, str) else '')[:16].replace('T', ' ')
            if kind == 'user' and tid == 'main':
                masked = redact(norm(text)) != norm(text)
                users.append('  [u%d %s] %s%s' % (len(users) + 1, ts, _clip(text, 400), '  (value masked as %s: quote the words around it)' % MASK if masked else ''))
            elif kind == 'tool_use' and is_command_call(extra) and (TEST_WORDS.search(extra[2]) or STRONG.search(invocation(extra[2]))):
                inline = bool(INLINE.search(extra[2]))
                strong = runs_strong(extra[2])
                if not strong and READ_ONLY.match(extra[2]):
                    continue
                entry = {'tid': tid, 'ts': ts, 'cmd': extra[2], 'res': None, 'err': False, 'strong': strong, 'inline': inline, 'unknown': False}
                uses[extra[0]] = entry
                calls.append(entry)
            elif kind == 'tool_result' and extra and extra[0] in uses:
                uses[extra[0]]['res'], uses[extra[0]]['err'] = text, extra[1]
                uses[extra[0]]['unknown'] = len(extra) > 2 and bool(extra[2])
        w = st.warning('transcript %s' % tid)
        if w:
            warnings.append(w)
    calls.sort(key=lambda c: c['ts'])  # session_files lists main, then the workers by id: the latest runs must be the last lines
    lines_c, lines_w, lines_i = [], [], []  # strong runs | other mentions | inline scripts that only mention a test word (lowest)
    for c in calls:
        res = norm(c['res'] or '(no result recorded)')
        flag = 'ERROR' if c['err'] else ('result unknown' if c['unknown'] else 'exit!=0' if re.match(r'(?i)exit code [1-9]', res) else 'ok')
        shown = invocation(c['cmd']) if c['inline'] and not c['strong'] else c['cmd']
        (lines_c if c['strong'] else lines_i if c['inline'] else lines_w).append('  [%s %s] $ %s\n      -> %s  head: "%s"  tail: "%s"' % (
            c['tid'], c['ts'], _clip(shown, 260), flag, _clip(res, 160), redact(res[-160:]) if len(res) > 160 else ''))
    fit_c, fit_w, fit_i = _fit_tiers([lines_c, lines_w, lines_i], cap * 3 // 5)
    out = ['## Transcript digest: %s' % main_path,
           'Quote the user\'s words exactly as printed (a piece of one message is enough). For tests/CI evidence copy a piece of the',
           'command and a piece of the head or the tail of its result (not the "…" and not text from both); name the transcript id',
           '(`main` or `agent-…`) in source.transcript. A message that holds a credential is shown with the value as %s: quote the words' % MASK,
           'around it, and leave out the label and the value.',
           '', 'User messages (%d, main transcript):' % len(users)]
    out += _fit(users, cap * 2 // 5) or ['  (none found)']
    out += ['', 'Test, lint, build and CI runs (%d, all transcripts of the session; ids: %s):' % (len(lines_c), ', '.join(session_files(main_path)))]
    out += fit_c or ['  (none found)']
    out += ['', 'Other commands that mention test/build/ci, lower priority (%d; inline scripts last):' % (len(lines_w) + len(lines_i))]
    out += fit_w + fit_i or ['  (none)']
    return '\n'.join(out), warnings
