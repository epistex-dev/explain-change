"""OpenCode adapter: the SQLite 2.x and 1.x schemas, write-ahead-log visibility, sub-agent sessions, guards and hostile databases."""
import json
import os
import shutil
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'scripts'))
sys.path.insert(0, HERE)

from lib import adapters  # noqa: E402
from lib.adapters import _io, opencode  # noqa: E402
from lib.adapters.model import (ASSISTANT_TEXT, COMPACTION, INJECTED, SUBAGENT, TOOL_CALL, USER_TEXT)  # noqa: E402
from test_adapters import CWD, TmpCase, calls, kinds  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'opencode')
DB = 'opencode.db'
MAGIC = b'SQLite format 3\x00'


def read_jsonl(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


def insert(con, table, row):
    row = dict(row)
    if isinstance(row.get('data'), (dict, list)):
        row['data'] = json.dumps(row['data'])
    cols = list(row)
    con.execute('INSERT INTO %s (%s) VALUES (%s)' % (table, ','.join(cols), ','.join('?' * len(cols))), [row[c] for c in cols])


def build_v2(path, fixtures=()):
    con = sqlite3.connect(path)
    with open(os.path.join(FIX, 'schema.sql'), encoding='utf-8') as fh:
        con.executescript(fh.read())
    for name in fixtures:
        for rec in read_jsonl(name):
            insert(con, rec['table'], rec['row'])
    con.commit()
    return con


V1_SCHEMA = '''
CREATE TABLE session (id text PRIMARY KEY, project_id text NOT NULL, parent_id text, directory text NOT NULL, title text, time_created integer NOT NULL, time_updated integer NOT NULL);
CREATE TABLE message (id text PRIMARY KEY, session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);
CREATE TABLE part (id text PRIMARY KEY, message_id text NOT NULL, session_id text NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL);
'''


def v2_session(con, sid, cwd=CWD, parent=None, created=1790000000000, updated=None):
    insert(con, 'session_v2', dict(id=sid, project_id='p', parent_id=parent, slug='s', directory=cwd, version='2.0.14',
                                   time_created=created, time_updated=updated or created))


def v2_msg(con, sid, seq, typ, data):
    insert(con, 'session_message', dict(id='msg_%s_%d' % (sid, seq), session_id=sid, type=typ, seq=seq, time_created=1790000000000 + seq,
                                        time_updated=1790000000000 + seq, data=data))


def v2_tool(call_id, name, inp, status='completed', content=None, **state):
    return {'type': 'tool', 'id': call_id, 'name': name, 'state': dict({'status': status, 'input': inp, 'content': content or []}, **state)}


class Store(TmpCase):
    """A temporary OpenCode data directory holding opencode.db."""
    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.root, DB)

    def ref(self, sid):
        return os.path.realpath(self.db) + '#' + sid

    def read(self, sid):
        return opencode.read(self.ref(sid), self.root)


# ---------------------------------------------------------------- the real SpecStory captures

class V2Fixtures(Store):
    def setUp(self):
        super().setUp()
        con = build_v2(self.db, ('tui-session.jsonl', 'tool-exercise.jsonl', 'model-error.jsonl'))
        con.close()
        found = opencode.find_sessions('/Users/dev/oc-tools', self.root)
        self.sessions = {r.rpartition('#')[2][:13]: opencode.read(r, self.root) for r in found}
        self.tui = self.sessions['ses_f34a1dc63']
        self.tools = self.sessions['ses_f34a354db']

    def test_find_sessions_matches_the_recorded_directory_and_lists_only_top_level_sessions(self):
        self.assertEqual(sorted(self.sessions), ['ses_f34a1dc63', 'ses_f34a354db'])
        self.assertEqual(len(opencode.find_sessions('/Users/dev/oc-1', self.root)), 1)
        self.assertEqual(opencode.find_sessions('/Users/dev/none', self.root), [])
        self.assertEqual(len(opencode.find_sessions('/Users/dev/oc-tools/', self.root)), 2)     # a trailing slash or dotdot is normalised
        self.assertEqual(len(opencode.find_sessions('/Users/dev/x/../oc-tools', self.root)), 2)

    def test_user_text_versus_injected(self):
        texts = [e.text for e in kinds(self.tui, USER_TEXT)]
        self.assertEqual(texts[0], 'The magic passphrase is PURPLE-ELEPHANT-42. Just acknowledge it briefly.')
        self.assertIn('In one sentence, what did the review conclude?', texts)
        reminders = kinds(self.tui, INJECTED)
        self.assertEqual(len(reminders), 2)
        self.assertTrue(all(e.text.startswith('<system-reminder>') for e in reminders))
        self.assertFalse([e for e in self.tui.events if e.text and 'The following shell command was executed by the user' in e.text])   # the shell echo repeats the shell record

    def test_a_user_shell_command_is_a_tool_call_by_the_user(self):
        t = [x for x in calls(self.tui) if x.by_user][0]
        self.assertEqual((t.command, t.exit_code, t.is_error, t.is_shell), ('echo hello from user shell && ls *.py', 0, False, True))
        self.assertEqual(t.output, 'hello from user shell\nfarewell.py\nhello.py\n')
        self.assertEqual(len([x for x in calls(self.tui) if x.by_user]), 1)

    def test_compaction_is_never_user_text(self):
        comp = kinds(self.tui, COMPACTION)
        self.assertEqual(len(comp), 1)
        self.assertTrue(comp[0].text.startswith('## Objective'))
        self.assertNotIn(comp[0].text, [e.text for e in kinds(self.tui, USER_TEXT)])

    def test_shell_tool_exit_and_is_error(self):
        t = {x.command: x for x in calls(self.tools) if x.is_shell}
        ok, bad = t['ls -la'], t['cat does-not-exist.txt']
        self.assertEqual((ok.exit_code, ok.is_error), (0, False))
        self.assertEqual((bad.exit_code, bad.is_error), (1, True))              # the tool's status is completed; the exit decides
        self.assertEqual(bad.output, 'cat: does-not-exist.txt: No such file or directory\n')
        self.assertNotIn('Command exited with code', ok.output)

    def test_failed_tools_without_an_exit_code(self):
        by = {}
        for x in calls(self.tools):
            by.setdefault(x.name, []).append(x)
        self.assertEqual([(x.exit_code, x.is_error) for x in by['websearch']], [(None, True), (None, True)])    # status error
        self.assertEqual(by['websearch'][0].output, 'Web search cancelled')
        self.assertEqual([x.is_error for x in by['execute']], [True, False])                                    # metadata.error: true on a completed call
        self.assertEqual([x.is_error for x in by['read']], [False, False, False, True, False])
        self.assertEqual(by['read'][3].output, 'File not found: missing.txt')
        self.assertTrue(all(not x.is_shell and x.command is None for x in by['read']))
        self.assertEqual(by['write'][0].args['path'].endswith('farewell.py'), True)

    def test_a_subagent_session_is_a_child_linked_to_its_tool_call(self):
        self.assertEqual(len(self.tools.children), 1)
        c = self.tools.children[0]
        sub = [x for x in calls(self.tools) if x.name == 'subagent'][0]
        self.assertEqual((c.kind, c.parent_id, c.parent_call_id, c.id), (SUBAGENT, self.tools.id, sub.call_id, 'ses_f34a2e95bffethLCcvMT6BjIMA'))
        self.assertEqual([e.kind for e in c.events], [INJECTED, TOOL_CALL, ASSISTANT_TEXT])      # the agent's prompt is not the user's
        self.assertEqual(kinds(c, USER_TEXT), [])
        self.assertEqual(self.tui.children, [])

    def test_a_failed_model_step_adds_no_assistant_text(self):
        s = opencode.read(opencode.find_sessions('/Users/dev/oc-1', self.root)[0], self.root)
        self.assertEqual([(e.kind, e.text) for e in s.events],
                         [(USER_TEXT, 'Say hi!'), (USER_TEXT, 'Say hi!'), (ASSISTANT_TEXT, 'Hi! How can I help you today?')])

    def test_locations_name_the_database_and_the_message_seq(self):
        path, seq = kinds(self.tui, USER_TEXT)[0].loc
        self.assertEqual((path, seq), (os.path.realpath(self.db), 4))

    def test_a_reference_to_a_missing_session_or_without_a_session_is_an_error(self):
        with self.assertRaises(_io.StoreError):
            opencode.read(self.ref('ses_missing'), self.root)
        with self.assertRaisesRegex(_io.StoreError, 'name a session'):
            opencode.read(self.db, self.root)

    def test_detect_and_registry(self):
        self.assertTrue(opencode.detect(self.db))
        self.assertTrue(opencode.detect(self.ref('ses_x')))
        self.assertEqual(adapters.detect_format(self.db), 'opencode')
        self.assertIs(adapters.get('opencode'), opencode)


class AgentSessionsShapes(Store):
    """Message and session rows shaped like the redacted OpenCode 2.1 fixtures of the agent-sessions project."""
    def test_every_row_shape_reads(self):
        base = os.path.join(FIX, 'agent-sessions', 'sqlite_v2')
        con = build_v2(self.db)
        with open(os.path.join(base, 'session_v2', 'ses_fixture_v2.json'), encoding='utf-8') as fh:
            row = {k: v for k, v in json.load(fh).items() if k != 'time_busy'}
        row.update(parent_id=None, directory=CWD, time_created=1790000000000)
        insert(con, 'session_v2', row)
        names = sorted(os.listdir(os.path.join(base, 'session_message')))
        for seq, name in enumerate(names, 1):
            with open(os.path.join(base, 'session_message', name), encoding='utf-8') as fh:
                rec = json.load(fh)
            insert(con, 'session_message', dict(id='m%d' % seq, session_id='ses_fixture_v2', type=rec['type'], seq=seq,
                                                time_created=seq, time_updated=seq, data=rec['data']))
        con.commit()
        con.close()
        s = self.read('ses_fixture_v2')
        self.assertEqual(self.ref('ses_fixture_v2'), opencode.find_sessions(CWD, self.root)[0])
        self.assertEqual([e.kind for e in s.events].count(USER_TEXT), 1)          # user.json; synthetic, system and job-synthetic are injected
        self.assertEqual(len(kinds(s, INJECTED)), 3)
        self.assertEqual(len(kinds(s, COMPACTION)), 1)
        self.assertEqual(sorted((t.name, t.command, t.exit_code, t.by_user, t.is_error) for t in calls(s)),
                         [('shell', 'redacted', 0, True, False), ('todowrite', None, None, False, False), ('todowrite', None, None, False, True)])
        self.assertEqual(len(kinds(s, ASSISTANT_TEXT)), 1)


class ShellTools(Store):
    def tool(self, name, content, **state):
        if os.path.exists(self.db):
            os.unlink(self.db)
        con = build_v2(self.db)
        v2_session(con, 's1')
        v2_msg(con, 's1', 1, 'assistant', {'content': [v2_tool('c1', name, {'command': 'x'}, content=content, **state)]})
        con.commit()
        con.close()
        return calls(self.read('s1'))[0]

    def test_the_exit_comes_from_metadata_or_the_closing_item(self):
        t = self.tool('shell', [{'type': 'text', 'text': 'out'}], metadata={'exit': 3})
        self.assertEqual((t.exit_code, t.is_error, t.output), (3, True, 'out'))
        t = self.tool('shell', [{'type': 'text', 'text': 'out'}, {'type': 'text', 'text': 'Command exited with code 4.'}])
        self.assertEqual((t.exit_code, t.is_error, t.output), (4, True, 'out'))
        t = self.tool('bash', [{'type': 'text', 'text': 'out'}], metadata={'exit': 0})
        self.assertEqual((t.is_shell, t.exit_code, t.is_error, t.command), (True, 0, False, 'x'))

    def test_an_exit_sentence_in_the_output_body_is_not_the_exit_code(self):
        t = self.tool('shell', [{'type': 'text', 'text': 'Command exited with code 9.'}, {'type': 'text', 'text': 'real output'}])
        self.assertEqual((t.exit_code, t.is_error, t.output), (None, False, 'Command exited with code 9.\nreal output'))
        t = self.tool('read', [{'type': 'text', 'text': 'x'}, {'type': 'text', 'text': 'Command exited with code 9.'}])
        self.assertEqual((t.exit_code, t.is_error), (None, False))

    def test_status_error_and_a_thrown_error_are_failures(self):
        t = self.tool('read', [], status='error', error={'type': 'x', 'message': 'File not found'})
        self.assertEqual((t.is_error, t.output, t.exit_code), (True, 'File not found', None))
        t = self.tool('execute', [{'type': 'text', 'text': 'boom'}], metadata={'error': True})
        self.assertEqual((t.is_error, t.output), (True, 'boom'))

    def test_streaming_and_running_calls_have_no_output(self):
        for status in ('streaming', 'running'):
            t = self.tool('shell', [{'type': 'text', 'text': 'partial'}], status=status)
            self.assertEqual((t.output, t.exit_code, t.is_error), (None, None, False), status)


# ---------------------------------------------------------------- schema detection (1.x vs 2.x) and the log

class Schemas(Store):
    def v1(self):
        con = sqlite3.connect(self.db)
        con.executescript(V1_SCHEMA)
        return con

    def add_v1(self, con, sid='ses_a', parent=None, cwd=CWD):
        insert(con, 'session', dict(id=sid, project_id='p', parent_id=parent, directory=cwd, title='t', time_created=1790000000000, time_updated=1790000000500))

    def msg(self, con, mid, sid, role, parts, created=1790000001000, **extra):
        insert(con, 'message', dict(id=mid, session_id=sid, time_created=created, time_updated=created, data=dict({'role': role, 'time': {'created': created}}, **extra)))
        for i, p in enumerate(parts):
            insert(con, 'part', dict(id='prt_%s_%d' % (mid, i), message_id=mid, session_id=sid, time_created=created + i, time_updated=created + i, data=p))

    def test_the_1x_tables_are_read_when_there_is_no_session_v2(self):
        con = self.v1()
        self.add_v1(con)
        self.add_v1(con, 'ses_child', 'ses_a')
        self.msg(con, 'm1', 'ses_a', 'user', [{'type': 'text', 'text': 'fix the bug'}, {'type': 'text', 'text': 'hook says hi', 'synthetic': True},
                                              {'type': 'text', 'text': 'hidden', 'ignored': True}, {'type': 'file', 'filename': 'x.png'}])
        self.msg(con, 'm2', 'ses_a', 'assistant', [
            {'type': 'text', 'text': 'running tests'}, {'type': 'reasoning', 'text': 'thinking'},
            {'type': 'tool', 'callID': 'c1', 'tool': 'bash', 'state': {'status': 'completed', 'input': {'command': 'pytest -q'}, 'output': '1 failed', 'metadata': {'exit': 1}}},
            {'type': 'tool', 'callID': 'c2', 'tool': 'read', 'state': {'status': 'error', 'input': {'filePath': '/x'}, 'error': 'no such file'}},
            {'type': 'tool', 'callID': 'c3', 'tool': 'task', 'state': {'status': 'completed', 'input': {'prompt': 'review'}, 'output': 'done', 'metadata': {'sessionId': 'ses_child'}}},
            {'type': 'tool', 'callID': 'c4', 'tool': 'bash', 'state': {'status': 'running', 'input': {'command': 'sleep 9'}}}], created=1790000002000)
        self.msg(con, 'm3', 'ses_a', 'assistant', [{'type': 'text', 'text': 'Summary of the work so far'}], created=1790000003000, summary=True)
        self.msg(con, 'k1', 'ses_child', 'user', [{'type': 'text', 'text': 'review the diff'}])
        con.commit()
        con.close()
        self.assertTrue(opencode.detect(self.db))
        self.assertEqual(opencode.find_sessions(CWD, self.root), [self.ref('ses_a')])
        s = self.read('ses_a')
        self.assertEqual([(e.kind, e.text) for e in s.events if e.tool is None],
                         [(USER_TEXT, 'fix the bug'), (INJECTED, 'hook says hi'), (ASSISTANT_TEXT, 'running tests'), (COMPACTION, 'Summary of the work so far')])
        by = {t.call_id: t for t in calls(s)}
        self.assertEqual((by['c1'].command, by['c1'].exit_code, by['c1'].is_error, by['c1'].output), ('pytest -q', 1, True, '1 failed'))
        self.assertEqual((by['c2'].is_error, by['c2'].output, by['c2'].is_shell), (True, 'no such file', False))
        self.assertEqual((by['c4'].output, by['c4'].exit_code, by['c4'].is_error), (None, None, False))
        self.assertEqual([(c.id, c.kind, c.parent_id, c.parent_call_id) for c in s.children], [('ses_child', SUBAGENT, 'ses_a', 'c3')])
        self.assertEqual([(e.kind, e.text) for e in s.children[0].events], [(INJECTED, 'review the diff')])

    def test_the_2x_tables_win_for_a_session_they_hold_and_both_are_listed(self):
        con = build_v2(self.db)
        con.executescript(V1_SCHEMA)
        v2_session(con, 'ses_new')
        v2_msg(con, 'ses_new', 1, 'user', {'text': 'from v2'})
        self.add_v1(con, 'ses_old')
        self.msg(con, 'o1', 'ses_old', 'user', [{'type': 'text', 'text': 'from v1'}])
        con.commit()
        con.close()
        self.assertEqual(sorted(opencode.find_sessions(CWD, self.root)), sorted([self.ref('ses_new'), self.ref('ses_old')]))
        self.assertEqual([e.text for e in self.read('ses_new').events], ['from v2'])
        self.assertEqual([e.text for e in self.read('ses_old').events], ['from v1'])

    def test_a_1x_session_table_without_parent_id_lists_its_sessions(self):
        con = sqlite3.connect(self.db)
        con.executescript(V1_SCHEMA.replace('parent_id text, ', ''))
        insert(con, 'session', dict(id='ses_a', project_id='p', directory=CWD, title='t', time_created=1, time_updated=2))
        con.commit()
        con.close()
        self.assertEqual(opencode.find_sessions(CWD, self.root), [self.ref('ses_a')])
        self.assertEqual(self.read('ses_a').events, [])

    def test_a_database_with_other_tables_is_not_opencodes(self):
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE session_v2 (id text)')          # half of the 2.x pair
        con.execute('CREATE TABLE message (id text)')             # two thirds of the 1.x triple
        con.commit()
        con.close()
        self.assertFalse(opencode.detect(self.db))
        self.assertEqual(opencode.find_sessions(CWD, self.root), [])
        with self.assertRaises(_io.StoreError):
            self.read('ses_a')


class WriteAheadLog(Store):
    def test_committed_rows_still_in_the_wal_are_visible_to_the_read_only_connection(self):
        con = build_v2(self.db)
        self.assertEqual(con.execute('PRAGMA journal_mode = WAL').fetchone()[0], 'wal')
        con.execute('PRAGMA wal_autocheckpoint = 0')
        v2_session(con, 'ses_w')
        v2_msg(con, 'ses_w', 1, 'user', {'text': 'only in the log'})
        con.commit()                                     # the writer stays open: no checkpoint has run
        try:
            self.assertGreater(os.path.getsize(self.db + '-wal'), 0)
            with open(self.db, 'rb') as fh:              # the main file alone does not hold the session yet
                self.assertNotIn(b'only in the log', fh.read())
            self.assertEqual(opencode.find_sessions(CWD, self.root), [self.ref('ses_w')])
            self.assertEqual([e.text for e in self.read('ses_w').events], ['only in the log'])
        finally:
            con.close()

    def test_reading_writes_nothing(self):
        con = build_v2(self.db)
        v2_session(con, 's1')
        v2_msg(con, 's1', 1, 'user', {'text': 'hello'})
        con.commit()
        con.close()
        before = (os.stat(self.db).st_mtime_ns, os.stat(self.db).st_size)
        self.read('s1')
        opencode.find_sessions(CWD, self.root)
        self.assertEqual((os.stat(self.db).st_mtime_ns, os.stat(self.db).st_size), before)
        self.assertEqual(sorted(os.listdir(self.root)), [DB])

    def test_the_connection_cannot_write(self):
        build_v2(self.db).close()
        con = opencode._connect(os.path.realpath(self.db))
        try:
            with self.assertRaises(sqlite3.Error):
                con.execute("INSERT INTO session_message (id, session_id, type, seq, time_created, time_updated, data) VALUES ('a','b','user',1,1,1,'{}')")
        finally:
            con.close()


# ---------------------------------------------------------------- hostile databases

class Hostile(Store):
    def test_an_empty_file_is_no_database(self):
        open(self.db, 'wb').close()
        self.assertEqual(opencode.find_sessions(CWD, self.root), [])
        self.assertFalse(opencode.detect(self.db))
        with self.assertRaises(_io.StoreError):
            self.read('s')

    def test_a_missing_database_has_no_sessions(self):
        self.assertEqual(opencode.find_sessions(CWD, self.root), [])
        self.assertEqual(opencode.find_sessions(CWD, os.path.join(self.tmp, 'absent')), [])
        with self.assertRaises(_io.RootError):
            self.read('s')

    def test_garbage_bytes_and_a_valid_header_with_a_corrupt_body_are_store_errors(self):
        for body in (b'not a database at all' * 100, MAGIC + b'\xff' * 4000, MAGIC):
            with open(self.db, 'wb') as fh:
                fh.write(body)
            self.assertEqual(opencode.find_sessions(CWD, self.root), [])
            self.assertFalse(opencode.detect(self.db))
            with self.assertRaises(_io.StoreError):
                self.read('s')

    def test_a_database_cut_short_is_a_store_error(self):
        con = build_v2(self.db)
        v2_session(con, 's1')
        for i in range(1, 200):
            v2_msg(con, 's1', i, 'user', {'text': 'row %d ' % i + 'x' * 500})
        con.commit()
        con.close()
        with open(self.db, 'r+b') as fh:
            fh.truncate(os.path.getsize(self.db) // 2)
        try:
            self.read('s1')
        except _io.StoreError:
            pass                                          # either the tables are gone or a page is missing: never a raw sqlite error
        self.assertIsInstance(opencode.find_sessions(CWD, self.root), list)

    def test_a_locked_database_is_a_store_error_and_find_sessions_is_empty(self):
        con = build_v2(self.db)
        v2_session(con, 's1')
        con.commit()
        con.close()
        writer = sqlite3.connect(self.db, isolation_level=None)
        writer.execute('BEGIN EXCLUSIVE')               # rollback-journal mode: readers wait for the lock
        old = opencode.BUSY_SECONDS
        opencode.BUSY_SECONDS = 0.05
        try:
            with self.assertRaises(_io.StoreError):
                self.read('s1')
            self.assertEqual(opencode.find_sessions(CWD, self.root), [])
        finally:
            opencode.BUSY_SECONDS = old
            writer.execute('ROLLBACK')
            writer.close()
        self.assertEqual(self.read('s1').id, 's1')      # the lock released: reading works again

    def test_invalid_utf8_in_a_text_column_is_replaced(self):
        con = build_v2(self.db)
        v2_session(con, 's1', cwd=CWD)
        v2_msg(con, 's1', 1, 'user', {'text': 'ok'})
        con.execute("INSERT INTO session_message VALUES ('bad', 's1', 'user', 2, 2, 2, CAST(X'7B2274657874223A2262616420FF22207D' AS TEXT))")
        con.commit()
        con.close()
        self.assertEqual([e.text for e in self.read('s1').events], ['ok', 'bad �'])

    def test_a_5mb_row_is_read_whole(self):
        con = build_v2(self.db)
        v2_session(con, 's1')
        big = 'x' * (5 * 1024 * 1024)
        v2_msg(con, 's1', 1, 'user', {'text': big})
        v2_msg(con, 's1', 2, 'user', {'text': 'after'})
        con.commit()
        con.close()
        self.assertEqual([len(e.text) for e in self.read('s1').events], [len(big), 5])

    def test_a_row_over_the_cap_is_skipped_and_reading_continues(self):
        con = build_v2(self.db)
        v2_session(con, 's1')
        v2_msg(con, 's1', 1, 'user', {'text': 'y' * 5000})
        v2_msg(con, 's1', 2, 'user', {'text': 'after'})
        con.commit()
        con.close()
        old = _io.MAX_LINE
        _io.MAX_LINE = 1000
        try:
            self.assertEqual([e.text for e in self.read('s1').events], ['after'])
        finally:
            _io.MAX_LINE = old

    def test_rows_that_are_not_json_objects_or_have_odd_types_are_skipped(self):
        con = build_v2(self.db)
        v2_session(con, 's1')
        for seq, data in enumerate(['not json', '[1,2]', '"str"', '42', 'null', '{}', json.dumps({'text': 5}), json.dumps({'text': 'kept'}),
                                    json.dumps({'content': 'not a list'}), json.dumps({'content': [7, None, {'type': 'tool'}, {'type': 'text', 'text': 9}]})], 1):
            v2_msg(con, 's1', seq, 'user' if seq < 9 else 'assistant', data)
        con.execute("INSERT INTO session_message VALUES ('typ', 's1', 7, 'x', 1, 1, '{}')")        # type and seq of the wrong SQLite types
        con.commit()
        con.close()
        s = self.read('s1')
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['kept'])
        t = calls(s)[0]
        self.assertEqual((t.call_id, t.name, t.output, t.exit_code, t.is_error), (None, None, None, None, False))

    def test_missing_and_extreme_values_become_none(self):
        con = build_v2(self.db)
        con.execute("INSERT INTO session_v2 (id, project_id, slug, directory, version, time_created, time_updated) VALUES ('s1', 'p', 's', ?, '2', 1e300, 0)", (CWD,))
        v2_msg(con, 's1', 1, 'user', {'text': 'hi', 'time': {'created': 1e300}})
        v2_msg(con, 's1', 2, 'user', {'text': 'hi', 'time': {'created': -5}})
        v2_msg(con, 's1', 3, 'assistant', {'content': [v2_tool('c', 'shell', {'command': 'x'}, metadata={'exit': 'abc'}), v2_tool('d', 'shell', {'command': 'y'}, metadata={'exit': '7'}),
                                                       v2_tool('e', 'shell', {'command': 'z'}, metadata={'exit': True})]})
        con.commit()
        con.close()
        s = self.read('s1')
        self.assertEqual((s.started_at, s.cwd), (None, CWD))
        self.assertEqual([e.ts[:4] for e in s.events if e.text], ['2026', '2026'])        # an unusable time in the data falls back to the row's own time
        self.assertEqual([(t.exit_code, t.is_error) for t in calls(s)], [(None, False), (7, True), (None, False)])

    def test_parent_cycles_do_not_loop(self):
        con = build_v2(self.db)
        v2_session(con, 'a', parent='b')
        v2_session(con, 'b', parent='a')
        v2_session(con, 'c', parent='c')
        v2_session(con, 'top')
        v2_session(con, 'kid', parent='top')
        v2_session(con, 'grandkid', parent='kid')
        con.commit()
        con.close()
        self.assertEqual(opencode.find_sessions(CWD, self.root), [self.ref('top')])
        s = self.read('top')
        self.assertEqual([(c.id, [g.id for g in c.children]) for c in s.children], [('kid', ['grandkid'])])
        self.assertEqual(self.read('a').children[0].children, [])          # b's child a was seen: the cycle ends

    def test_sub_agent_nesting_is_capped(self):
        con = build_v2(self.db)
        v2_session(con, 'n0')
        for i in range(1, opencode.MAX_DEPTH + 4):
            v2_session(con, 'n%d' % i, parent='n%d' % (i - 1))
        con.commit()
        con.close()
        depth, s = 0, self.read('n0')
        while s.children:
            s, depth = s.children[0], depth + 1
        self.assertEqual(depth, opencode.MAX_DEPTH)

    def test_a_hash_in_a_session_id_is_never_listed(self):
        con = build_v2(self.db)
        v2_session(con, 'ses#evil')
        v2_session(con, 'ok')
        con.commit()
        con.close()
        self.assertEqual(opencode.find_sessions(CWD, self.root), [self.ref('ok')])

    def test_a_path_with_a_hash_in_the_directory_still_resolves(self):
        root = os.path.join(self.tmp, 'a#b')
        os.makedirs(root)
        con = build_v2(os.path.join(root, DB))
        v2_session(con, 's1')
        v2_msg(con, 's1', 1, 'user', {'text': 'hi'})
        con.commit()
        con.close()
        refs = opencode.find_sessions(CWD, root)
        self.assertEqual(len(refs), 1)
        self.assertEqual([e.text for e in opencode.read(refs[0], root).events], ['hi'])


# ---------------------------------------------------------------- guards

class Tree(TmpCase):
    """The JSON tree of OpenCode before 1.2: storage/session/<project>/<id>.json, storage/message/<session>/, storage/part/."""
    LEGACY = os.path.join(FIX, 'agent-sessions', 'storage_legacy')

    def put(self, rel, obj):
        p = os.path.join(self.root, 'storage', rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(obj if isinstance(obj, str) else json.dumps(obj))
        return p

    def session(self, sid, cwd=CWD, parent=None, created=1790000000000, updated=None):
        return self.put('session/proj/ses_%s.json' % sid, {'id': sid, 'directory': cwd, 'parentID': parent, 'time': {'created': created, 'updated': updated or created}})

    def message(self, sid, mid, role, created, parts=(), **extra):
        self.put('message/%s/%s.json' % (sid, mid), dict({'id': mid, 'sessionID': sid, 'role': role, 'time': {'created': created}}, **extra))
        for n, part in enumerate(parts):
            self.put('part/%s/prt_%d.json' % (mid, n), dict({'id': 'prt_%s_%d' % (mid, n), 'messageID': mid}, **part))

    def test_the_vendored_flat_layout_reads(self):
        shutil.copytree(self.LEGACY, os.path.join(self.root, 'storage'))
        refs = opencode.find_sessions('/tmp/drift', self.root)
        self.assertEqual([os.path.basename(r) for r in refs], ['ses_s_stage0_drift.json'])
        self.assertTrue(opencode.detect(refs[0]))
        sess = opencode.read(refs[0], self.root)
        self.assertEqual((sess.harness, sess.id, sess.cwd, sess.started_at), ('opencode', 's_stage0_drift', '/tmp/drift', '2024-10-27T03:36:40.000Z'))
        self.assertEqual([e.kind for e in sess.events], [TOOL_CALL, ASSISTANT_TEXT])
        tool = sess.events[0].tool
        self.assertEqual((tool.name, tool.is_shell, tool.command, tool.output, tool.is_error), ('bash', True, 'cat README.md', '# Title\n\nBody\n', False))
        self.assertEqual(sess.events[1].text, 'Read README and extracted the title.')
        self.assertEqual(opencode.find_sessions('/tmp/elsewhere', self.root), [])

    def test_messages_and_parts_come_in_time_order_with_the_per_message_layout(self):
        self.session('a')
        self.message('a', 'msg_2', 'assistant', 1790000002000, [
            {'type': 'text', 'text': 'second', 'time': {'start': 1790000002200}},
            {'type': 'text', 'text': 'first', 'time': {'start': 1790000002100}},
            {'type': 'text', 'text': '   '},
            {'type': 'reasoning', 'text': 'hidden thoughts'}])
        self.message('a', 'msg_1', 'user', 1790000001000, [{'type': 'text', 'text': 'do it'}, {'type': 'text', 'text': 'noise', 'ignored': True},
                                                         {'type': 'text', 'text': 'injected', 'synthetic': True}])
        sess = opencode.read(opencode.find_sessions(CWD, self.root)[0], self.root)
        self.assertEqual([(e.kind, e.text) for e in sess.events], [(USER_TEXT, 'do it'), (INJECTED, 'injected'), (ASSISTANT_TEXT, 'first'), (ASSISTANT_TEXT, 'second')])

    def test_tools_and_compaction_read_like_the_1x_tables(self):
        self.session('a')
        self.message('a', 'msg_1', 'assistant', 1790000001000, [{'type': 'tool', 'tool': 'bash', 'callID': 'c1', 'state': {
            'status': 'completed', 'input': {'command': 'false'}, 'output': 'x', 'metadata': {'exit': 1}}}])
        self.message('a', 'msg_2', 'assistant', 1790000002000, [{'type': 'text', 'text': 'the summary'}], summary=True)
        sess = opencode.read(opencode.find_sessions(CWD, self.root)[0], self.root)
        self.assertEqual([e.kind for e in sess.events], [TOOL_CALL, COMPACTION])
        self.assertEqual((sess.events[0].tool.exit_code, sess.events[0].tool.is_error), (1, True))

    def test_only_top_level_sessions_in_the_directory_are_listed_and_children_are_attached(self):
        self.session('top', updated=1790000009000)
        self.session('old', created=1780000000000)
        self.session('other', cwd='/elsewhere')
        self.session('kid', parent='top')
        self.message('top', 'msg_1', 'assistant', 1790000001000, [{'type': 'tool', 'tool': 'task', 'callID': 'call-kid', 'state': {
            'status': 'completed', 'input': {}, 'output': 'ok', 'metadata': {'sessionId': 'kid'}}}])
        self.message('kid', 'msg_k', 'user', 1790000001500, [{'type': 'text', 'text': 'sub prompt'}])
        refs = opencode.find_sessions(CWD, self.root)
        self.assertEqual([os.path.basename(r) for r in refs], ['ses_top.json', 'ses_old.json'])
        sess = opencode.read(refs[0], self.root)
        self.assertEqual([(c.id, c.kind, c.parent_id, c.parent_call_id) for c in sess.children], [('kid', SUBAGENT, 'top', 'call-kid')])
        self.assertEqual([e.kind for e in sess.children[0].events], [INJECTED])

    def test_a_database_session_whose_id_ends_in_json_is_still_a_database_reference(self):
        con = build_v2(os.path.join(self.root, DB))
        v2_session(con, 'x.json')
        v2_msg(con, 'x.json', 1, 'user', {'text': 'hi'})
        con.commit()
        con.close()
        ref = opencode.find_sessions(CWD, self.root)[0]
        self.assertTrue(ref.endswith('#x.json'))
        self.assertEqual(opencode.read(ref, self.root).id, 'x.json')

    def test_parent_cycles_and_deep_nesting_terminate(self):
        self.session('a', parent='b')
        self.session('b', parent='a')
        self.message('a', 'm', 'user', 1790000001000, [{'type': 'text', 'text': 'hi'}])
        sess = opencode.read(os.path.join(self.root, 'storage', 'session', 'proj', 'ses_a.json'), self.root)
        self.assertEqual([c.id for c in sess.children], ['b'])
        self.assertEqual(sess.children[0].children, [])
        for n in range(opencode.MAX_DEPTH + 4):
            self.session('d%d' % n, parent='d%d' % (n - 1) if n else None)
        node, depth = opencode.read(os.path.join(self.root, 'storage', 'session', 'proj', 'ses_d0.json'), self.root), 0
        while node.children:
            node, depth = node.children[0], depth + 1
        self.assertEqual(depth, opencode.MAX_DEPTH)

    def test_broken_files_are_skipped(self):
        self.session('a')
        self.put('session/proj/ses_bad.json', '{not json')
        self.put('session/proj/ses_list.json', '[1, 2]')
        self.put('session/proj/ses_noid.json', {'directory': CWD})
        self.put('message/a/msg_bad.json', 'garbage')
        self.put('message/a/msg_utf.json', b'\xff'.decode('latin-1'))
        self.message('a', 'msg_1', 'user', 1790000001000, [{'type': 'text', 'text': 'ok'}])
        with open(os.path.join(self.root, 'storage', 'part', 'msg_1', 'prt_x.json'), 'wb') as fh:
            fh.write(b'\xff\xfe not json')
        sess = opencode.read(opencode.find_sessions(CWD, self.root)[0], self.root)
        self.assertEqual([e.text for e in sess.events], ['ok'])
        with self.assertRaises(_io.StoreError):
            opencode.read(os.path.join(self.root, 'storage', 'session', 'proj', 'ses_bad.json'), self.root)

    def test_a_file_over_the_size_cap_is_skipped(self):
        self.session('a')
        self.message('a', 'msg_1', 'user', 1790000001000, [{'type': 'text', 'text': 'kept'}])
        self.put('part/msg_1/prt_big.json', '{"type":"text","text":"padded"}' + ' ' * (_io.MAX_LINE + 1))
        self.put('part/msg_1/prt_ok.json', '{"type":"text","text":"also kept"}' + ' ' * 1000)
        sess = opencode.read(opencode.find_sessions(CWD, self.root)[0], self.root)
        self.assertEqual(sorted(e.text for e in sess.events), ['also kept', 'kept'])

    def forged_message(self):
        outside = os.path.join(self.tmp, 'outside')
        os.makedirs(outside)
        with open(os.path.join(outside, 'msg_f.json'), 'w') as fh:
            json.dump({'id': 'msg_f', 'role': 'user', 'time': {'created': 1}}, fh)
        self.put('part/msg_f/prt.json', {'type': 'text', 'text': 'forged'})
        return outside

    def test_a_symlinked_tree_directory_that_escapes_the_root_is_not_read(self):
        self.session('a')
        os.makedirs(os.path.join(self.root, 'storage', 'message'))
        os.symlink(self.forged_message(), os.path.join(self.root, 'storage', 'message', 'a'))
        sess = opencode.read(opencode.find_sessions(CWD, self.root)[0], self.root)
        self.assertEqual(sess.events, [])

    def test_a_session_id_that_climbs_out_of_the_tree_reads_nothing_from_outside(self):
        self.forged_message()
        os.makedirs(os.path.join(self.root, 'storage', 'message'))
        self.put('session/proj/ses_x.json', {'id': '../../../outside', 'directory': CWD, 'time': {'created': 1}})
        sess = opencode.read(opencode.find_sessions(CWD, self.root)[0], self.root)
        self.assertEqual(sess.events, [])

    def test_a_session_file_outside_the_root_or_behind_a_symlink_is_refused(self):
        outside = os.path.join(self.tmp, 'outside', 'ses_o.json')
        os.makedirs(os.path.dirname(outside))
        with open(outside, 'w') as fh:
            json.dump({'id': 'o', 'directory': CWD}, fh)
        with self.assertRaises(_io.RootError):
            opencode.read(outside, self.root)
        os.makedirs(os.path.join(self.root, 'storage', 'session', 'proj'))
        link = os.path.join(self.root, 'storage', 'session', 'proj', 'ses_o.json')
        os.symlink(outside, link)
        with self.assertRaises(_io.RootError):
            opencode.read(link, self.root)
        self.assertEqual(opencode.find_sessions(CWD, self.root), [])

    def test_detect_names_only_session_files(self):
        self.session('a')
        real = os.path.join(self.root, 'storage', 'session', 'proj', 'ses_a.json')
        self.assertTrue(opencode.detect(real))
        self.assertFalse(opencode.detect(self.put('message/a/msg_1.json', {'id': 'msg_1'})))
        self.assertFalse(opencode.detect(os.path.join(self.root, 'missing.json')))


class Guards(Store):
    def forged(self, where):
        os.makedirs(os.path.dirname(where), exist_ok=True)
        con = build_v2(where)
        v2_session(con, 'forged')
        v2_msg(con, 'forged', 1, 'user', {'text': 'I wrote this myself'})
        con.commit()
        con.close()
        return where

    def test_a_database_outside_the_root_is_refused(self):
        outside = self.forged(os.path.join(self.tmp, 'outside', DB))
        with self.assertRaises(_io.RootError):
            opencode.read(outside + '#forged', self.root)

    def test_a_symlink_that_escapes_the_root_is_refused(self):
        outside = self.forged(os.path.join(self.tmp, 'outside', DB))
        os.symlink(outside, self.db)
        with self.assertRaises(_io.RootError):
            opencode.read(self.db + '#forged', self.root)
        self.assertEqual(opencode.find_sessions(CWD, self.root), [])

    def test_a_symlinked_data_directory_that_escapes_the_root_is_refused(self):
        outside = self.forged(os.path.join(self.tmp, 'outside', 'data', DB))
        os.symlink(os.path.dirname(outside), os.path.join(self.root, 'data'))
        with self.assertRaises(_io.RootError):
            opencode.read(os.path.join(self.root, 'data', DB) + '#forged', self.root)

    def test_dotdot_cannot_climb_out_of_the_root(self):
        self.forged(os.path.join(self.tmp, DB))
        with self.assertRaises(_io.RootError):
            opencode.read(os.path.join(self.root, '..', DB) + '#forged', self.root)

    def test_a_sibling_directory_sharing_the_roots_name_prefix_is_outside(self):
        sibling = self.forged(os.path.join(self.root + '-evil', DB))
        with self.assertRaises(_io.RootError):
            opencode.read(sibling + '#forged', self.root)

    def test_a_symlink_inside_the_root_to_a_database_inside_the_root_is_fine(self):
        real = self.forged(os.path.join(self.root, 'real', DB))
        link = os.path.join(self.root, 'link.db')
        os.symlink(real, link)
        self.assertEqual([e.text for e in opencode.read(link + '#forged', self.root).events], ['I wrote this myself'])

    def test_a_fifo_or_directory_is_not_opened(self):
        os.mkfifo(self.db)
        with self.assertRaises(_io.RootError):
            opencode.read(self.db + '#s', self.root)
        self.assertEqual(opencode.find_sessions(CWD, self.root), [])
        self.assertFalse(opencode.detect(self.db))
        os.unlink(self.db)
        os.mkdir(self.db)
        with self.assertRaises(_io.RootError):
            opencode.read(self.db + '#s', self.root)

    def test_the_default_root_is_the_data_directory_and_no_environment_variable_moves_it(self):
        saved = {k: os.environ.get(k) for k in ('XDG_DATA_HOME', 'OPENCODE_DB', 'HOME')}
        try:
            os.environ['XDG_DATA_HOME'] = self.tmp
            os.environ['OPENCODE_DB'] = os.path.join(self.tmp, 'elsewhere.db')
            self.assertEqual(opencode.default_root(), os.path.join(os.path.expanduser('~'), '.local', 'share', 'opencode'))
            outside = self.forged(os.path.join(self.tmp, DB))
            with self.assertRaises(_io.RootError):
                opencode.read(outside + '#forged')                  # no root argument: the default root applies
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == '__main__':
    unittest.main()
