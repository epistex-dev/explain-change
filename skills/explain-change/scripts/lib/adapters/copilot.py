"""GitHub Copilot CLI transcripts: ~/.copilot/session-state/<session-id>/events.jsonl.

The record handling follows the SpecStory CLI provider for Copilot (Apache-2.0, see THIRD_PARTY_NOTICES.md):
`classifyUserMessage` for which user.message records are typed prompts, the toolRequests / tool.execution_complete
pairing by toolCallId, and the rule that a shell command's exit code is `shellExecution.exitCode` because
`success` stays true when the command failed. Changes: the result is the normalized model of model.py, the
exit code also falls back to the trailing `<shellId: ... completed with exit code N>` line, and sub-agent
records become child sessions.
"""
import os
import re
from collections import deque

from . import _io
from .model import (ASSISTANT_TEXT, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT, Session, Tool)

HARNESS = 'copilot'
EVENTS_FILE = 'events.jsonl'

SHELL_TOOLS = frozenset((
    'bash', 'read_bash', 'stop_bash', 'list_bash', 'write_bash', 'local_shell',
    'powershell', 'read_powershell', 'write_powershell', 'stop_powershell', 'list_powershell'))

NOTE_OPEN, NOTE_CLOSE = '<system_notification>', '</system_notification>'
CROSS_SESSION_TAG = '<cross_session_message>'
EXIT_LINE = re.compile(r'<shellId:[^>]*?completed with exit code (-?\d{1,18})>')      # a longer number is not an exit code


def default_root():
    return os.path.join(os.path.expanduser('~'), '.copilot', 'session-state')


def detect(path):
    """Whether the file's first record is a Copilot `session.start`."""
    try:
        rec = _io.first_record(os.path.realpath(path))
    except (OSError, _io.RootError):
        return False
    return bool(rec) and rec.get('type') == 'session.start' and isinstance(rec.get('data'), dict)


def _header(real):
    rec = _io.first_record(real)
    if not rec or rec.get('type') != 'session.start':
        return None
    data = _io.d(rec.get('data'))
    return {'id': _io.s(data.get('sessionId')), 'cwd': _io.s(_io.d(data.get('context')).get('cwd')),
            'started_at': _io.s(data.get('startTime')) or _io.s(rec.get('timestamp'))}


def find_sessions(cwd, root=None):
    """Paths of the sessions under `root` whose session.start cwd is `cwd`, newest first."""
    root = root or default_root()
    try:
        names = os.listdir(root)
    except OSError:
        return []
    found = []
    for name in names:
        try:
            real = _io.confine(os.path.join(root, name, EVENTS_FILE), root)
            hdr = _header(real)
            mtime = os.stat(real).st_mtime
        except (OSError, _io.RootError):
            continue
        if hdr and _io.same_dir(hdr['cwd'], cwd):
            found.append((mtime, real))
    return [p for _, p in sorted(found, reverse=True)]


def classify_user_message(data):
    """'user' for a typed prompt, 'agent' for a sub-agent's prompt, 'session' for a message from another
    Copilot session, None for harness machinery or empty text. An allowlist: only an empty or `user`
    source is real input; a runtime notice must be wrapped in its tags end to end."""
    content = (_io.s(data.get('content')) or '').strip()
    source = _io.s(data.get('source')) or ''
    if not content:
        return None
    if content.startswith(NOTE_OPEN) and content.endswith(NOTE_CLOSE):
        return None
    if source.startswith('agent-'):
        return 'agent'
    if source not in ('', 'user'):
        return None
    transformed = _io.s(data.get('transformedContent')) or ''
    if CROSS_SESSION_TAG in transformed.replace(_io.s(data.get('content')) or '', '', 1):
        return 'session'
    return 'user'


def _exit_code(data, output, is_shell):
    shell = _io.d(data.get('shellExecution'))
    code = shell.get('exitCode')
    if isinstance(code, int) and not isinstance(code, bool):
        return code
    if is_shell and output:
        m = None
        for m in EXIT_LINE.finditer(output[-2000:]):
            pass
        if m:
            return int(m.group(1))
    return None


def read(path, root=None):
    real = _io.confine(path, root or default_root())
    main = Session(HARNESS, None, kind=MAIN)
    subs = {}              # agent key -> child Session, in creation order
    agent_of_call = {}     # launching toolCallId -> agent key
    pending = {}           # toolCallId -> deque of unpaired call events
    seen_start = False

    def child(key, launched_by=None, ts=None):
        c = subs.get(key)
        if c is None:
            c = subs[key] = Session(HARNESS, key, kind=SUBAGENT, started_at=ts)
        if launched_by and not c.parent_call_id:
            c.parent_call_id = launched_by
        return c

    for ln, rec in _io.records(real):
        typ = _io.s(rec.get('type'))
        data = _io.d(rec.get('data'))
        ts = _io.s(rec.get('timestamp'))
        loc = (real, ln)
        agent = _io.s(rec.get('agentId'))
        parent_call = _io.s(data.get('parentToolCallId'))

        if typ == 'session.start' and not seen_start:
            seen_start = True
            main.id = _io.s(data.get('sessionId'))
            main.cwd = _io.s(_io.d(data.get('context')).get('cwd'))
            main.started_at = _io.s(data.get('startTime')) or ts
            continue
        if typ == 'subagent.started':
            key = agent or _io.s(data.get('toolCallId'))
            if key:
                child(key, _io.s(data.get('toolCallId')), ts)
                if _io.s(data.get('toolCallId')):
                    agent_of_call[data['toolCallId']] = key
            continue

        key = agent or agent_of_call.get(parent_call) or parent_call
        sess = child(key, parent_call, ts) if key else main

        if typ == 'user.message':
            kind = classify_user_message(data)
            if kind is None:
                text = _io.s(data.get('content'))
                if text and text.strip():
                    sess.add(INJECTED, ts, text, loc=loc)
            elif kind == 'user' and sess is main:
                sess.add(USER_TEXT, ts, data['content'], loc=loc)
            else:   # a sub-agent's prompt, a message from another session, or any user.message inside a sub-agent
                sess.add(INJECTED, ts, data['content'], loc=loc)

        elif typ == 'assistant.message':
            content = _io.s(data.get('content'))
            if content and content.strip():
                sess.add(ASSISTANT_TEXT, ts, content, loc=loc)
            reqs = data.get('toolRequests')
            for req in reqs if isinstance(reqs, list) else ():
                if not isinstance(req, dict):
                    continue
                name = _io.s(req.get('name'))
                args = req.get('arguments')
                if name == 'task_complete':        # the closing answer the user sees
                    summary = _io.s(_io.d(args).get('summary'))
                    if summary:
                        sess.add(ASSISTANT_TEXT, ts, summary, loc=loc)
                    continue
                is_shell = name in SHELL_TOOLS
                command = _io.s(_io.d(args).get('command')) if is_shell else None
                tool = Tool(_io.s(req.get('toolCallId')), name, is_shell, command, args=args)
                ev = sess.add(TOOL_CALL, ts, loc=loc, tool=tool)
                if tool.call_id:
                    pending.setdefault(tool.call_id, deque()).append(ev)

        elif typ == 'tool.user_requested':
            name = _io.s(data.get('toolName'))
            args = data.get('arguments')
            is_shell = name in SHELL_TOOLS
            command = _io.s(_io.d(args).get('command')) if is_shell else None
            tool = Tool(_io.s(data.get('toolCallId')), name, is_shell, command, args=args, by_user=True)
            ev = main.add(TOOL_CALL, ts, loc=loc, tool=tool)
            if tool.call_id:
                pending.setdefault(tool.call_id, deque()).append(ev)

        elif typ == 'tool.execution_complete':
            queue = pending.get(_io.s(data.get('toolCallId')))
            if not queue:
                continue                  # an output with no call
            tool = queue.popleft().tool
            err = _io.s(_io.d(data.get('error')).get('message'))
            res = _io.s(_io.d(data.get('result')).get('content'))
            tool.output = err if (data.get('success') is False or res is None) and err is not None else res
            tool.exit_code = _exit_code(data, tool.output, tool.is_shell)
            failed = data.get('success') is False or isinstance(data.get('error'), dict)
            tool.is_error = failed or tool.exit_code not in (None, 0)

    main.children = list(subs.values())
    for c in main.children:
        c.cwd, c.parent_id = main.cwd, main.id
    return main
