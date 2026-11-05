"""Cursor CLI transcripts: ~/.cursor/projects/<project folder>/agent-transcripts/<uuid>/<uuid>.jsonl, with sub-agent
transcripts in <uuid>/subagents/*.jsonl.

Ported from agent-sessions (MIT, see THIRD_PARTY_NOTICES.md), `Services/CursorSessionParser.swift`:

- A line is `{role, message: {content: [blocks]}}`. Blocks are `text`, `thinking`, `tool_use` (`tool_call`, `tool-use`,
  `tool-call`: `{name, input}`) and, in some drifted captures, `tool_result`. The typed text of a user message is
  wrapped in `<user_query>...</user_query>`; the parser unwraps it. The format records no timestamps and no tool results:
  the Shell tool's `input.command` is the whole record of a command.
- `detectSubagentInfo`: a file in `<uuid>/subagents/` is a sub-agent of the session `<uuid>`.
- `inferCWD` / `inferCWDBestEffort`: the only place the working directory is recorded is the project folder's name.

The project folder name is the absolute path with every `/` replaced by `-` and the leading `/` dropped. Two different
paths can give the same name (`/a/b-c` and `/a-b/c` are both `a-b-c`), so the folder alone does not say which directory
it stands for. `find_sessions` treats a folder as belonging to `cwd` when its name equals the name of the real path of
`cwd`; `Session.cwd` is the path the Swift parser decodes, a left-to-right walk that takes a `-` as a separator while the
path so far is an existing directory, and which is None when the decoded directory does not exist.

Changes: the result is the normalized model of model.py. Only the text inside `<user_query>` is the user's: any other
text of a user message (attachments, context the harness added) and every user message of a sub-agent file is INJECTED.
The format has no tool results, so a tool's output, exit code and failure flag stay unset; a `tool_result` block is
neither user text nor an output. A sub-agent call carries no id that names its file, so parent_call_id stays None.
"""
import os
import re

from . import _io
from .model import (ASSISTANT_TEXT, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT, Session, Tool)

HARNESS = 'cursor-cli'
SHELL_TOOLS = frozenset(('Shell',))
TOOL_BLOCKS = frozenset(('tool_use', 'tool-use', 'tool_call', 'tool-call'))
USER_ROLES = frozenset(('user', 'human'))
ASSISTANT_ROLES = frozenset(('assistant', 'model'))
QUERY = re.compile(r'<user_query>(.*?)</user_query>', re.S)
UUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')
MAX_CHILDREN = 1000
NOT_PROJECTS = frozenset(('projects', 'empty-window'))


def default_root():
    return os.path.join(os.path.expanduser('~'), '.cursor', 'projects')


def project_slug(path):
    """The project folder name of an absolute path: `/` replaced by `-`, the leading `/` dropped."""
    return path.strip('/').replace('/', '-')


def decode_slug(name, is_dir=os.path.isdir):
    """The path a project folder name stands for, or None when that directory does not exist.

    A walk from the left: the name is split at every `-`; a piece closes a path component when the path so far plus
    that component is an existing directory, and otherwise the `-` stays inside the component. When the result is not a
    directory either, the name with every `-` read as `/` is tried."""
    if name in NOT_PROJECTS or not name:
        return None
    segments = name.split('-')
    prefix, current = '', segments[0]
    for seg in segments[1:]:
        candidate = prefix + '/' + current
        if is_dir(candidate):
            prefix, current = candidate, seg
        else:
            current = current + '-' + seg
    best = prefix + '/' + current
    if is_dir(best):
        return best
    naive = '/' + name.replace('-', '/')
    return naive if is_dir(naive) else None


def _role(rec):
    role = _io.s(rec.get('role'))
    return role.lower() if role else None


def _is_record(rec):
    return _role(rec) in USER_ROLES | ASSISTANT_ROLES and isinstance(rec.get('message'), dict) and 'type' not in rec


def _first(real):
    try:
        return _io.first_record(real)
    except (OSError, _io.RootError):
        return None


def detect(path):
    """Whether the file's first record is a Cursor transcript line: a top-level `role` and a `message` object."""
    rec = _first(os.path.realpath(path))
    return bool(rec) and _is_record(rec)


def _transcripts(root, slugs):
    """The top-level transcript files `<project>/agent-transcripts/<id>/<id>.jsonl` of the project folders named in slugs."""
    out = []
    for slug in sorted(slugs):
        base = os.path.join(root, slug, 'agent-transcripts')
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for sid in names:
            try:
                real = _io.confine(os.path.join(base, sid, sid + '.jsonl'), root)
                mtime = os.stat(real).st_mtime
            except (OSError, _io.RootError):
                continue
            rec = _first(real)
            if rec and _is_record(rec):
                out.append((mtime, real))
    return out


def find_sessions(cwd, root=None):
    """Paths of the top-level transcripts under `root` whose project folder is named for `cwd`, newest first.
    A sub-agent transcript is reached through its parent."""
    root = root or default_root()
    slugs = {project_slug(os.path.realpath(cwd)), project_slug(os.path.abspath(cwd))} - {''}
    return [p for _, p in sorted(_transcripts(root, slugs), reverse=True)]


def _blocks(message):
    content = message.get('content')
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _split_user(text):
    """[(is_query, text)] of a user text: the inside of each <user_query> element, and the text around them."""
    out, pos = [], 0
    for m in QUERY.finditer(text):
        out.append((False, text[pos:m.start()]))
        out.append((True, m.group(1)))
        pos = m.end()
    out.append((False, text[pos:]))
    return [(q, t.strip()) for q, t in out if t.strip()]


def _tool(block):
    name = _io.s(block.get('name')) or _io.s(block.get('tool'))
    args = block.get('input')
    is_shell = name in SHELL_TOOLS
    return Tool(_io.s(block.get('id')), name, is_shell, _io.s(_io.d(args).get('command')) if is_shell else None, args=args)


def _subagent_parent(real):
    """The session id a file in `<uuid>/subagents/` belongs to, or None."""
    parent = os.path.dirname(real)
    if os.path.basename(parent) != 'subagents':
        return None
    sid = os.path.basename(os.path.dirname(parent))
    return sid if UUID.fullmatch(sid) else None


def _project(real):
    parts = real.split(os.sep)
    for i in range(len(parts) - 1, 0, -1):
        if parts[i] == 'agent-transcripts':
            return parts[i - 1]
    return None


def _session(real, root, kind, parent_id):
    stem = os.path.basename(real)[:-len('.jsonl')] if real.endswith('.jsonl') else os.path.basename(real)
    project = _project(real)
    sess = Session(HARNESS, stem, cwd=decode_slug(project) if project else None, kind=kind, parent_id=parent_id)
    for ln, rec in _io.records(real):
        role = _role(rec)
        if role not in USER_ROLES and role not in ASSISTANT_ROLES:
            continue
        loc = (real, ln)
        for block in _blocks(_io.d(rec.get('message'))):
            typ = (_io.s(block.get('type')) or '').lower()
            if typ in TOOL_BLOCKS:
                if role in ASSISTANT_ROLES:
                    sess.add(TOOL_CALL, tool=_tool(block), loc=loc)
                continue
            text = _io.s(block.get('text'))
            if typ in ('thinking', 'tool_result', 'tool-result') or not text:
                continue
            if role in USER_ROLES:
                for is_query, part in _split_user(text):
                    sess.add(USER_TEXT if is_query and kind == MAIN else INJECTED, text=part, loc=loc)
            elif text.strip():
                sess.add(ASSISTANT_TEXT, text=text, loc=loc)
    if kind == MAIN:
        sub = os.path.join(os.path.dirname(real), 'subagents')
        try:
            names = sorted(n for n in os.listdir(sub) if n.endswith('.jsonl'))[:MAX_CHILDREN]
        except OSError:
            names = []
        for name in names:
            try:
                child = _io.confine(os.path.join(sub, name), root)
            except _io.RootError:
                continue
            rec = _first(child)
            if rec and _is_record(rec):
                sess.children.append(_session(child, root, SUBAGENT, stem))
    return sess


def read(path, root=None):
    """The session a transcript file holds. A file in `<uuid>/subagents/` is read as a sub-agent of that session."""
    root = root or default_root()
    real = _io.confine(path, root)
    parent = _subagent_parent(real)
    return _session(real, root, SUBAGENT if parent else MAIN, parent)
