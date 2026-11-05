"""Session mode: one streaming pass over a Claude Code session (main transcript + workers) that gives the numbered user turns, the tool calls
grouped by the turn they follow, the repos the git commands ran in, and the outward actions (lib/outward.py) of calls that succeeded.

`scan` keeps counters and short excerpts, never whole results, so a 33 MB transcript costs a few MB. `digest` prints it for the agent that
writes an explain-session/1 doc; `check_session` calls `scan` to compare outward counts with the doc and `quote_turns` to place events."""
import bisect
import collections
import os

from . import outward, transcript

USER_CLIP = 300
USER_BUDGET = 24000
MAX_GROUPS = 60
MAX_REPOS = 60
MAX_OUTWARD_LINES = 80


class Scan:
    def __init__(self):
        self.users = []  # (n, ts, clipped text)
        self.groups = collections.OrderedDict()  # turn -> {'tools': Counter, 'first': ts, 'last': ts, 'cmd': excerpt}
        self.workers = {}  # tid -> {'calls': int, 'first': turn, 'last': turn}
        self.repos = {}  # path -> [first turn, last turn, git calls]
        self.outward = []  # (turn, kind, label, tid), in turn order
        self.warnings = []
        self.calls = 0

    def counts(self):
        return collections.Counter(k for _, k, _, _ in self.outward)


def _ts(rec):
    t = rec.get('timestamp')
    return t if isinstance(t, str) else ''


def scan(main_path):
    """Scan the session whose main transcript is `main_path` (a safe_path). Learns the session's credentials first, so excerpts are masked."""
    transcript.learn(main_path)
    sc = Scan()
    files = transcript.session_files(main_path)
    stamps = []  # timestamp of each user turn, to place a worker's call on the turn that was open at its time
    for tid in sorted(files, key=lambda t: (t != 'main', t)):
        st = transcript.Stats()
        pending = {}  # tool_use id -> (turn, [(kind, label)])
        turn = 0
        for rec in transcript.records(files[tid], st):
            ts = _ts(rec)
            for kind, text, extra in transcript.parts(rec):
                if tid == 'main' and kind == 'user':
                    turn += 1
                    stamps.append(ts)
                    sc.users.append((turn, ts, _excerpt(text, USER_CLIP)))
                elif kind == 'tool_use':
                    at = turn if tid == 'main' else bisect.bisect_right(stamps, ts) if ts else 0
                    _call(sc, tid, at, ts, extra, pending, rec.get('cwd'))
                elif kind == 'tool_result' and extra and extra[0] in pending:
                    at, acts = pending.pop(extra[0])
                    if not outward.failed(extra[1], text[:64]):
                        sc.outward += [(at, k, lbl, tid) for k, lbl in acts]
        w = st.warning('transcript %s' % tid)
        if w:
            sc.warnings.append(w)
    sc.outward.sort(key=lambda o: o[0])
    return sc


def _excerpt(s, n):
    s = transcript.redact(transcript.norm(s))
    return s if len(s) <= n else s[:n - 1] + '…'


def _call(sc, tid, turn, ts, extra, pending, cwd):
    sc.calls += 1
    name = extra[1] if isinstance(extra[1], str) else '?'
    if tid == 'main':
        g = sc.groups.setdefault(turn, {'tools': collections.Counter(), 'first': ts, 'last': ts, 'cmd': ''})
        g['tools'][name] += 1
        g['last'] = ts or g['last']
        if not g['cmd'] and transcript.is_command_call(extra):
            g['cmd'] = _excerpt(extra[2], 90)
    else:
        w = sc.workers.setdefault(tid, {'calls': 0, 'first': turn, 'last': turn})
        w['calls'] += 1
        w['last'] = max(w['last'], turn)
    if not transcript.is_command_call(extra):
        return
    cmd = extra[2]
    for d in outward.repo_paths(cmd, cwd if isinstance(cwd, str) else None):
        r = sc.repos.setdefault(d, [turn, turn, 0])
        r[0], r[1], r[2] = min(r[0], turn), max(r[1], turn), r[2] + 1
    acts = outward.classify(cmd)
    if acts and extra[0]:
        pending[extra[0]] = (turn, acts)


def quote_turns(main_path, needles):
    """{needle: [user turn numbers whose text holds it]} for the user-typed text of the main transcript (one streaming pass)."""
    want = {transcript.norm(n): [] for n in needles if isinstance(n, str)}
    turn = 0
    for rec in transcript.records(main_path, transcript.Stats()):
        for kind, text, _ in transcript.parts(rec):
            if kind == 'user':
                turn += 1
                n = transcript.norm(text)
                for q, hits in want.items():
                    if q and q in n:
                        hits.append(turn)
    return {n: want[transcript.norm(n)] for n in needles if isinstance(n, str)}


def _hm(ts):
    return ts[:16].replace('T', ' ') if ts else '?'


def digest(main_path):
    """(text, warnings): the session as the agent reads it before writing an explain-session/1 doc."""
    sc = scan(main_path)
    files = transcript.session_files(main_path)
    out = ['## Session digest: %s' % main_path,
           'Turns are the numbers u1, u2, ... in the order the user typed; compaction summaries, injected context and worker briefs are not turns.',
           'Use a turn number as an event `order`; quote the user\'s words exactly (a piece of one message is enough). A value masked as %s was a credential:' % transcript.MASK,
           'quote the words around it and leave the value out.', '',
           'User turns (%d, main transcript):' % len(sc.users)]
    users = ['  [u%d %s] %s' % (n, _hm(ts), t) for n, ts, t in sc.users]
    out += transcript._fit(users, USER_BUDGET) or ['  (none found)']
    out += ['', 'Work between turns (%d tool calls: main %d, workers %d; ids: %s):' % (
        sc.calls, sum(sum(g['tools'].values()) for g in sc.groups.values()), sum(w['calls'] for w in sc.workers.values()), _ids(files))]
    lines = ['  after u%d: %d calls (%s) %s..%s%s' % (
        t, sum(g['tools'].values()), ', '.join('%s %d' % kv for kv in g['tools'].most_common(3)), _hm(g['first'])[-5:], _hm(g['last'])[-5:],
        '; first command: %s' % g['cmd'] if g['cmd'] else '') for t, g in sc.groups.items()]
    out += _cap(lines, MAX_GROUPS) or ['  (none)']
    for tid, w in sorted(sc.workers.items()):
        out.append('  %s: %d calls, turns u%d..u%d' % (tid, w['calls'], w['first'], w['last']))
    repos = sorted(sc.repos.items(), key=lambda kv: (kv[1][0], kv[0]))
    out += ['', 'Repos touched (%d: the directory of each git or gh command, from -C, cd or the working directory; first..last turn, git calls):' % len(repos)]
    out += _cap(['  %s  u%d..u%d  %d' % (transcript.redact(p), a, b, n) for p, (a, b, n) in repos], MAX_REPOS) or ['  (none)']
    counts = sc.counts()
    out += ['', 'Outward actions (%d, only from calls that succeeded; an outward[].count in the doc must equal its total):' % len(sc.outward)]
    out += _cap(['  u%d  %s  %s%s' % (t, k, transcript.redact(lbl), '  [%s]' % tid if tid != 'main' else '') for t, k, lbl, tid in sc.outward], MAX_OUTWARD_LINES) or ['  (none)']
    out.append('  totals: ' + (', '.join('%s %d' % (k, counts[k]) for k in outward.KINDS if counts[k]) or 'none'))
    return '\n'.join(out), sc.warnings


def _ids(files):
    ids = list(files)
    return ', '.join(ids[:4]) + (', ... %d more' % (len(ids) - 4) if len(ids) > 4 else '')


def _cap(lines, n):
    return lines if len(lines) <= n else lines[:n // 2] + ['  ... %d more omitted ...' % (len(lines) - n)] + lines[-(n - n // 2):]
