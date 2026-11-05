"""OpenCode transcripts: the SQLite database ~/.local/share/opencode/opencode.db, and the JSON tree
~/.local/share/opencode/storage/ that OpenCode before 1.2 wrote.

A transcript is one session inside the database, so find_sessions returns references of the form
`<database path>#<session id>` and read takes the same form. For the JSON tree the reference is the path of
the session file, `storage/session/<project>/<session id>.json`; its messages are `storage/message/<session id>/`
and their parts `storage/part/<message id>/` (or, in the oldest layout, `storage/part/<part id>.json` with a `messageID`).

Ported from the SpecStory CLI provider for OpenCode (Apache-2.0, see THIRD_PARTY_NOTICES.md): the 2.x schema
(`session_v2` / `session_message`, matching a repo by `session_v2.directory`, sub-agent sessions through
`parent_id`), the message record types and what each one means (`user`, `assistant` with `content[]` parts,
`shell` for a user `!command`, `synthetic` / `system` / `skill` scaffolding, `compaction` with its own summary),
the tool `state` shapes and `metadata.exit`. The 1.x schema (`session` / `message` / `part`, each row's `data`
a JSON object) and the JSON tree follow the OpenCode readers of agent-sessions (MIT) and tokscale (MIT).

Changes: the result is the normalized model of model.py; the database is opened read-only through a `mode=ro`
URI (committed write-ahead-log pages stay visible, nothing is written); rows are streamed, a row over
MAX_LINE bytes is skipped, and invalid UTF-8 is replaced; the text of a sub-agent session's first prompt is
INJECTED, not the user's; the model-facing `Command exited with code N.` item is not part of a shell output.
"""
import json
import os
import re
import sqlite3
import urllib.parse
from datetime import datetime, timezone

from . import _io
from .model import (ASSISTANT_TEXT, COMPACTION, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT, Session, Tool)

HARNESS = 'opencode'
DB_NAME = 'opencode.db'
BUSY_SECONDS = 2.0                 # how long a read waits for a writer's lock
SHELL_TOOLS = frozenset(('shell', 'bash'))
SUBAGENT_TOOLS = frozenset(('subagent', 'task'))
MAX_DEPTH = 8                      # nesting of sub-agent sessions followed
MAX_CHILDREN = 1000
EXIT_ITEM = re.compile(r'Command exited with code (-?\d+)\.')
V2_TABLES = ('session_v2', 'session_message')
V1_TABLES = ('session', 'message', 'part')


def default_root():
    return os.path.join(os.path.expanduser('~'), '.local', 'share', 'opencode')


def _split(ref):
    """(database path, session id) of a reference; the id is None for a bare database path."""
    db, sep, sid = ref.rpartition('#')
    return (db, sid) if sep else (ref, None)


def _connect(real):
    """A read-only connection to a resolved database path. Raises RootError for a non-regular file and
    StoreError when it cannot be opened. A file that is not an SQLite database fails at the first query."""
    _io.open_plain(real).close()          # refuses a FIFO or a directory before SQLite can block on it
    try:
        con = sqlite3.connect('file:%s?mode=ro' % urllib.parse.quote(real), uri=True, timeout=BUSY_SECONDS, isolation_level=None)
        con.text_factory = lambda b: b.decode('utf-8', 'replace')
        con.execute('PRAGMA trusted_schema = OFF')
        return con
    except sqlite3.Error as e:
        raise _io.StoreError('cannot open %s: %s' % (real, e))


def _tables(con):
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(con, table):
    return {r[1] for r in con.execute('PRAGMA table_info(%s)' % table)}


def _is_tree(path):
    """Whether a reference names a session file of the JSON tree (a database reference is `<database>#<id>`)."""
    return path.endswith('.json') and not path.rpartition('#')[0].endswith(DB_NAME)


def detect(path):
    """Whether the file is an SQLite database with OpenCode's session tables (2.x or 1.x)."""
    if _is_tree(path):
        try:
            return isinstance(_tree_json(os.path.realpath(path)).get('id'), str) and os.path.basename(os.path.dirname(os.path.dirname(path))) == 'session'
        except OSError:
            return False
    try:
        con = _connect(os.path.realpath(_split(path)[0]))
    except (OSError, _io.RootError, _io.StoreError):
        return False
    try:
        names = _tables(con)
        return all(t in names for t in V2_TABLES) or all(t in names for t in V1_TABLES)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open_db(db, root):
    """(connection, real database path) for a database path under root."""
    real = _io.confine(db, root)
    return _connect(real), real


def find_sessions(cwd, root=None):
    """References of the top-level sessions recorded in `cwd`, newest first. A sub-agent session is reached
    through its parent's `children`."""
    root = root or default_root()
    dirs = sorted({os.path.realpath(cwd), os.path.abspath(cwd)})
    found = _db_sessions(root, dirs) + _tree_found(root, dirs)
    return [ref for _, ref in sorted(found, reverse=True)]


def _db_sessions(root, dirs):
    """(updated, reference) of the top-level sessions of the database under root recorded in one of `dirs`."""
    try:
        con, real = _open_db(os.path.join(root, DB_NAME), root)
    except (OSError, _io.RootError, _io.StoreError):
        return []
    marks = ','.join('?' * len(dirs))
    found = []
    try:
        names = _tables(con)
        for table, needed in (('session_v2', V2_TABLES), ('session', V1_TABLES)):
            if not all(t in names for t in needed):
                continue
            top = ' AND parent_id IS NULL' if 'parent_id' in _columns(con, table) else ''
            for sid, updated in con.execute('SELECT id, time_updated FROM %s WHERE directory IN (%s)%s' % (table, marks, top), dirs):
                if isinstance(sid, str) and '#' not in sid:
                    found.append((updated if isinstance(updated, (int, float)) else 0, real + '#' + sid))
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return found


def _tree_found(root, dirs):
    """(updated, path) of the top-level session files of the pre-1.2 JSON tree recorded in one of `dirs`."""
    out = []
    for info, real in _tree_sessions(root):
        if info.get('directory') in dirs and not info.get('parentID'):
            upd = _io.d(info.get('time')).get('updated')
            out.append((upd if isinstance(upd, (int, float)) else 0, real))
    return out


def _iso(ms):
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    except (OverflowError, OSError, ValueError):
        return None


def _json(raw):
    """The JSON object in a row's data column, or an empty dict."""
    if not isinstance(raw, str):
        return {}
    try:
        v = json.loads(raw)
    except ValueError:
        return {}
    return v if isinstance(v, dict) else {}


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == int(v):
        return int(v)
    if isinstance(v, str) and re.fullmatch(r'\s*-?\d{1,18}\s*', v):
        return int(v)
    return None


def _data_column(name='data'):
    """A column read only when it is within the row size cap, so one huge row is skipped, not loaded."""
    return 'CASE WHEN length(CAST(%s AS BLOB)) <= %d THEN %s END' % (name, _io.MAX_LINE, name)


def _tool(call_id, name, args, status, texts, error, meta, exit_hint=None):
    """A Tool from the fields both schemas share."""
    is_shell = name in SHELL_TOOLS
    inp = args if isinstance(args, (dict, str)) else None
    command = _io.s(_io.d(inp).get('command')) if is_shell else None
    code = _int(meta.get('exit'))
    if exit_hint is not None and code is None:
        code = exit_hint
    finished = status in ('completed', 'error', 'success')
    output = None
    if finished:
        output = error if (status == 'error' and error) else ('\n'.join(texts) if texts else None)
    failed = status == 'error' or meta.get('error') is True
    return Tool(call_id, name, is_shell, command, output, code, failed or code not in (None, 0), inp)


def _v2_tool(item):
    state = _io.d(item.get('state'))
    meta = _io.d(state.get('metadata'))
    status = _io.s(state.get('status'))
    items = [c for c in state.get('content') or () if isinstance(c, dict) and c.get('type') == 'text' and isinstance(c.get('text'), str)] \
        if isinstance(state.get('content'), list) else []
    texts = [c['text'] for c in items]
    hint = None
    name = _io.s(item.get('name'))
    if name in SHELL_TOOLS and texts:
        m = EXIT_ITEM.fullmatch(texts[-1])         # only the closing item: the output body is a separate item
        if m:
            hint = int(m.group(1))
            texts = texts[:-1]
    return _tool(_io.s(item.get('id')), name, state.get('input'), status, texts,
                 _io.s(_io.d(state.get('error')).get('message')), meta, hint), meta


def _v1_tool(part):
    state = _io.d(part.get('state'))
    meta = _io.d(state.get('metadata'))
    out = _io.s(state.get('output'))
    err = state.get('error')
    err = err if isinstance(err, str) else _io.s(_io.d(err).get('message'))
    return _tool(_io.s(part.get('callID')) or _io.s(part.get('id')), _io.s(part.get('tool')), state.get('input'),
                 _io.s(state.get('status')), [out] if out is not None else [], err, meta), meta


def _child_ref(meta):
    return _io.s(meta.get('sessionID')) or _io.s(meta.get('sessionId'))


class _Reader:
    def __init__(self, con, real):
        self.con, self.real, self.seen = con, real, set()
        self.names = _tables(con)

    def has(self, tables):
        return all(t in self.names for t in tables)

    def session(self, sid, kind=MAIN, parent_id=None, depth=0):
        """The session `sid` and its sub-agent sessions, or None when no table holds it."""
        if sid in self.seen:
            return None
        self.seen.add(sid)
        link = {}
        sess, table = None, 'session_v2'
        if self.has(V2_TABLES):
            sess = self._v2(sid, kind, parent_id, link)
        if sess is None and self.has(V1_TABLES):
            sess = self._v1(sid, kind, parent_id, link)
            table = 'session'
        if sess is None:
            return None
        if depth < MAX_DEPTH and 'parent_id' in _columns(self.con, table):
            kids = [r[0] for r in self.con.execute('SELECT id FROM %s WHERE parent_id = ? ORDER BY time_created, id LIMIT %d' % (table, MAX_CHILDREN), (sid,))]
            for kid in kids:
                child = self.session(kid, SUBAGENT, sid, depth + 1) if isinstance(kid, str) else None
                if child:
                    child.parent_call_id = link.get(kid)
                    sess.children.append(child)
        return sess

    def _head(self, table, sid, kind, parent_id):
        row = self.con.execute('SELECT directory, time_created FROM %s WHERE id = ?' % table, (sid,)).fetchone()
        if row is None:
            return None
        return Session(HARNESS, sid, cwd=_io.s(row[0]), started_at=_iso(row[1]), kind=kind, parent_id=parent_id)

    def _v2(self, sid, kind, parent_id, link):
        sess = self._head('session_v2', sid, kind, parent_id)
        if sess is None:
            return None
        rows = self.con.execute('SELECT type, seq, time_created, %s FROM session_message WHERE session_id = ? ORDER BY seq' % _data_column(), (sid,))
        for typ, seq, created, raw in rows:
            data = _json(raw)
            ts = _iso(_io.d(data.get('time')).get('created')) or _iso(created)
            loc = (self.real, seq if isinstance(seq, int) else 0)
            if typ == 'user':
                text = _io.s(data.get('text'))
                if text and text.strip():
                    sess.add(USER_TEXT if kind == MAIN else INJECTED, ts, text, loc=loc)
            elif typ == 'shell':
                self._shell(sess, data, ts, loc)
            elif typ in ('synthetic', 'system', 'skill'):
                text = _io.s(data.get('text'))
                if text and text.strip() and _io.d(data.get('metadata')).get('source') != 'shell':   # the shell echo repeats the shell record
                    sess.add(INJECTED, ts, text, loc=loc)
            elif typ == 'compaction':
                summary = _io.s(data.get('summary'))
                if data.get('status') == 'completed' and summary and summary.strip():
                    sess.add(COMPACTION, ts, summary, loc=loc)
            elif typ == 'assistant' and isinstance(data.get('content'), list):
                for item in data['content']:
                    if not isinstance(item, dict):
                        continue
                    if item.get('type') == 'text':
                        text = _io.s(item.get('text'))
                        if text and text.strip():
                            sess.add(ASSISTANT_TEXT, ts, text, loc=loc)
                    elif item.get('type') == 'tool':
                        tool, meta = _v2_tool(item)
                        sess.add(TOOL_CALL, _iso(_io.d(item.get('time')).get('created')) or ts, tool=tool, loc=loc)
                        self._link(link, tool, meta)
        return sess

    @staticmethod
    def _link(link, tool, meta):
        child = _child_ref(meta)
        if tool.name in SUBAGENT_TOOLS and child and tool.call_id:
            link[child] = tool.call_id

    @staticmethod
    def _shell(sess, data, ts, loc):
        command = _io.s(data.get('command'))
        if not command or not command.strip():
            return
        out = _io.d(data.get('output'))
        code = _int(data.get('exit'))
        failed = code not in (None, 0) or data.get('status') in ('timeout', 'killed')
        tool = Tool(None, 'shell', True, command, _io.s(out.get('output')), code, failed, {'command': command}, by_user=True)
        sess.add(TOOL_CALL, ts, tool=tool, loc=loc)

    def _v1(self, sid, kind, parent_id, link):
        sess = self._head('session', sid, kind, parent_id)
        if sess is None:
            return None
        msgs = self.con.execute('SELECT id, time_created, %s FROM message WHERE session_id = ? ORDER BY time_created, id' % _data_column(), (sid,))
        for n, (mid, created, raw) in enumerate(msgs, 1):
            parts = self.con.execute('SELECT %s FROM part WHERE message_id = ? ORDER BY time_created, id' % _data_column(), (mid,))
            msg = _json(raw)
            v1_message(sess, kind, msg, _iso(_io.d(msg.get('time')).get('created')) or _iso(created), (self.real, n),
                       (_json(praw) for (praw,) in parts), link)
        return sess


def v1_message(sess, kind, msg, ts, loc, parts, link):
    """Add the events of one 1.x message (SQLite `message` + `part` rows, or the JSON tree's files) to `sess`."""
    role = msg.get('role')
    summary = msg.get('summary') is True            # an assistant message that is the compaction summary
    for part in parts:
        text = _io.s(part.get('text'))
        if part.get('type') == 'text' and text and text.strip():
            if role == 'user':
                if part.get('ignored') is not True:
                    sess.add(INJECTED if part.get('synthetic') is True or kind != MAIN else USER_TEXT, ts, text, loc=loc)
            elif role == 'assistant':
                sess.add(COMPACTION if summary else ASSISTANT_TEXT, ts, text, loc=loc)
        elif part.get('type') == 'tool' and role == 'assistant':
            tool, meta = _v1_tool(part)
            sess.add(TOOL_CALL, ts, tool=tool, loc=loc)
            _Reader._link(link, tool, meta)


# ---------------------------------------------------------------- the JSON tree of OpenCode before 1.2

TREE = 'storage'
TREE_FILES = 100000                # files read per directory


def _tree_json(real):
    """The JSON object in a tree file, or {}. A file over the size cap or not valid is {}."""
    try:
        with _io.open_plain(real) as fh:
            raw = fh.read(_io.MAX_LINE + 1)
    except (OSError, _io.RootError):
        return {}
    if len(raw) > _io.MAX_LINE:
        return {}
    return _json(raw.decode('utf-8', 'replace'))


def _tree_files(directory, root):
    """The confined real paths of the .json files directly in a directory, sorted by name."""
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith('.json'))[:TREE_FILES]
    except OSError:
        return []
    out = []
    for n in names:
        try:
            out.append(_io.confine(os.path.join(directory, n), root))
        except _io.RootError:
            continue
    return out


def _tree_sessions(root):
    """(info dict, real path) of every session file of the tree under root."""
    base = os.path.join(root, TREE, 'session')
    try:
        projects = sorted(os.listdir(base))
    except OSError:
        return
    for proj in projects:
        for real in _tree_files(os.path.join(base, proj), root):
            info = _tree_json(real)
            if isinstance(info.get('id'), str):
                yield info, real


def _tree_ms(info):
    t = _io.d(info.get('time'))
    return t.get('created') if isinstance(t.get('created'), (int, float)) else 0


def _tree_session(info, root, kind=MAIN, parent_id=None, depth=0, seen=None):
    sid = info['id']
    seen = set() if seen is None else seen
    seen.add(sid)
    sess = Session(HARNESS, sid, cwd=_io.s(info.get('directory')), started_at=_iso(_tree_ms(info)), kind=kind, parent_id=parent_id)
    link = {}
    msgs = [(m, p) for p in _tree_files(os.path.join(root, TREE, 'message', sid), root) for m in (_tree_json(p),) if m]
    msgs.sort(key=lambda mp: (_tree_ms(mp[0]), _io.s(mp[0].get('id')) or ''))
    flat = None
    for n, (msg, mpath) in enumerate(msgs, 1):
        mid = _io.s(msg.get('id'))
        parts_dir = os.path.join(root, TREE, 'part', mid) if mid else None
        files = _tree_files(parts_dir, root) if parts_dir and os.path.isdir(parts_dir) else None
        if files is None:                     # the older flat layout: part/<part id>.json, each naming its message
            if flat is None:
                flat = {}
                ids = {_io.s(m.get('id')) for m, _ in msgs}
                for pp in _tree_files(os.path.join(root, TREE, 'part'), root):
                    part = _tree_json(pp)
                    if part.get('messageID') in ids:
                        flat.setdefault(part['messageID'], []).append((_tree_ms(part) or _tree_ms({'time': {'created': _io.d(part.get('time')).get('start')}}), os.path.basename(pp), part))
            parts = [x[2] for x in sorted(flat.get(mid, ()), key=lambda x: (x[0], x[1]))]
        else:
            parts = sorted((_tree_json(f) for f in files), key=lambda x: (_io.d(x.get('time')).get('start') if isinstance(_io.d(x.get('time')).get('start'), (int, float)) else 0, _io.s(x.get('id')) or ''))
        v1_message(sess, kind, msg, _iso(_tree_ms(msg)), (mpath, 1), iter(parts), link)
    if depth < MAX_DEPTH:
        kids = [(i, r) for i, r in _tree_sessions(root) if i.get('parentID') == sid][:MAX_CHILDREN]
        for info_k, real_k in sorted(kids, key=lambda x: (_tree_ms(x[0]), x[0]['id'])):
            if info_k['id'] in seen:
                continue
            child = _tree_session(info_k, root, SUBAGENT, sid, depth + 1, seen)
            child.parent_call_id = link.get(info_k['id'])
            sess.children.append(child)
    return sess


def _tree_read(path, root):
    real = _io.confine(path, root)
    info = _tree_json(real)
    if not isinstance(info.get('id'), str):
        raise _io.StoreError('not an OpenCode session file: %s' % real)
    return _tree_session(info, root)


def read(path, root=None):
    """The session a reference names, with its sub-agent sessions as children."""
    root = root or default_root()
    if _is_tree(path):
        return _tree_read(path, root)
    db, sid = _split(path)
    con, real = _open_db(db, root)
    try:
        if not sid:
            raise _io.StoreError('name a session as <database>#<session id>: %s' % path)
        sess = _Reader(con, real).session(sid)
        if sess is None:
            raise _io.StoreError('no session %s in %s' % (sid, real))
        return sess
    except sqlite3.Error as e:
        raise _io.StoreError('cannot read %s: %s' % (real, e))
    finally:
        con.close()
