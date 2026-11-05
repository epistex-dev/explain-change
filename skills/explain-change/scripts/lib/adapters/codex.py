"""Codex CLI transcripts: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.

Ported from the SpecStory CLI provider for Codex (Apache-2.0) and the Codex session parser of tokscale (MIT);
the tool-output exit-code strings come from openai/codex `codex-rs/core/src/tools/context.rs` and
`tools/mod.rs` (Apache-2.0). See THIRD_PARTY_NOTICES.md. What is taken from each:

- SpecStory: the record shapes (`session_meta`, `event_msg` user_message / agent_message, `response_item`
  function_call / custom_tool_call and their outputs paired by call_id), the argument and output shapes, and
  `codexItemAsLegacyEvent` (Codex 0.147 writes `item_completed` thread items instead of `user_message`).
- tokscale: a forked or sub-agent rollout starts with the parent's history replayed; the replay ends at the
  first `turn_context` that belongs to the child, and `thread_source` / `source.subagent` say what a thread is.
- codex-rs: `Process exited with code N` and the older `Exit code: N` header lines of a shell output.

Changes: the result is the normalized model of model.py; replayed history is dropped, not counted;
a replayed turn is recognised by its UUIDv7 time against the child's even when the parent's session_meta
was not copied into the child.
"""
import json
import os
import re
import shlex

from . import _io
from .model import (ASSISTANT_TEXT, COMPACTION, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT, Session, Tool)

HARNESS = 'codex'
SHELL_TOOLS = frozenset(('exec_command', 'shell_command', 'shell', 'local_shell', 'container.exec'))
SUBAGENT_THREADS = frozenset(('subagent', 'guardian_review'))
# Text the harness puts in the user channel: a message wholly wrapped in one of these tags is not typed.
INJECTED_TAGS = ('environment_context', 'user_instructions', 'system-reminder', 'turn_aborted',
                 'user_shell_command', 'subagent_notification', 'permissions', 'collaboration_mode')
EXIT_HEADER = (re.compile(r'^Process exited with code (-?\d+)\s*$', re.M), re.compile(r'^Exit code: (-?\d+)\s*$', re.M))


def default_root():
    return os.path.join(os.path.expanduser('~'), '.codex', 'sessions')


def detect(path):
    """Whether the file's first record is a Codex `session_meta`."""
    try:
        rec = _io.first_record(os.path.realpath(path))
    except (OSError, _io.RootError):
        return False
    return bool(rec) and rec.get('type') == 'session_meta' and isinstance(rec.get('payload'), dict)


def _fork_parent(payload):
    """The id of the thread this one was forked from, if any (forked_from_id, or a spawned sub-agent's parent)."""
    fid = _io.s(payload.get('forked_from_id'))
    if fid:
        return fid
    spawn = _io.d(_io.d(_io.d(payload.get('source')).get('subagent')).get('thread_spawn'))
    return _io.s(spawn.get('parent_thread_id')) or None


def _is_subagent(payload):
    src = payload.get('source')
    return payload.get('thread_source') in SUBAGENT_THREADS or (isinstance(src, dict) and 'subagent' in src)


def _meta(rec):
    p = _io.d(rec.get('payload'))
    forked = _fork_parent(p)
    sub = _is_subagent(p)
    return {'id': _io.s(p.get('id')), 'cwd': _io.s(p.get('cwd')), 'started_at': _io.s(p.get('timestamp')) or _io.s(rec.get('timestamp')),
            'kind': SUBAGENT if sub else MAIN, 'forked_from': forked, 'user_fork': p.get('thread_source') == 'user',
            'parent_id': (_io.s(p.get('parent_thread_id')) or forked) if sub else forked}


def _header(real):
    rec = _io.first_record(real)
    if not rec or rec.get('type') != 'session_meta':
        return None
    return _meta(rec)


def _rollouts(root):
    """Every rollout-*.jsonl under root as a confined real path, in name (= time) order."""
    out = []
    for base, dirs, files in os.walk(root, followlinks=False):
        for f in files:
            if f.startswith('rollout-') and f.endswith('.jsonl'):
                try:
                    out.append(_io.confine(os.path.join(base, f), root))
                except _io.RootError:
                    pass
    return sorted(out, key=os.path.basename)


def find_sessions(cwd, root=None):
    """Paths of the non-sub-agent sessions under `root` recorded in `cwd`, newest first.
    A sub-agent's rollout is reached through its parent's `children`."""
    root = root or default_root()
    found = []
    for real in _rollouts(root):
        try:
            hdr = _header(real)
            mtime = os.stat(real).st_mtime
        except (OSError, _io.RootError):
            continue
        if hdr and hdr['kind'] == MAIN and _io.same_dir(hdr['cwd'], cwd):
            found.append((mtime, real))
    return [p for _, p in sorted(found, reverse=True)]


def _v7_key(uuid):
    """The UUIDv7 millisecond timestamp (12 hex digits) of an id, or None when it is not a v7 UUID."""
    if not isinstance(uuid, str):
        return None
    m = re.fullmatch(r'([0-9a-fA-F]{8})-([0-9a-fA-F]{4})-7[0-9a-fA-F]{3}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', uuid)
    return (m.group(1) + m.group(2)).lower() if m else None


def _turn_is_own(child_id, turn_id, user_fork, announced):
    """Whether a turn_context ends the replay of the parent's history in a forked rollout."""
    child, turn = _v7_key(child_id), _v7_key(turn_id)
    if turn_id is None or child is None:
        return True                    # an older rollout without turn ids: the first turn_context is the child's
    if turn is None:                   # a turn id that is not a UUIDv7 (an ancestor's): needs its own task_started
        return user_fork or turn_id in announced
    if turn != child:
        return turn > child
    return user_fork or turn_id in announced      # same millisecond: a user fork has no task_started


def _task_is_own(child_id, turn_id, started_at):
    """Whether a task_started seen during the replay announces the child's own turn, not an ancestor's."""
    child, turn = _v7_key(child_id), _v7_key(turn_id)
    if child is None:
        return True
    if turn is not None:
        return turn >= child
    if isinstance(started_at, (int, float)) and not isinstance(started_at, bool):
        return started_at >= int(child, 16) // 1000
    return False


def _item_text(item):
    parts = item.get('content')
    if not isinstance(parts, list):
        return ''
    return ''.join(p['text'] for p in parts if isinstance(p, dict) and isinstance(p.get('text'), str))


def _conversation(payload):
    """(kind, text) of an event_msg payload: 'user' / 'agent' with the message text, else (None, None).
    Codex 0.147 writes item_completed thread items where earlier versions wrote user_message / agent_message."""
    t = payload.get('type')
    if t == 'item_completed':
        item = _io.d(payload.get('item'))
        it = item.get('type')
        if it == 'UserMessage':
            return 'user', _item_text(item)
        if it == 'AgentMessage':
            return 'agent', _item_text(item)
        return None, None
    if t == 'user_message':
        return 'user', _io.s(payload.get('message')) or ''
    if t == 'agent_message':
        return 'agent', _io.s(payload.get('message')) or ''
    return None, None


def is_injected_text(text):
    """A message wholly wrapped in one of the harness's context tags, or an AGENTS.md instructions block."""
    t = text.strip()
    if t.startswith('# AGENTS.md instructions for'):
        return True
    return any(re.match(r'<%s[\s>]' % re.escape(tag), t) and t.endswith('</%s>' % tag) for tag in INJECTED_TAGS)


def _command(args):
    """The command line of an exec_command / shell_command / shell call as one string."""
    args = _io.d(args)
    cmd = args.get('cmd', args.get('command'))
    if isinstance(cmd, list) and all(isinstance(x, str) for x in cmd) and cmd:
        if len(cmd) >= 3 and os.path.basename(cmd[0]) in ('bash', 'sh', 'zsh') and cmd[1] in ('-lc', '-c'):
            return cmd[2]
        return shlex.join(cmd)
    return cmd if isinstance(cmd, str) else None


def _output(value):
    """(text, exit_code) of a function_call_output / custom_tool_call_output `output`.
    A string (plain, or JSON {"output", "metadata": {"exit_code"}}), a list of {text} items, or a dict."""
    code = None
    if isinstance(value, list):
        parts = []
        for it in value:
            if isinstance(it, dict):
                if isinstance(it.get('text'), str) and it['text']:
                    parts.append(it['text'])
                elif it.get('type') == 'input_image':
                    parts.append('[image]')
        return ('\n'.join(parts) if parts else None), None
    if isinstance(value, str):
        if value.lstrip().startswith('{'):
            try:
                obj = json.loads(value)
            except ValueError:
                obj = None
            if isinstance(obj, dict) and ('output' in obj or 'metadata' in obj):
                return _output(obj)
        return value, _header_exit(value)
    if isinstance(value, dict):
        out = value.get('output', value.get('content'))
        meta = _io.d(value.get('metadata'))
        c = meta.get('exit_code')
        code = c if isinstance(c, int) and not isinstance(c, bool) else None
        text, inner = _output(out) if out is not None else (None, None)
        return text, code if code is not None else inner
    return None, None


def _header_exit(text):
    """The exit code a shell output states in its header lines (the part before the `Output:` line)."""
    head = re.split(r'^Output:\s*$', text, maxsplit=1, flags=re.M)[0]
    for rx in EXIT_HEADER:
        m = rx.search(head)
        if m:
            return int(m.group(1))
    return None


def _parse(real):
    meta_seen = False
    sess = Session(HARNESS, None)
    fork = {}
    replaying = False
    announced = set()
    calls = {}        # call_id -> list of Events not yet paired
    ended = {}        # call_id -> exit code from an exec_command_end event
    all_calls = {}    # call_id -> every call event (for a late exec_command_end)

    for ln, rec in _io.records(real):
        typ = rec.get('type')
        payload = _io.d(rec.get('payload'))
        ts = _io.s(rec.get('timestamp'))
        loc = (real, ln)

        if typ == 'session_meta':
            if not meta_seen:          # only the file's own (first) metadata counts; a fork copies its parent's
                meta_seen = True
                fork = _meta(rec)
                sess.id, sess.cwd, sess.started_at = fork['id'], fork['cwd'], fork['started_at']
                sess.kind, sess.parent_id = fork['kind'], fork['parent_id']
                replaying = bool(fork['forked_from'])
            continue
        if replaying:
            if typ == 'event_msg' and payload.get('type') == 'task_started' and isinstance(payload.get('turn_id'), str):
                if _task_is_own(sess.id, payload['turn_id'], payload.get('started_at')):
                    announced.add(payload['turn_id'])
            elif typ == 'turn_context' and _turn_is_own(sess.id, _io.s(payload.get('turn_id')), fork['user_fork'], announced):
                replaying = False
            continue

        if typ == 'event_msg':
            t = payload.get('type')
            if t == 'exec_command_end':
                cid, code = _io.s(payload.get('call_id')), payload.get('exit_code')
                if cid and isinstance(code, int) and not isinstance(code, bool):
                    ended[cid] = code
                    for ev in all_calls.get(cid, ()):
                        if ev.tool.output is not None:
                            ev.tool.exit_code, ev.tool.is_error = code, code != 0
                continue
            who, text = _conversation(payload)
            if who == 'user' and text and text.strip():
                injected = sess.kind == SUBAGENT or is_injected_text(text)
                sess.add(INJECTED if injected else USER_TEXT, ts, text, loc=loc)
            elif who == 'agent' and text and text.strip():
                sess.add(ASSISTANT_TEXT, ts, text, loc=loc)

        elif typ == 'compacted':
            sess.add(COMPACTION, ts, _io.s(payload.get('message')), loc=loc)

        elif typ == 'response_item':
            t = payload.get('type')
            if t in ('function_call', 'custom_tool_call'):
                name, cid = _io.s(payload.get('name')), _io.s(payload.get('call_id'))
                if not name:
                    continue
                if t == 'function_call':
                    raw = payload.get('arguments')
                    try:
                        args = json.loads(raw) if isinstance(raw, str) and raw.strip() else None
                    except ValueError:
                        args = raw
                else:
                    args = _io.s(payload.get('input'))
                is_shell = t == 'function_call' and name in SHELL_TOOLS
                tool = Tool(cid, name, is_shell, _command(args) if is_shell else None, args=args)
                ev = sess.add(TOOL_CALL, ts, tool=tool, loc=loc)
                if cid:
                    calls.setdefault(cid, []).append(ev)
                    all_calls.setdefault(cid, []).append(ev)
            elif t in ('function_call_output', 'custom_tool_call_output'):
                cid = _io.s(payload.get('call_id'))
                queue = calls.get(cid)
                if not queue:
                    continue           # an output with no call
                tool = queue.pop(0).tool
                text, code = _output(payload.get('output'))
                tool.output = text if text is not None else ''
                if cid in ended:
                    code = ended[cid]
                tool.exit_code = code
                tool.is_error = tool.exit_code not in (None, 0)
    return sess


def _children(sess, real, rollouts, seen):
    """Attach the sub-agent rollouts whose parent is `sess` (they are written after it)."""
    me = os.path.basename(real)
    for other in rollouts:
        if os.path.basename(other) <= me or other in seen or not sess.id:
            continue
        hdr = _header(other)
        if hdr and hdr['kind'] == SUBAGENT and hdr['parent_id'] == sess.id:
            seen.add(other)
            child = _parse(other)
            sess.children.append(child)
            _children(child, other, rollouts, seen)


def read(path, root=None):
    root = root or default_root()
    real = _io.confine(path, root)
    sess = _parse(real)
    _children(sess, real, _rollouts(root), {real})
    return sess
