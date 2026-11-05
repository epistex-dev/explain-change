"""Gemini CLI transcripts: ~/.gemini/tmp/<project>/chats/session-*.jsonl (and the older session-*.json).

Ported from google-gemini/gemini-cli (Apache-2.0, see THIRD_PARTY_NOTICES.md):

- `packages/core/src/services/chatRecordingService.ts` and `chatRecordingTypes.ts`: a JSONL transcript is a
  metadata record `{sessionId, projectHash, kind}`, message records `{id, type: user|gemini|info|error|warning,
  content, toolCalls[]}`, `$set` metadata updates, `$patch` records (`{id, content, toolCalls[{id, result}]}`, or
  `updates`, `removeIds`, `orderIds`), and `$rewindTo` records that drop a message and every message after it.
  A message record whose `id` was seen before replaces the earlier one in place (the loader's `Map.set`).
  The project hash is `sha256(project root)`. Sub-agent transcripts sit in `chats/<parent session id>/<id>.jsonl`
  with `kind: subagent`; the file name part is `sanitizeFilenamePart` of the id.
- `utils/sessionUtils.ts` `isIgnoredUserContent`: a recorded user message that starts with `<session_context>` or
  `<hook_context>` is the harness's, not typed.
- `tools/shell.ts`: the `run_shell_command` output is `Output: <text>`, then optional `Error:`, `Exit Code: N`
  (only when N is not 0), `Signal:`, `Background PIDs:` and `Process Group PGID:` lines. The exit code is
  not a field of the record, and the call's `status` stays `success` for a non-zero exit (`scheduler/tool-executor.ts`
  makes an error result only when the tool itself returns an error).

Changes: the result is the normalized model of model.py; the exit code is read from the footer only (the lines
after the output), so an `Exit Code:` line inside the output does not count; sessions are found by the
`projectHash` in each file's first record, which covers both the `sha256` and the short-id directory names.
"""
import hashlib
import json
import os
import re

from . import _io
from .model import (ASSISTANT_TEXT, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT, Session, Tool)

HARNESS = 'gemini'
SHELL_TOOLS = frozenset(('run_shell_command',))
INJECTED_PREFIXES = ('<session_context>', '<hook_context>')
MAX_DEPTH = 4
MAX_CHILDREN = 1000
MAX_LEGACY = 64 * 1024 * 1024      # a legacy single-object .json larger than this is not read
EXIT_LINE = re.compile(r'Exit Code: (-?\d+)')
FOOTER = (re.compile(r'Process Group PGID: \d+'), re.compile(r'Background PIDs: .*'), re.compile(r'Signal: \S+'))


def default_root():
    return os.path.join(os.path.expanduser('~'), '.gemini', 'tmp')


def project_hash(path):
    return hashlib.sha256(path.encode('utf-8', 'surrogateescape')).hexdigest()


def _sanitize(part):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', part)


def _is_header(rec):
    return isinstance(rec.get('sessionId'), str) and isinstance(rec.get('projectHash'), str)


def _legacy(real):
    """The conversation object of a legacy single-object .json file, or None."""
    with _io.open_plain(real) as fh:
        raw = fh.read(MAX_LEGACY + 1)       # a file over the cap is cut here, so it does not parse
    try:
        obj = json.loads(raw.decode('utf-8', 'replace'))
    except ValueError:
        return None
    return obj if isinstance(obj, dict) and _is_header(obj) and isinstance(obj.get('messages'), list) else None


def _header(real):
    """The metadata record of a transcript (its first record, or a legacy file's own keys), or None."""
    try:
        if real.endswith('.json'):
            return _legacy(real)
        rec = _io.first_record(real)
    except (OSError, _io.RootError):
        return None
    return rec if rec and _is_header(rec) else None


def detect(path):
    return _header(os.path.realpath(path)) is not None


def _chats(root):
    """The chats directory of every project directory directly under root. A file inside is confined when it is opened."""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [os.path.join(root, n, 'chats') for n in names if os.path.isdir(os.path.join(root, n, 'chats'))]


def find_sessions(cwd, root=None):
    """Paths of the sessions under `root` recorded for `cwd` (by project hash), newest first. A legacy .json
    file is skipped when a .jsonl of the same session exists. Sub-agent files are reached through their parent."""
    root = root or default_root()
    want = {project_hash(os.path.realpath(cwd)), project_hash(os.path.abspath(cwd))}
    best = {}
    for chats in _chats(root):
        try:
            names = os.listdir(chats)
        except OSError:
            continue
        for name in sorted(names):
            if not (name.startswith('session-') and name.endswith(('.jsonl', '.json'))):
                continue
            try:
                real = _io.confine(os.path.join(chats, name), root)
                hdr = _header(real)
                mtime = os.stat(real).st_mtime
            except (OSError, _io.RootError):
                continue
            if not hdr or hdr['projectHash'] not in want or hdr.get('kind') == 'subagent':
                continue
            key = hdr['sessionId']
            if key not in best or (real.endswith('.jsonl') and not best[key][1].endswith('.jsonl')):
                best[key] = (mtime, real)
    return [p for _, p in sorted(best.values(), reverse=True)]


def _parts_text(content):
    """The text of a recorded content value (a string, or a list of strings and {text} parts)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(p if isinstance(p, str) else (_io.s(p.get('text')) or '') for p in content if isinstance(p, (str, dict)))
    return ''


def _apply_patch(msgs, patch):
    mid = _io.s(patch.get('id'))
    msg = msgs.get(mid)
    if msg is None:
        return
    if 'content' in patch and patch['content'] is not None:
        msg['content'] = patch['content']
    calls = msg.get('toolCalls')
    if isinstance(patch.get('toolCalls'), list) and isinstance(calls, list):
        for tp in patch['toolCalls']:
            if not isinstance(tp, dict) or 'result' not in tp:
                continue
            for tc in calls:
                if isinstance(tc, dict) and tc.get('id') == tp.get('id'):
                    tc['result'] = tp['result']
                    break


def _load(real):
    """(metadata, messages) of a transcript: [(message dict, line number)] in order, after $set, $patch,
    $rewindTo and same-id replacement."""
    meta, msgs, lines = {}, {}, {}

    def put(rec, ln):
        msgs[rec['id']] = rec               # a repeated id keeps its place and takes the later record
        lines[rec['id']] = ln

    if real.endswith('.json'):
        obj = _legacy(real) or {}
        meta.update({k: v for k, v in obj.items() if k != 'messages'})
        for i, m in enumerate(obj.get('messages') or (), 1):
            if isinstance(m, dict) and isinstance(m.get('id'), str):
                put(m, i)
        return meta, [(m, lines[i]) for i, m in msgs.items()]
    for ln, rec in _io.records(real):
        rewind = rec.get('$rewindTo')
        patch = rec.get('$patch')
        if isinstance(rewind, str):
            if rewind in msgs:
                keep = list(msgs)
                for dead in keep[keep.index(rewind):]:
                    del msgs[dead]
            else:
                msgs.clear()
        elif isinstance(patch, dict):
            if isinstance(patch.get('id'), str):
                _apply_patch(msgs, patch)
            for upd in patch.get('updates') if isinstance(patch.get('updates'), list) else ():
                if isinstance(upd, dict):
                    _apply_patch(msgs, upd)
            for dead in patch.get('removeIds') if isinstance(patch.get('removeIds'), list) else ():
                if isinstance(dead, str):
                    msgs.pop(dead, None)
            if isinstance(patch.get('orderIds'), list):
                ordered = [i for i in patch['orderIds'] if isinstance(i, str) and i in msgs]
                rest = [i for i in msgs if i not in set(ordered)]
                kept = {i: msgs[i] for i in rest + ordered}
                msgs.clear()
                msgs.update(kept)
        elif isinstance(rec.get('id'), str):
            put(rec, ln)
        elif isinstance(rec.get('$set'), dict):
            upd = rec['$set']
            meta.update({k: v for k, v in upd.items() if k != 'messages'})
            if isinstance(upd.get('messages'), list):
                msgs.clear()
                for m in upd['messages']:
                    if isinstance(m, dict) and isinstance(m.get('id'), str):
                        put(m, ln)
        elif _is_header(rec):
            meta.update(rec)
    return meta, [(m, lines[i]) for i, m in msgs.items()]


def _response_text(result):
    """The text a recorded tool result carries: the `output` (or `error`) of each functionResponse."""
    if result is None:
        return None
    if isinstance(result, str):
        return result
    parts = [result] if isinstance(result, dict) else result if isinstance(result, list) else []
    out = []
    for p in parts:
        if isinstance(p, str):
            out.append(p)
            continue
        resp = _io.d(_io.d(p).get('functionResponse')).get('response')
        resp = _io.d(resp)
        text = _io.s(resp.get('output'))
        if text is None:
            text = _io.s(resp.get('error'))
        if text is not None:
            out.append(text)
    return '\n'.join(out) if out else None


def shell_exit_code(text, status):
    """The exit code of a run_shell_command output, or None when it cannot be told.

    The footer (after the output) holds `Exit Code: N` for N other than 0, followed by optional Signal,
    Background PIDs and Process Group PGID lines. No such line on a finished `Output:` result means exit 0."""
    if text is None:
        return None
    body = text.strip()
    if body.startswith('<untrusted_context'):
        body = body.split('\n', 1)[1] if '\n' in body else ''
        body = body.rsplit('</untrusted_context>', 1)[0]
    lines = body.rstrip().split('\n')
    n, signalled = len(lines), False
    for pattern in FOOTER:                  # from the end: Process Group PGID, Background PIDs, Signal
        if n and pattern.fullmatch(lines[n - 1]):
            signalled = signalled or pattern is FOOTER[2]
            n -= 1
    m = EXIT_LINE.fullmatch(lines[n - 1]) if n else None
    if m:
        return int(m.group(1))
    if status == 'success' and body.startswith('Output:') and not signalled:
        return 0
    return None


def _tool(tc):
    name = _io.s(tc.get('name'))
    status = _io.s(tc.get('status'))
    args = tc.get('args')
    is_shell = name in SHELL_TOOLS
    output = _response_text(tc.get('result'))
    code = shell_exit_code(output, status) if is_shell else None
    failed = status in ('error', 'cancelled') or code not in (None, 0)
    return Tool(_io.s(tc.get('id')), name, is_shell, _io.s(_io.d(args).get('command')) if is_shell else None,
                output, code, failed, args)


def _session(real, root, kind_hint=None, parent_id=None, depth=0, seen=None):
    meta, msgs = _load(real)
    kind = SUBAGENT if (kind_hint == SUBAGENT or meta.get('kind') == 'subagent') else MAIN
    sess = Session(HARNESS, _io.s(meta.get('sessionId')), kind=kind, parent_id=parent_id, started_at=_io.s(meta.get('startTime')))
    for msg, ln in msgs:
        ts, loc, typ = _io.s(msg.get('timestamp')), (real, ln), msg.get('type')
        text = _parts_text(msg.get('content'))
        if typ == 'user' and text.strip():
            injected = kind == SUBAGENT or text.lstrip().startswith(INJECTED_PREFIXES)
            sess.add(INJECTED if injected else USER_TEXT, ts, text, loc=loc)
        elif typ == 'gemini':
            if text.strip():
                sess.add(ASSISTANT_TEXT, ts, text, loc=loc)
            for tc in msg.get('toolCalls') if isinstance(msg.get('toolCalls'), list) else ():
                if isinstance(tc, dict):
                    sess.add(TOOL_CALL, _io.s(tc.get('timestamp')) or ts, tool=_tool(tc), loc=loc)
    sid = sess.id
    if sid and depth < MAX_DEPTH and seen is not None and sid not in seen:
        seen.add(sid)
        chats = os.path.dirname(real) if depth == 0 else os.path.dirname(os.path.dirname(real))
        sub = os.path.join(chats, _sanitize(sid))
        try:
            names = sorted(n for n in os.listdir(sub) if n.endswith('.jsonl'))[:MAX_CHILDREN]
        except OSError:
            names = []
        for name in names:
            try:
                child_real = _io.confine(os.path.join(sub, name), root)
            except _io.RootError:
                continue
            hdr = _header(child_real)
            if hdr and hdr.get('kind') == 'subagent':
                sess.children.append(_session(child_real, root, SUBAGENT, sid, depth + 1, seen))
    return sess


def read(path, root=None):
    root = root or default_root()
    real = _io.confine(path, root)
    return _session(real, root, None, None, 0, set())
