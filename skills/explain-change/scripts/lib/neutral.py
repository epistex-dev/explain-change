"""Transcripts of every supported harness, seen through the same stream of parts the Claude Code reader gives.

transcript.py reads Claude Code JSONL itself. A transcript of another harness is parsed by its adapter (lib/adapters) into a
normalized Session, and this module turns that Session into the (timestamp, cwd, kind, text, extra) parts the grounding code already
walks: user text, assistant text, tool calls and their results. Injected text and compaction summaries are left out, as they are for
Claude Code, so a quote can never match them. A shell call whose output or exit code the harness did not record is flagged
`unknown` on its result: it can never back a done or a passed run.
"""
import json
import os
import re

from . import adapters
from .adapters import _io
from .gitio import ExplainError

FORMATS = ('claude', 'copilot', 'codex', 'opencode', 'gemini', 'cursor-cli', 'cursor-ide')
CHOICES = ('auto',) + FORMATS
assert set(FORMATS) == {'claude'} | set(adapters.ADAPTERS)
# What the first record of a Claude Code line looks like, to tell it from a file nothing recognises.
_CLAUDE_TYPES = ('user', 'assistant', 'summary', 'system', 'file-history-snapshot', 'queue-operation', 'attachment')


class FormatError(ExplainError):
    """A transcript no supported adapter recognises, or one that is not in the format asked for."""


class NPath(str):
    """The resolved reference of a non-Claude transcript (a file, or `<database>#<session id>`) with its parsed session."""
    session = None
    harness = None


class NFile:
    """One session of the transcript (the main one or a sub-agent) as the stream of parts."""

    def __init__(self, session, tid):
        self.session, self.tid = session, tid


def formats_line():
    return ', '.join(FORMATS)


def _real(p):
    if '#' in p and not os.path.exists(p):
        db, sid = p.rsplit('#', 1)
        return os.path.realpath(db) + '#' + sid
    return os.path.realpath(p)


def _detects(mod, p):
    try:
        return bool(mod.detect(p))
    except (OSError, ValueError, RecursionError):
        return False


def claude_shaped(p):
    """Whether the first JSON object of a plain file has the `type` of a Claude Code record."""
    try:
        rec = _io.first_record(os.path.realpath(p))
    except (OSError, ValueError):
        return False
    return isinstance(rec, dict) and rec.get('type') in _CLAUDE_TYPES


def detect(path):
    """The harness whose adapter recognises `path`, or None."""
    p = os.path.expanduser(path)
    for name, mod in adapters.ADAPTERS.items():
        if _detects(mod, p):
            return name
    return None


def load(path, harness):
    """The NPath of a transcript the adapter of `harness` reads under its official root. Raises ExplainError."""
    mod = adapters.get(harness)
    p = os.path.expanduser(path)
    root = mod.default_root()
    try:
        sess = mod.read(p, root)
    except adapters.RootError as e:
        raise ExplainError('transcript must be under %s (got %s)' % (root, path)) from e
    except (adapters.StoreError, OSError, ValueError, RecursionError) as e:
        raise ExplainError('cannot read the %s transcript %s: %s' % (harness, path, e)) from e
    np = NPath(_real(p))
    np.session, np.harness = sess, harness
    return np


def open_transcript(path, fmt='auto'):
    """NPath for a transcript of a non-Claude harness; None when `fmt` is auto and the file is not one (the caller then tries Claude Code
    rules). With an explicit `fmt` a file that is not in that format raises FormatError."""
    if fmt == 'auto':
        name = detect(path)
        return load(path, name) if name else None
    mod = adapters.get(fmt)
    if mod is None:
        raise FormatError('unknown format %r; supported: %s' % (fmt, formats_line()))
    if not _detects(mod, os.path.expanduser(path)):
        raise FormatError('%s is not a %s transcript (supported formats: %s)' % (path, fmt, formats_line()))
    return load(path, fmt)


def session_files(np):
    """{'main': NFile, 'agent-xxx': NFile, ...}: the main session and its sub-agent sessions, in the order the adapter gives them."""
    out = {'main': NFile(np.session, 'main')}
    for i, child in enumerate(list(np.session.walk())[1:], 1):
        base = 'agent-' + (re.sub(r'[^A-Za-z0-9]', '', child.id or '') or 'x%d' % i)
        tid, n = base, 1
        while tid in out:
            n += 1
            tid = '%s%d' % (base, n)
        out[tid] = NFile(child, tid)
    return out


def _inp(tool):
    if tool.is_shell:
        return {'command': tool.command} if isinstance(tool.command, str) else {}
    a = tool.args
    return a if isinstance(a, dict) else ({'input': a} if a is not None else {})


def iter_parts(nfile, st):
    """Yield (ts, cwd, kind, text, extra) like transcript.iter_parts. tool_use extra = (id, name, command, input, is_shell);
    tool_result extra = (id, is_error, unknown)."""
    sess = nfile.session
    cwd = sess.cwd
    for ev in sess.events:
        st.lines += 1
        ts = ev.ts if isinstance(ev.ts, str) else None
        if ev.kind == 'user_text' and ev.text:
            yield ts, cwd, 'user', ev.text, None
        elif ev.kind == 'assistant_text' and ev.text:
            yield ts, cwd, 'assistant', ev.text, None
        elif ev.kind == 'tool_call' and ev.tool is not None:
            t = ev.tool
            inp = _inp(t)
            cid = t.call_id if isinstance(t.call_id, str) and t.call_id else '#%s:%d' % (nfile.tid, ev.seq)
            cmd = inp['command'] if isinstance(inp.get('command'), str) else json.dumps(inp, ensure_ascii=False)
            yield ts, cwd, 'tool_use', json.dumps(inp, ensure_ascii=False), (cid, t.name, cmd, inp, bool(t.is_shell))
            unknown = bool(t.is_shell) and (t.output is None or t.exit_code is None)
            if t.output is not None or unknown:
                yield ts, cwd, 'tool_result', t.output or '', (cid, bool(t.is_error), unknown)


def candidates(repo, top=3):
    """Per harness with sessions recorded in `repo`: [(harness, [candidate dict, ...])], newest first. A store that cannot be read is skipped."""
    out = []
    for name, mod in adapters.ADAPTERS.items():
        found = []
        try:
            refs = mod.find_sessions(repo)
        except (OSError, ValueError, RecursionError):
            continue
        for ref in refs:
            if len(found) >= top:
                break
            try:
                np = load(ref, name)
            except ExplainError:
                continue
            s = np.session
            stamps = [e.ts for e in s.events if isinstance(e.ts, str)]
            first = next((e.text for e in s.events if e.kind == 'user_text' and e.text), None)
            found.append({'path': str(np), 'np': np, 'harness': name, 'first_user': first,
                          'start': s.started_at if isinstance(s.started_at, str) else (stamps[0] if stamps else None),
                          'end': stamps[-1] if stamps else None, 'events': len(s.events), 'subagents': len(s.children)})
        if found:
            out.append((name, found))
    return out
