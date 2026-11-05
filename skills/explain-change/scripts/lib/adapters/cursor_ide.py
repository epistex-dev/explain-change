"""Cursor IDE conversations: the key-value table `cursorDiskKV` of <Cursor user data>/User/globalStorage/state.vscdb.

One database holds every conversation of every project, so a transcript is one composer inside it. find_sessions returns
references of the form `<database path>#<composer id>`, and read takes the same form. The user data directory is
`~/.config/Cursor` on Linux, `~/Library/Application Support/Cursor` on macOS and `%APPDATA%\\Cursor` (by default
`~\\AppData\\Roaming\\Cursor`) on Windows.

Ported from the SpecStory CLI provider `cursoride` (Apache-2.0, see THIRD_PARTY_NOTICES.md): `CURSORIDE-FORMAT.md`,
`types.go`, `database.go`, `agent_session.go` and `tool_shell.go`.

- `composerData:<composer id>` holds the conversation's metadata: `_v`, `createdAt` and `lastUpdatedAt` (epoch milliseconds),
  `workspaceIdentifier.uri.fsPath` (the folder the conversation was opened in; Cursor 3.12 and later), the ordered
  `fullConversationHeadersOnly` (or, from Cursor 3.27.14, the paged rows `composerConvHeaders:<composer id>:<page>`),
  and for `_v` below 3 the inline `conversation` and `capabilities`.
- `bubbleId:<composer id>:<bubble id>` holds one message: `type` 1 is the user's and 2 the assistant's; `capabilityType` 15 is a
  tool call. The call's record `{name, params, rawArgs, result, status, error}` is `toolFormerData` on the bubble when
  `_v` is 3 or more, and otherwise `capabilities[type 15].data.bubbleDataMap[<bubble id>]` (an object or a JSON string).
- A shell tool (`run_terminal_cmd`, `run_terminal_command`, `run_terminal_command_v2`) has its command in `params` or
  `rawArgs` and its output in the JSON `result` as `output`. `status` is `error` or `cancelled` for a call that failed or was
  declined. Neither the format document nor the provider's code names a field for an exit code, so exit_code stays None and
  is_error follows `status` only.

Changes: the result is the normalized model of model.py; the database is opened read-only through a `mode=ro` URI and
only the rows of the one composer are read (its `composerData`, `composerConvHeaders` and `bubbleId` keys, found by key
range), streamed and capped at MAX_LINE bytes a row; finding a project's composers reads only `composerData:` rows, takes
their folder with `json_extract`, and keeps no row in memory. A composer is matched by `workspaceIdentifier.uri.fsPath`
alone: conversations of Cursor before 3.12, which are tied to a folder through the workspace databases, and remote
(SSH, WSL, container) folders are not matched. The format records no sub-agent, no compaction and no text the harness
injected into a user bubble, so every user bubble is the user's text.
"""
import json
import math
import os
import re
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timezone

from . import _io
from .model import ASSISTANT_TEXT, MAIN, TOOL_CALL, USER_TEXT, Session, Tool

HARNESS = 'cursor-ide'
DB_NAME = 'state.vscdb'
TABLE = 'cursorDiskKV'
BUSY_SECONDS = 2.0                 # how long a read waits for a writer's lock
SHELL_TOOLS = frozenset(('run_terminal_cmd', 'run_terminal_command', 'run_terminal_command_v2'))
TOOL_CAPABILITY = 15
FAILED = frozenset(('error', 'cancelled'))
MAX_BUBBLES = 200000               # rows read for one composer
MAX_PAGES = 10000


def default_root(platform=None):
    """The globalStorage directory of Cursor's user data directory on this operating system."""
    platform = platform or sys.platform
    home = os.path.expanduser('~')
    if platform == 'darwin':
        base = os.path.join(home, 'Library', 'Application Support', 'Cursor')
    elif platform.startswith('win'):
        base = os.path.join(home, 'AppData', 'Roaming', 'Cursor')
    else:
        base = os.path.join(home, '.config', 'Cursor')
    return os.path.join(base, 'User', 'globalStorage')


def _split(ref):
    """(database path, composer id) of a reference; the id is None for a bare database path."""
    db, sep, cid = ref.rpartition('#')
    return (db, cid) if sep else (ref, None)


def _connect(real):
    """A read-only connection to a resolved database path. Raises RootError for a non-regular file and
    StoreError when it cannot be opened. A file that is not an SQLite database fails at the first query."""
    _io.open_plain(real).close()          # refuses a FIFO or a directory before SQLite can block on it
    try:
        con = sqlite3.connect('file:%s?mode=ro' % urllib.parse.quote(real), uri=True, timeout=BUSY_SECONDS, isolation_level=None)
        con.text_factory = lambda b: b.decode('utf-8', 'replace')
        con.execute('PRAGMA trusted_schema = OFF')
        con.execute('PRAGMA mmap_size = 0')
        return con
    except sqlite3.Error as e:
        raise _io.StoreError('cannot open %s: %s' % (real, e))


def _open_db(db, root):
    """(connection, real database path) for a database path under root."""
    real = _io.confine(db, root)
    return _connect(real), real


def _has_table(con):
    return any(r[1] == 'key' for r in con.execute('PRAGMA table_info(%s)' % TABLE)) and any(r[1] == 'value' for r in con.execute('PRAGMA table_info(%s)' % TABLE))


def detect(path):
    """Whether the file is an SQLite database with Cursor's `cursorDiskKV` table."""
    try:
        con = _connect(os.path.realpath(_split(path)[0]))
    except (OSError, _io.RootError, _io.StoreError):
        return False
    try:
        return _has_table(con)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _range(prefix):
    """(low, high) bounds that select exactly the keys starting with prefix, which ends in ':'."""
    return prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)


def _text_value():
    """The value column as text, read only when it is within the row size cap, so one huge row is skipped, not loaded."""
    return 'CASE WHEN length(CAST(value AS BLOB)) <= %d THEN CAST(value AS TEXT) END' % _io.MAX_LINE


def _usable_id(cid):
    return isinstance(cid, str) and bool(cid) and ':' not in cid and '#' not in cid


def _updated(*values):
    for v in values:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v):
            return v
    return 0


def find_sessions(cwd, root=None):
    """References of the composers whose recorded folder is `cwd`, newest first."""
    root = root or default_root()
    try:
        con, real = _open_db(os.path.join(root, DB_NAME), root)
    except (OSError, _io.RootError, _io.StoreError):
        return []
    want = {os.path.normcase(os.path.realpath(cwd)), os.path.normcase(os.path.abspath(cwd))}
    seen, found = {}, []
    lo, hi = _range('composerData:')
    sql = ('SELECT key, json_extract(v, \'$.workspaceIdentifier.uri.fsPath\'), json_extract(v, \'$.lastUpdatedAt\'), json_extract(v, \'$.createdAt\') '
           'FROM (SELECT key, %s AS v FROM %s WHERE key >= ? AND key < ?) WHERE v IS NOT NULL AND json_valid(v)' % (_text_value(), TABLE))
    try:
        if not _has_table(con):
            return []
        for key, fs_path, last, created in con.execute(sql, (lo, hi)):
            cid = key[len(lo):] if isinstance(key, str) else None
            if not _usable_id(cid) or not isinstance(fs_path, str) or not os.path.isabs(fs_path) or '\0' in fs_path:
                continue
            if fs_path not in seen:
                seen[fs_path] = os.path.normcase(fs_path) in want or os.path.normcase(os.path.realpath(fs_path)) in want
            if seen[fs_path]:
                found.append((_updated(last, created), real + '#' + cid))
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [ref for _, ref in sorted(found, reverse=True)]


def _iso(ms):
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or not math.isfinite(ms) or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    except (OverflowError, OSError, ValueError):
        return None


def _json(raw):
    """The JSON object in a row's value, or an empty dict."""
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
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return int(v)
    return None


def _obj(v):
    """A dict that is a dict, or a JSON string holding one; None otherwise."""
    if isinstance(v, str):
        v = _json(v) or None
    return v if isinstance(v, dict) else None


def _slim(bubble, bubble_id):
    """The few fields of a bubble the transcript uses, so a long conversation is not held whole."""
    tool = bubble.get('toolFormerData')
    return {'id': bubble_id, 'type': _int(bubble.get('type')), 'text': _io.s(bubble.get('text')), 'cap': _int(bubble.get('capabilityType')),
            'tool': tool if isinstance(tool, dict) else None}


def _error_text(error):
    """The message a failed call shows: `clientVisibleErrorMessage` of the error JSON when it has one (SpecStory's
    `formatToolError`), else the error as recorded."""
    text = _io.s(error)
    msg = _io.s(_io.d(_json(text)).get('clientVisibleErrorMessage')) if text else None
    return msg or text


def _tool(bubble_id, data):
    """A Tool from a tool record, or None when the record names no tool."""
    name = _io.s(data.get('name'))
    if not name:
        return None
    params, raw = _obj(data.get('params')), _obj(data.get('rawArgs'))
    args = params or raw
    if args is None:
        args = _io.s(data.get('params')) or _io.s(data.get('rawArgs'))
    is_shell = name in SHELL_TOOLS
    command = None
    if is_shell:
        command = next((c for c in (_io.s(_io.d(params).get('command')), _io.s(_io.d(raw).get('command'))) if c), None)
    result = data.get('result')
    output = _io.s(_io.d(_obj(result)).get('output')) if is_shell else _io.s(result)
    status = _io.s(data.get('status'))
    if status == 'error' and output is None:
        output = _error_text(data.get('error'))
    return Tool(bubble_id, name, is_shell, command, output, None, status in FAILED, args)


class _Reader:
    def __init__(self, con, real):
        self.con, self.real = con, real

    def row(self, key):
        r = self.con.execute('SELECT %s FROM %s WHERE key = ?' % (_text_value(), TABLE), (key,)).fetchone()
        return r[0] if r else None

    def rows(self, prefix, limit):
        lo, hi = _range(prefix)
        return self.con.execute('SELECT key, %s FROM %s WHERE key >= ? AND key < ? ORDER BY key LIMIT %d' % (_text_value(), TABLE, limit), (lo, hi))

    def headers(self, cid, composer):
        """The ordered bubble ids of a composer: the inline manifest, else the concatenated header pages."""
        inline = composer.get('fullConversationHeadersOnly')
        heads = [h for h in inline if isinstance(h, dict)] if isinstance(inline, list) else []
        if not heads:
            for _, raw in self.rows('composerConvHeaders:%s:' % cid, MAX_PAGES):
                try:
                    page = json.loads(raw) if isinstance(raw, str) else None
                except ValueError:
                    page = None
                heads += [h for h in page if isinstance(h, dict)] if isinstance(page, list) else []
        return [h['bubbleId'] for h in heads if isinstance(h.get('bubbleId'), str)]

    def bubbles(self, cid):
        prefix = 'bubbleId:%s:' % cid
        out = {}
        for key, raw in self.rows(prefix, MAX_BUBBLES):
            bid = key[len(prefix):]
            b = _json(raw)
            if bid and b:
                out[bid] = _slim(b, bid)
        return out

    def session(self, cid):
        raw = self.row('composerData:' + cid)
        composer = _json(raw)
        if not composer:
            raise _io.StoreError('no composer %s in %s' % (cid, self.real))
        fs_path = _io.s(_io.d(_io.d(composer.get('workspaceIdentifier')).get('uri')).get('fsPath'))
        sess = Session(HARNESS, cid, cwd=fs_path, started_at=_iso(composer.get('createdAt')), kind=MAIN)
        version = _int(composer.get('_v')) or 0
        found = self.bubbles(cid)
        order = self.headers(cid, composer)
        if order:
            conversation = [found[b] for b in order if b in found]
        else:                                                    # the inline conversation of the older format, completed by the bubble rows
            conversation = []
            for c in composer.get('conversation') if isinstance(composer.get('conversation'), list) else ():
                if not isinstance(c, dict) or not isinstance(c.get('bubbleId'), str):
                    continue
                base = _slim(c, c['bubbleId'])
                full = found.get(c['bubbleId'])
                if full:
                    base.update({k: v for k, v in full.items() if v})
                conversation.append(base)
        caps = self.capabilities(composer)
        for n, b in enumerate(conversation, 1):
            loc = (self.real, n)
            text = b['text']
            if b['type'] == 1:
                if text and text.strip():
                    sess.add(USER_TEXT, text=text, loc=loc)
            elif b['type'] == 2:
                tool = None
                if b['cap'] == TOOL_CAPABILITY:
                    data = b['tool'] if version >= 3 and b['tool'] else _io.d(caps.get(b['cap'])).get(b['id'])
                    tool = _tool(b['id'], data) if isinstance(data, dict) else None
                if tool:
                    sess.add(TOOL_CALL, tool=tool, loc=loc)
                elif text and text.strip():
                    sess.add(ASSISTANT_TEXT, text=text, loc=loc)
        return sess

    @staticmethod
    def capabilities(composer):
        """{capabilityType: {bubble id: tool record}} of the older format."""
        out = {}
        for cap in composer.get('capabilities') if isinstance(composer.get('capabilities'), list) else ():
            data = _io.d(_io.d(cap).get('data'))
            table = _obj(data.get('bubbleDataMap'))
            if table and _int(_io.d(cap).get('type')) is not None:
                out[_int(cap['type'])] = {k: v for k, v in table.items() if isinstance(v, dict)}
        return out


def read(path, root=None):
    """The composer a reference names."""
    root = root or default_root()
    db, cid = _split(path)
    con, real = _open_db(db, root)
    try:
        if not _usable_id(cid):
            raise _io.StoreError('name a composer as <database>#<composer id>: %s' % path)
        if not _has_table(con):
            raise _io.StoreError('%s has no %s table' % (real, TABLE))
        return _Reader(con, real).session(cid)
    except sqlite3.Error as e:
        raise _io.StoreError('cannot read %s: %s' % (real, e))
    finally:
        con.close()
