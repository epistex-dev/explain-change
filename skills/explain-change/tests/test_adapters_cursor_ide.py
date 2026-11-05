"""Cursor IDE adapter: cursorDiskKV composers and bubbles (Cursor 3 and the older inline format), shell tools, project matching, bounded reads, guards and hostile databases."""
import json
import os
import resource
import sqlite3
import subprocess
import sys
import tracemalloc
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'scripts'))
sys.path.insert(0, HERE)

from lib import adapters  # noqa: E402
from lib.adapters import _io, cursor_ide  # noqa: E402
from lib.adapters.model import ASSISTANT_TEXT, INJECTED, MAIN, TOOL_CALL, USER_TEXT  # noqa: E402
from test_adapters import CWD, TmpCase, calls, kinds  # noqa: E402

DB = 'state.vscdb'
MAGIC = b'SQLite format 3\x00'
C3, C3P, C1, OTHER, NOPATH = 'c3-composer', 'c3-paged', 'c1-composer', 'other-composer', 'no-path'


def put(con, key, value):
    con.execute('INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?, ?)', (key, value if isinstance(value, (str, bytes)) else json.dumps(value)))


def composer(con, cid, cwd=CWD, v=17, created=1790000000000, updated=None, **extra):
    rec = dict({'_v': v, 'composerId': cid, 'createdAt': created, 'lastUpdatedAt': updated or created}, **extra)
    if cwd is not None:
        rec['workspaceIdentifier'] = {'id': 'ws', 'uri': {'fsPath': cwd}}
    put(con, 'composerData:' + cid, rec)


def bubble(con, cid, bid, typ, text='', **extra):
    put(con, 'bubbleId:%s:%s' % (cid, bid), dict({'bubbleId': bid, 'type': typ, 'text': text}, **extra))


def header(bid, typ=2, renderable=True):
    return {'bubbleId': bid, 'type': typ, 'grouping': {'isRenderable': renderable}}


def tool_data(name='run_terminal_command_v2', command='ls', output='out', status='completed', **extra):
    return dict({'tool': 15, 'name': name, 'params': json.dumps({'command': command}), 'rawArgs': json.dumps({'command': command}),
                 'result': json.dumps({'output': output}), 'status': status}, **extra)


def tool_bubble(con, cid, bid, data):
    bubble(con, cid, bid, 2, '', capabilityType=15, toolFormerData=data)


def new_db(path):
    con = sqlite3.connect(path, isolation_level=None)
    con.execute('CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)')       # the table definition of SpecStory's tests
    con.execute('CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)')
    con.execute('BEGIN')
    return con


def build_fixture(path):
    """A small state.vscdb written from the record formats in SpecStory's CURSORIDE-FORMAT.md."""
    con = new_db(path)
    # Cursor 3: inline headers, toolFormerData
    composer(con, C3, name='Fix the retry', fullConversationHeadersOnly=[header(b, t) for b, t in [('b1', 1), ('b2', 2), ('b3', 2), ('b4', 2), ('b5', 2), ('b6', 2), ('b7', 2), ('b8', 1), ('b9', 2)]])
    bubble(con, C3, 'b1', 1, 'Add a retry to fetch() in client.py')
    bubble(con, C3, 'b2', 2, 'I will list the sources first.', thinking={'text': 'hmm'})
    tool_bubble(con, C3, 'b3', tool_data(command='ls src', output='client.py\nutil.py'))
    tool_bubble(con, C3, 'b4', tool_data(command='pytest -q', output='1 failed, 4 passed', status='completed'))
    tool_bubble(con, C3, 'b5', tool_data(command='rm -rf build', output='', status='cancelled'))
    tool_bubble(con, C3, 'b6', tool_data(command='nosuchcmd', status='error', error='{"clientVisibleErrorMessage":"command not found"}', result=''))
    tool_bubble(con, C3, 'b7', {'tool': 5, 'name': 'read_file_v2', 'params': '{"targetFile": "client.py"}', 'result': '{"contents": "def fetch(): ..."}', 'status': 'completed'})
    bubble(con, C3, 'b8', 1, 'Try exponential backoff instead')
    bubble(con, C3, 'b9', 2, 'Done: fetch() now backs off.')
    bubble(con, C3, 'not-in-the-manifest', 1, 'a bubble no header lists')
    # Cursor 3.27.14: the headers are paged rows, and the first row of the conversation is a user bubble
    composer(con, C3P, updated=1790000009000)
    put(con, 'composerConvHeaders:%s:000001' % C3P, [header('p3')])
    put(con, 'composerConvHeaders:%s:000000' % C3P, [header('p1', 1), header('p2')])
    bubble(con, C3P, 'p1', 1, 'first prompt')
    bubble(con, C3P, 'p2', 2, 'first answer')
    bubble(con, C3P, 'p3', 2, 'second answer')
    # an older composer: the conversation is inline and tool data sits in capabilities[].data.bubbleDataMap, which is a JSON string
    composer(con, C1, v=1, created=1780000000000, conversation=[
        {'bubbleId': 'o1', 'type': 1, 'text': 'old prompt'}, {'bubbleId': 'o2', 'type': 2, 'text': '', 'capabilityType': 15}, {'bubbleId': 'o3', 'type': 2, 'text': 'old answer'},
        {'bubbleId': 'o4', 'type': 2, 'text': 'tool data lost', 'capabilityType': 15}],
        capabilities=[{'type': 15, 'data': {'bubbleDataMap': json.dumps({'o2': tool_data('run_terminal_cmd', 'git status', 'clean', 'completed')})}}, {'type': 30, 'data': {'customInstructions': 'x'}}])
    bubble(con, C1, 'o3', 2, 'old answer, full text')
    # another project's composer, and one that records no folder
    composer(con, OTHER, cwd='/work/other')
    bubble(con, OTHER, 'x1', 1, 'prompt in another project')
    composer(con, NOPATH, cwd=None)
    for i in range(30):
        put(con, 'checkpointId:%s:%d' % (C3, i), {'junk': i})
        put(con, 'messageRequestContext:%s:%d' % (C3, i), {'junk': i})
    put(con, 'composerHeaders', {'allComposers': []})
    con.execute('COMMIT')
    con.close()


class Store(TmpCase):
    """A temporary Cursor globalStorage directory."""
    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.root, DB)

    def con(self):
        con = new_db(self.db)
        self.addCleanup(lambda: con.close() if con else None)
        return con

    def finish(self, con):
        con.execute('COMMIT')
        con.close()

    def ref(self, cid):
        return os.path.realpath(self.db) + '#' + cid

    def read(self, cid):
        return cursor_ide.read(self.ref(cid), self.root)


class Fixture(Store):
    def setUp(self):
        super().setUp()
        build_fixture(self.db)
        self.s = self.read(C3)

    def test_find_sessions_matches_the_recorded_folder_newest_first(self):
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [self.ref(c) for c in (C3P, C3, C1)])
        self.assertEqual(cursor_ide.find_sessions('/work/other', self.root), [self.ref(OTHER)])
        self.assertEqual(cursor_ide.find_sessions('/work/nowhere', self.root), [])
        self.assertEqual(len(cursor_ide.find_sessions(CWD + '/', self.root)), 3)
        self.assertEqual(len(cursor_ide.find_sessions('/work/x/../repo', self.root)), 3)
        self.assertEqual(cursor_ide.find_sessions(CWD, os.path.join(self.tmp, 'absent')), [])

    def test_user_text_is_the_user_bubbles_and_never_a_tool_or_thinking(self):
        self.assertEqual([e.text for e in kinds(self.s, USER_TEXT)], ['Add a retry to fetch() in client.py', 'Try exponential backoff instead'])
        self.assertEqual(kinds(self.s, INJECTED), [])
        self.assertEqual([e.text for e in kinds(self.s, ASSISTANT_TEXT)], ['I will list the sources first.', 'Done: fetch() now backs off.'])
        self.assertEqual((self.s.id, self.s.kind, self.s.cwd, self.s.started_at, self.s.children), (C3, MAIN, CWD, '2026-09-21T14:13:20.000Z', []))

    def test_bubbles_come_in_manifest_order_and_a_bubble_no_header_lists_is_left_out(self):
        self.assertEqual([e.kind for e in self.s.events], [USER_TEXT, ASSISTANT_TEXT, TOOL_CALL, TOOL_CALL, TOOL_CALL, TOOL_CALL, TOOL_CALL, USER_TEXT, ASSISTANT_TEXT])
        self.assertNotIn('a bubble no header lists', [e.text for e in self.s.events])

    def test_shell_command_output_and_no_exit_code(self):
        t = {x.command: x for x in calls(self.s) if x.command}
        self.assertEqual(sorted(t), ['ls src', 'nosuchcmd', 'pytest -q', 'rm -rf build'])
        ls = t['ls src']
        self.assertEqual((ls.name, ls.is_shell, ls.output, ls.exit_code, ls.is_error, ls.by_user, ls.call_id), ('run_terminal_command_v2', True, 'client.py\nutil.py', None, False, False, 'b3'))
        self.assertEqual(ls.args, {'command': 'ls src'})
        pytest = t['pytest -q']                              # a failing test run: the record has no exit code, so it is not an error
        self.assertEqual((pytest.output, pytest.exit_code, pytest.is_error), ('1 failed, 4 passed', None, False))

    def test_error_and_cancelled_status_is_a_failure(self):
        t = {x.command: x for x in calls(self.s) if x.command}
        self.assertEqual((t['rm -rf build'].is_error, t['rm -rf build'].exit_code), (True, None))
        bad = t['nosuchcmd']
        self.assertEqual((bad.is_error, bad.exit_code), (True, None))
        self.assertEqual(bad.output, 'command not found')            # the visible error message stands in for the missing output

    def test_other_tools_are_not_shells(self):
        read = [x for x in calls(self.s) if x.name == 'read_file_v2'][0]
        self.assertEqual((read.is_shell, read.command, read.args, read.output, read.is_error), (False, None, {'targetFile': 'client.py'}, '{"contents": "def fetch(): ..."}', False))

    def test_paged_headers_are_joined_in_page_order(self):
        s = self.read(C3P)
        self.assertEqual([(e.kind, e.text) for e in s.events], [(USER_TEXT, 'first prompt'), (ASSISTANT_TEXT, 'first answer'), (ASSISTANT_TEXT, 'second answer')])

    def test_the_older_inline_format_reads_tools_from_capabilities(self):
        s = self.read(C1)
        self.assertEqual([(e.kind, e.text) for e in kinds(s, USER_TEXT, ASSISTANT_TEXT)],
                         [(USER_TEXT, 'old prompt'), (ASSISTANT_TEXT, 'old answer, full text'), (ASSISTANT_TEXT, 'tool data lost')])         # the bubble row completes the inline one
        t = calls(s)
        self.assertEqual([(x.name, x.command, x.output, x.is_error, x.call_id) for x in t], [('run_terminal_cmd', 'git status', 'clean', False, 'o2')])
        self.assertEqual(s.started_at, '2026-05-28T20:26:40.000Z')

    def test_locations_name_the_database_and_the_position(self):
        self.assertEqual([e.loc for e in self.s.events][:3], [(os.path.realpath(self.db), 1), (os.path.realpath(self.db), 2), (os.path.realpath(self.db), 3)])

    def test_a_reference_to_a_missing_composer_or_without_one_is_an_error(self):
        for ref in (self.ref('nope'), os.path.realpath(self.db), self.ref(''), self.ref('a:b'), self.ref(NOPATH + 'x')):
            with self.assertRaises(_io.StoreError):
                cursor_ide.read(ref, self.root)

    def test_a_composer_with_no_folder_is_read_but_not_listed(self):
        self.assertEqual(self.read(NOPATH).cwd, None)
        self.assertNotIn(self.ref(NOPATH), cursor_ide.find_sessions(CWD, self.root))

    def test_detect_and_registry(self):
        self.assertTrue(cursor_ide.detect(self.db))
        self.assertTrue(cursor_ide.detect(self.ref(C3)))
        self.assertEqual(adapters.detect_format(self.db), 'cursor-ide')
        self.assertIs(adapters.get('cursor-ide'), cursor_ide)
        self.assertFalse(cursor_ide.detect(os.path.join(self.root, 'missing')))

    def test_a_database_is_detected_without_reading_it_as_json_lines(self):
        old = _io.first_record
        _io.first_record = lambda real: (_ for _ in ()).throw(AssertionError('a database was scanned as JSON lines'))
        try:
            self.assertEqual(adapters.detect_format(self.db), 'cursor-ide')
        finally:
            _io.first_record = old

    def test_a_vscode_database_without_cursordiskkv_is_not_cursors(self):
        other = os.path.join(self.root, 'vscode.vscdb')
        con = sqlite3.connect(other)
        con.execute('CREATE TABLE ItemTable (key TEXT, value TEXT)')
        con.close()
        self.assertFalse(cursor_ide.detect(other))
        self.assertIsNone(adapters.detect_format(other))
        with self.assertRaises(_io.StoreError):
            cursor_ide.read(other + '#x', self.root)
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), cursor_ide.find_sessions(CWD, self.root))


class Records(Store):
    def one(self, headers, bubbles, **extra):
        if os.path.exists(self.db):
            os.unlink(self.db)
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header(b) for b in headers], **extra)
        for args in bubbles:
            bubble(con, 'c', *args[:3], **(args[3] if len(args) > 3 else {}))
        self.finish(con)
        return self.read('c')

    def test_only_type_1_and_type_2_bubbles_are_read_and_blank_text_is_skipped(self):
        s = self.one(['a', 'b', 'c1', 'd', 'e'], [('a', 1, '  '), ('b', 3, 'system?'), ('c1', 2, ''), ('d', 0, 'zero'), ('e', 1, 'real')])
        self.assertEqual([(e.kind, e.text) for e in s.events], [(USER_TEXT, 'real')])

    def test_a_tool_bubble_with_no_resolvable_data_falls_back_to_its_text(self):
        s = self.one(['a', 'b', 'c1'], [('a', 2, 'said', {'capabilityType': 15}), ('b', 2, '', {'capabilityType': 15, 'toolFormerData': {'tool': 1}}),
                                        ('c1', 2, 'named', {'capabilityType': 15, 'toolFormerData': {'name': ''}})])
        self.assertEqual([(e.kind, e.text) for e in s.events], [(ASSISTANT_TEXT, 'said'), (ASSISTANT_TEXT, 'named')])

    def test_a_bubble_with_tool_data_but_no_tool_capability_is_text(self):
        s = self.one(['a'], [('a', 2, 'plain', {'toolFormerData': tool_data()})])
        self.assertEqual([(e.kind, e.text) for e in s.events], [(ASSISTANT_TEXT, 'plain')])

    def test_version_3_reads_the_bubbles_tool_data_not_the_capability_map(self):
        caps = [{'type': 15, 'data': {'bubbleDataMap': {'a': tool_data(command='from the map')}}}]
        s = self.one(['a'], [('a', 2, '', {'capabilityType': 15, 'toolFormerData': tool_data(command='from the bubble')})], capabilities=caps)
        self.assertEqual([t.command for t in calls(s)], ['from the bubble'])
        s = self.one(['a'], [('a', 2, '', {'capabilityType': 15})], capabilities=caps)           # no toolFormerData: the capability map answers
        self.assertEqual([t.command for t in calls(s)], ['from the map'])

    def test_older_versions_read_the_capability_map_even_when_the_bubble_has_data(self):
        caps = [{'type': 15, 'data': {'bubbleDataMap': {'a': tool_data(command='from the map')}}}]
        s = self.one(['a'], [('a', 2, '', {'capabilityType': 15, 'toolFormerData': tool_data(command='from the bubble')})], capabilities=caps, v=2)
        self.assertEqual([t.command for t in calls(s)], ['from the map'])

    def test_command_comes_from_params_then_rawargs(self):
        d = dict(tool_data(), params='', rawArgs=json.dumps({'command': 'from rawArgs'}))
        s = self.one(['a', 'b'], [('a', 2, '', {'capabilityType': 15, 'toolFormerData': d}),
                                  ('b', 2, '', {'capabilityType': 15, 'toolFormerData': dict(tool_data(), params=json.dumps({'command': 'from params'}), rawArgs=json.dumps({'command': 'ignored'}))})])
        self.assertEqual([t.command for t in calls(s)], ['from rawArgs', 'from params'])

    def test_each_shell_tool_name(self):
        names = ['run_terminal_cmd', 'run_terminal_command', 'run_terminal_command_v2', 'shell', 'bash']
        s = self.one(['n%d' % i for i in range(5)], [('n%d' % i, 2, '', {'capabilityType': 15, 'toolFormerData': tool_data(name=n)}) for i, n in enumerate(names)])
        self.assertEqual([(t.name, t.is_shell, t.command) for t in calls(s)], [(n, n.startswith('run_'), 'ls' if n.startswith('run_') else None) for n in names])

    def test_the_result_of_a_shell_is_its_output_field_and_nothing_else(self):
        cases = [json.dumps({'output': 'a'}), json.dumps({'output': 3}), json.dumps({'stdout': 'b'}), 'plain text', '', json.dumps(['x']), None, {'output': 'object'}]
        s = self.one(['r%d' % i for i in range(len(cases))], [('r%d' % i, 2, '', {'capabilityType': 15, 'toolFormerData': dict(tool_data(), result=r)}) for i, r in enumerate(cases)])
        self.assertEqual([t.output for t in calls(s)], ['a', None, None, None, None, None, None, 'object'])
        self.assertEqual({t.exit_code for t in calls(s)}, {None})

    def test_an_exit_code_in_a_result_is_not_read(self):
        d = dict(tool_data(), result=json.dumps({'output': 'x', 'exitCode': 2, 'exit_code': 2}))
        s = self.one(['a'], [('a', 2, '', {'capabilityType': 15, 'toolFormerData': d})])
        t = calls(s)[0]
        self.assertEqual((t.exit_code, t.is_error), (None, False))

    def test_the_error_text_is_the_visible_message_or_else_the_error_as_recorded(self):
        cases = ['{"clientVisibleErrorMessage":"", "x": 1}', 'plain failure', '[1]', '{"clientVisibleErrorMessage": 5}', '{"clientVisibleErrorMessage":"seen"}', None, 7]
        s = self.one(['e%d' % i for i in range(len(cases))], [('e%d' % i, 2, '', {'capabilityType': 15, 'toolFormerData': {'tool': 15, 'name': 'run_terminal_command_v2', 'status': 'error', 'error': e}}) for i, e in enumerate(cases)])
        self.assertEqual([t.output for t in calls(s)], ['{"clientVisibleErrorMessage":"", "x": 1}', 'plain failure', '[1]', '{"clientVisibleErrorMessage": 5}', 'seen', None, None])

    def test_statuses(self):
        cases = ['completed', 'error', 'cancelled', 'loading', None, 7]
        s = self.one(['s%d' % i for i in range(len(cases))], [('s%d' % i, 2, '', {'capabilityType': 15, 'toolFormerData': dict(tool_data(), status=st)}) for i, st in enumerate(cases)])
        self.assertEqual([t.is_error for t in calls(s)], [False, True, True, False, False, False])

    def test_odd_tool_arguments(self):
        cases = [dict(tool_data(), params=p, rawArgs=r) for p, r in [(None, None), ('not json', 'also not'), ('[1]', '7'), ({'command': 'object params'}, {}), ('{"command": 5}', '{"command": ["a"]}')]]
        s = self.one(['t%d' % i for i in range(len(cases))], [('t%d' % i, 2, '', {'capabilityType': 15, 'toolFormerData': d}) for i, d in enumerate(cases)])
        self.assertEqual([(t.command, t.args) for t in calls(s)], [(None, None), (None, 'not json'), (None, '[1]'), ('object params', {'command': 'object params'}), (None, {'command': 5})])

    def test_a_composer_with_no_manifest_and_no_inline_conversation_has_no_events(self):
        con = self.con()
        composer(con, 'c')
        bubble(con, 'c', 'a', 1, 'orphan')
        self.finish(con)
        self.assertEqual(self.read('c').events, [])

    def test_pages_are_ordered_by_number_whether_or_not_they_are_zero_padded(self):
        con = self.con()
        composer(con, 'c')
        for page in ('2', '10', '1', '000003', 'zz', '0'):
            put(con, 'composerConvHeaders:c:%s' % page, [header('p' + page, 1)])
            bubble(con, 'c', 'p' + page, 1, 'page ' + page)
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['page 0', 'page 1', 'page 2', 'page 000003', 'page 10', 'page zz'])

    def test_the_inline_manifest_wins_over_paged_headers(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1)])
        put(con, 'composerConvHeaders:c:000000', [header('b', 1)])
        bubble(con, 'c', 'a', 1, 'inline')
        bubble(con, 'c', 'b', 1, 'paged')
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['inline'])

    def test_headers_of_another_composer_are_not_borrowed(self):
        con = self.con()
        composer(con, 'c')
        composer(con, 'c2')
        put(con, 'composerConvHeaders:c2:000000', [header('b', 1)])
        bubble(con, 'c2', 'b', 1, 'not mine')
        bubble(con, 'c', 'b', 1, 'mine')
        self.finish(con)
        self.assertEqual(self.read('c').events, [])

    def test_a_bubble_of_another_composer_whose_id_starts_the_same_is_not_read(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1), header('2:b', 1)])
        composer(con, 'c2')
        bubble(con, 'c', 'a', 1, 'mine')
        bubble(con, 'c2', 'b', 1, 'the neighbour')
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['mine'])

    def test_a_sql_wildcard_in_a_composer_id_matches_nothing_else(self):
        con = self.con()
        composer(con, '%', fullConversationHeadersOnly=[header('a', 1)])
        composer(con, 'xyz', fullConversationHeadersOnly=[header('a', 1)])
        bubble(con, 'xyz', 'a', 1, 'other composer')
        self.finish(con)
        self.assertEqual(self.read('%').events, [])

    def test_value_columns_of_type_blob_are_read(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1)])
        put(con, 'bubbleId:c:a', json.dumps({'bubbleId': 'a', 'type': 1, 'text': 'as a blob'}).encode())
        put(con, 'composerData:blobby', json.dumps({'_v': 17, 'workspaceIdentifier': {'uri': {'fsPath': CWD}}}).encode())
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['as a blob'])
        self.assertIn(self.ref('blobby'), cursor_ide.find_sessions(CWD, self.root))

    def test_find_sessions_matches_a_symlinked_folder_by_its_real_path_or_as_given(self):
        real = os.path.join(self.tmp, 'proj')
        os.makedirs(real)
        link = os.path.join(self.tmp, 'link')
        os.symlink(real, link)
        con = self.con()
        composer(con, 'r', cwd=os.path.realpath(real))
        composer(con, 'l', cwd=link)
        self.finish(con)
        self.assertEqual(sorted(cursor_ide.find_sessions(link, self.root)), sorted([self.ref('r'), self.ref('l')]))
        self.assertEqual(sorted(cursor_ide.find_sessions(real, self.root)), sorted([self.ref('r'), self.ref('l')]))             # a recorded folder that is itself a link

    def test_odd_folders_never_match_or_crash(self):
        con = self.con()
        for i, p in enumerate([None, 7, '', 'relative/path', 'bad\0nul', ['/work/repo'], {'a': 1}]):
            put(con, 'composerData:odd%d' % i, {'workspaceIdentifier': {'uri': {'fsPath': p}}})
        put(con, 'composerData:no-uri', {'workspaceIdentifier': {'id': 'x'}})
        put(con, 'composerData:wsid-str', {'workspaceIdentifier': 'str'})
        self.finish(con)
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [])
        self.assertEqual(cursor_ide.find_sessions(os.path.join(os.getcwd(), 'relative', 'path'), self.root), [])      # a relative folder is not read against the working directory

    def test_an_id_with_a_colon_or_hash_is_never_listed(self):
        con = self.con()
        composer(con, 'a:b')
        composer(con, 'a#b')
        composer(con, 'fine')
        self.finish(con)
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [self.ref('fine')])

    def test_ordering_uses_last_updated_then_created(self):
        con = self.con()
        composer(con, 'old', created=1, updated=1)
        composer(con, 'newer', created=1, updated=3)
        put(con, 'composerData:created-only', {'createdAt': 2, 'workspaceIdentifier': {'uri': {'fsPath': CWD}}})
        put(con, 'composerData:neither', {'workspaceIdentifier': {'uri': {'fsPath': CWD}}})
        put(con, 'composerData:weird', {'lastUpdatedAt': 'x', 'createdAt': 'y', 'workspaceIdentifier': {'uri': {'fsPath': CWD}}})
        self.finish(con)
        got = [r.rpartition('#')[2] for r in cursor_ide.find_sessions(CWD, self.root)]
        self.assertEqual(got[:3], ['newer', 'created-only', 'old'])
        self.assertEqual(sorted(got[3:]), ['neither', 'weird'])

    def test_platform_roots(self):
        home = os.path.expanduser('~')
        self.assertEqual(cursor_ide.default_root('linux'), os.path.join(home, '.config', 'Cursor', 'User', 'globalStorage'))
        self.assertEqual(cursor_ide.default_root('darwin'), os.path.join(home, 'Library', 'Application Support', 'Cursor', 'User', 'globalStorage'))
        self.assertEqual(cursor_ide.default_root('win32'), os.path.join(home, 'AppData', 'Roaming', 'Cursor', 'User', 'globalStorage'))
        self.assertEqual(cursor_ide.default_root('freebsd13'), cursor_ide.default_root('linux'))


class WriteAheadLog(Store):
    def test_committed_rows_still_in_the_wal_are_visible_and_nothing_is_written(self):
        con = sqlite3.connect(self.db, isolation_level=None)
        self.assertEqual(con.execute('PRAGMA journal_mode = WAL').fetchone()[0], 'wal')
        con.execute('PRAGMA wal_autocheckpoint = 0')
        con.execute('CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)')
        composer(con, 'w', fullConversationHeadersOnly=[header('a', 1)])
        bubble(con, 'w', 'a', 1, 'only in the log')
        try:
            self.assertGreater(os.path.getsize(self.db + '-wal'), 0)
            with open(self.db, 'rb') as fh:
                self.assertNotIn(b'only in the log', fh.read())
            before = (os.stat(self.db).st_mtime_ns, os.stat(self.db).st_size)
            self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [self.ref('w')])
            self.assertEqual([e.text for e in self.read('w').events], ['only in the log'])
            self.assertEqual((os.stat(self.db).st_mtime_ns, os.stat(self.db).st_size), before)
        finally:
            con.close()

    def test_the_connection_cannot_write(self):
        build_fixture(self.db)
        con = cursor_ide._connect(os.path.realpath(self.db))
        try:
            with self.assertRaises(sqlite3.Error):
                con.execute("INSERT INTO cursorDiskKV (key, value) VALUES ('a', 'b')")
        finally:
            con.close()


# ---------------------------------------------------------------- bounded reads

class Bounded(Store):
    """A database holds every conversation of the machine: only the rows of the one composer may be read."""
    ROWS, PAYLOAD = 6000, 'x' * 6000

    def build(self):
        con = self.con()
        composer(con, 'mine', fullConversationHeadersOnly=[header('m%d' % i, 1) for i in range(20)])
        for i in range(20):
            bubble(con, 'mine', 'm%d' % i, 1, 'mine %d' % i)
        for n in range(self.ROWS):
            cid = 'noise%d' % (n % 50)
            if n < 50:
                composer(con, cid, cwd='/work/elsewhere')
            bubble(con, cid, 'b%d' % n, 2, self.PAYLOAD)
            put(con, 'checkpointId:%s:%d' % (cid, n), {'junk': self.PAYLOAD})
        self.finish(con)
        self.assertGreater(os.path.getsize(self.db), 60 * 1024 * 1024)

    def test_reads_touch_only_the_keys_asked_for(self):
        self.build()
        seen = []
        real = cursor_ide._connect

        def spying(path):
            con = real(path)
            con.set_trace_callback(seen.append)
            return con
        cursor_ide._connect = spying
        try:
            self.assertEqual([e.text for e in self.read('mine').events][:2], ['mine 0', 'mine 1'])
            self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [self.ref('mine')])
        finally:
            cursor_ide._connect = real
        scans = [q for q in seen if 'cursorDiskKV' in q and 'PRAGMA' not in q]
        self.assertTrue(scans)
        for q in scans:
            self.assertTrue("key >= 'composerData:'" in q or "key >= 'composerData:mine'" in q or "key >= 'bubbleId:mine:'" in q or "key >= 'composerConvHeaders:mine:'" in q or "key = 'composerData:mine'" in q, q[:200])
            self.assertNotIn('LIKE', q)

    def test_a_large_database_is_not_loaded_into_memory(self):
        self.build()
        script = ('import resource,sys; sys.path.insert(0, %r)\n'
                  'from lib.adapters import cursor_ide\n'
                  'base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss\n'
                  'ref = cursor_ide.find_sessions(%r, %r)[0]\n'
                  'n = len(cursor_ide.read(ref, %r).events)\n'
                  'print(n, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - base)\n') % (
            os.path.join(os.path.dirname(HERE), 'scripts'), CWD, self.root, self.root)
        out = subprocess.run([sys.executable, '-I', '-c', script], capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        events, grown_kb = map(int, out.stdout.split())
        size_mb = os.path.getsize(self.db) / 1048576
        self.assertEqual(events, 20)
        self.assertLess(grown_kb / 1024, 12, 'peak memory grew by %d KB reading a %d MB database' % (grown_kb, size_mb))

    def test_python_allocations_stay_small_in_process(self):
        self.build()
        tracemalloc.start()
        try:
            cursor_ide.find_sessions(CWD, self.root)
            self.read('mine')
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 2 * 1024 * 1024)

    def test_rows_of_the_composer_itself_are_streamed(self):
        con = self.con()
        composer(con, 'big', fullConversationHeadersOnly=[header('b%d' % i, 1) for i in range(300)])
        for i in range(300):
            bubble(con, 'big', 'b%d' % i, 1, 'w' * 100000)
        self.finish(con)
        tracemalloc.start()
        try:
            s = self.read('big')
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(s.events), 300)
        self.assertLess(peak, 45 * 1000 * 1000)                # the events hold the 30 MB of text once; holding every raw row as well would pass 60 MB


# ---------------------------------------------------------------- hostile databases

class Hostile(Store):
    def test_an_empty_file_is_no_database(self):
        open(self.db, 'wb').close()
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [])
        self.assertFalse(cursor_ide.detect(self.db))
        with self.assertRaises(_io.StoreError):
            self.read('s')

    def test_a_missing_database_has_no_sessions(self):
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [])
        with self.assertRaises(_io.RootError):
            self.read('s')

    def test_garbage_bytes_and_a_valid_header_with_a_corrupt_body_are_store_errors(self):
        for body in (b'not a database at all' * 100, MAGIC + b'\xff' * 4000, MAGIC):
            with open(self.db, 'wb') as fh:
                fh.write(body)
            self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [])
            self.assertFalse(cursor_ide.detect(self.db))
            with self.assertRaises(_io.StoreError):
                self.read('s')

    def test_a_database_cut_short_is_a_store_error(self):
        build_fixture(self.db)
        con = sqlite3.connect(self.db)
        for i in range(300):
            con.execute('INSERT INTO cursorDiskKV VALUES (?, ?)', ('bubbleId:%s:z%d' % (C3, i), json.dumps({'type': 1, 'text': 'row %d ' % i + 'x' * 500})))
        con.commit()
        con.close()
        with open(self.db, 'r+b') as fh:
            fh.truncate(os.path.getsize(self.db) // 2)
        try:
            self.read(C3)
        except _io.StoreError:
            pass                                          # either the tables are gone or a page is missing: never a raw sqlite error
        self.assertIsInstance(cursor_ide.find_sessions(CWD, self.root), list)

    def test_a_locked_database_is_a_store_error_and_find_sessions_is_empty(self):
        build_fixture(self.db)
        writer = sqlite3.connect(self.db, isolation_level=None)
        writer.execute('BEGIN EXCLUSIVE')
        old = cursor_ide.BUSY_SECONDS
        cursor_ide.BUSY_SECONDS = 0.05
        try:
            with self.assertRaises(_io.StoreError):
                self.read(C3)
            self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [])
        finally:
            cursor_ide.BUSY_SECONDS = old
            writer.execute('ROLLBACK')
            writer.close()
        self.assertEqual(self.read(C3).id, C3)

    def test_invalid_utf8_in_a_value_is_replaced(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1), header('b', 1)])
        bubble(con, 'c', 'a', 1, 'ok')
        con.execute("INSERT INTO cursorDiskKV VALUES ('bubbleId:c:b', CAST(X'7B2274797065223A312C2274657874223A2262616420FF22207D' AS TEXT))")
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['ok', 'bad �'])

    def test_a_5mb_row_is_read_whole(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1), header('b', 1)])
        big = 'x' * (5 * 1024 * 1024)
        bubble(con, 'c', 'a', 1, big)
        bubble(con, 'c', 'b', 1, 'after')
        self.finish(con)
        self.assertEqual([len(e.text) for e in self.read('c').events], [len(big), 5])

    def test_a_row_over_the_cap_is_skipped_and_reading_continues(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1), header('b', 1)])
        bubble(con, 'c', 'a', 1, 'y' * 5000)
        bubble(con, 'c', 'b', 1, 'after')
        composer(con, 'huge', cwd=CWD, pad='z' * 5000)
        self.finish(con)
        old = _io.MAX_LINE
        _io.MAX_LINE = 1000
        try:
            self.assertEqual([e.text for e in self.read('c').events], ['after'])
            self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [self.ref('c')])            # a composerData row over the cap is not listed ...
            with self.assertRaises(_io.StoreError):
                self.read('huge')                                                                  # ... and not read
        finally:
            _io.MAX_LINE = old

    def test_rows_that_are_not_json_objects_or_have_odd_types_are_skipped(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1), header('b', 1), header('c1', 1), header('d', 1), header('e', 1), header('f', 1), header('g', 1)])
        put(con, 'bubbleId:c:a', 'not json')
        put(con, 'bubbleId:c:b', '[1, 2]')
        put(con, 'bubbleId:c:c1', 'null')
        put(con, 'bubbleId:c:d', {'type': '1', 'text': 'type as a string'})
        put(con, 'bubbleId:c:e', {'type': 1, 'text': 5})
        put(con, 'bubbleId:c:f', {'type': 1.0, 'text': 'float type'})
        put(con, 'bubbleId:c:g', {'type': True, 'text': 'bool type'})
        con.execute("INSERT INTO cursorDiskKV VALUES ('bubbleId:c:h', NULL)")
        con.execute("INSERT INTO cursorDiskKV VALUES ('composerData:nullrow', NULL)")
        put(con, 'composerData:arr', '[1]')
        put(con, 'composerData:str', '"x"')
        put(con, 'composerData:bad', '{"workspaceIdentifier": ')
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['float type'])
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [self.ref('c')])
        for cid in ('arr', 'str', 'bad', 'nullrow'):
            with self.assertRaises(_io.StoreError):
                self.read(cid)

    def test_odd_manifests_and_capabilities_do_not_break_the_read(self):
        con = self.con()
        composer(con, 'c1', fullConversationHeadersOnly='x', conversation=7, capabilities=7)
        composer(con, 'c2', fullConversationHeadersOnly=[1, None, {}, {'bubbleId': 5}, {'bubbleId': 'a'}], capabilities=[3, {'type': 15}, {'type': 15, 'data': 5}, {'type': 'x', 'data': {'bubbleDataMap': '{}'}},
                                                                                                               {'type': 15, 'data': {'bubbleDataMap': 'not json'}}, {'type': 15, 'data': {'bubbleDataMap': {'a': 5}}}])
        bubble(con, 'c2', 'a', 2, 'hello', capabilityType=15)
        composer(con, 'c3', v='3', conversation=[3, {}, {'bubbleId': 'q'}, {'bubbleId': 'r', 'type': 1, 'text': 'inline only'}])
        composer(con, 'c4', v=1e400)
        put(con, 'composerConvHeaders:c4:000000', 'not json')
        put(con, 'composerConvHeaders:c4:000001', {'a': 1})
        put(con, 'composerConvHeaders:c4:000002', [1, {'bubbleId': 'x'}])
        self.finish(con)
        self.assertEqual(self.read('c1').events, [])
        self.assertEqual([(e.kind, e.text) for e in self.read('c2').events], [(ASSISTANT_TEXT, 'hello')])
        self.assertEqual([e.text for e in self.read('c3').events], ['inline only'])
        self.assertEqual(self.read('c4').events, [])

    def test_a_very_large_or_non_finite_timestamp_is_none(self):
        con = self.con()
        for i, v in enumerate([10 ** 30, -5, 0, True, 'x', float('inf'), 1e400]):
            put(con, 'composerData:t%d' % i, '{"createdAt": %s}' % ('Infinity' if v == float('inf') else json.dumps(v)))
        self.finish(con)
        for i in range(7):
            self.assertIsNone(self.read('t%d' % i).started_at)

    def test_a_manifest_longer_than_the_rows_present_reads_what_exists(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('b%d' % i, 1) for i in range(1000)])
        bubble(con, 'c', 'b500', 1, 'the only one')
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['the only one'])

    def test_a_header_naming_the_same_bubble_twice_reads_it_twice(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('a', 1), header('a', 1)])
        bubble(con, 'c', 'a', 1, 'dup')
        self.finish(con)
        self.assertEqual([e.text for e in self.read('c').events], ['dup', 'dup'])

    def test_bubbles_are_capped(self):
        con = self.con()
        composer(con, 'c', fullConversationHeadersOnly=[header('b%02d' % i, 1) for i in range(10)])
        for i in range(10):
            bubble(con, 'c', 'b%02d' % i, 1, 'm%d' % i)
        self.finish(con)
        old = cursor_ide.MAX_BUBBLES
        cursor_ide.MAX_BUBBLES = 3
        try:
            self.assertEqual([e.text for e in self.read('c').events], ['m0', 'm1', 'm2'])
        finally:
            cursor_ide.MAX_BUBBLES = old


class Guards(Store):
    def forged(self, where):
        os.makedirs(os.path.dirname(where), exist_ok=True)
        con = new_db(where)
        composer(con, 'forged', fullConversationHeadersOnly=[header('a', 1)])
        bubble(con, 'forged', 'a', 1, 'I wrote this myself')
        con.execute('COMMIT')
        con.close()
        return where

    def test_a_database_outside_the_root_is_refused(self):
        outside = self.forged(os.path.join(self.tmp, 'outside', DB))
        with self.assertRaises(_io.RootError):
            cursor_ide.read(outside + '#forged', self.root)

    def test_a_symlink_that_escapes_the_root_is_refused(self):
        outside = self.forged(os.path.join(self.tmp, 'outside', DB))
        os.symlink(outside, self.db)
        with self.assertRaises(_io.RootError):
            cursor_ide.read(self.db + '#forged', self.root)
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [])

    def test_a_symlinked_directory_that_escapes_the_root_is_refused(self):
        outside = self.forged(os.path.join(self.tmp, 'outside', 'data', DB))
        os.symlink(os.path.dirname(outside), os.path.join(self.root, 'data'))
        with self.assertRaises(_io.RootError):
            cursor_ide.read(os.path.join(self.root, 'data', DB) + '#forged', self.root)

    def test_dotdot_cannot_climb_out_of_the_root(self):
        self.forged(os.path.join(self.tmp, DB))
        with self.assertRaises(_io.RootError):
            cursor_ide.read(os.path.join(self.root, '..', DB) + '#forged', self.root)

    def test_a_sibling_directory_sharing_the_roots_name_prefix_is_outside(self):
        sibling = self.forged(os.path.join(self.root + '-evil', DB))
        with self.assertRaises(_io.RootError):
            cursor_ide.read(sibling + '#forged', self.root)

    def test_a_symlink_inside_the_root_to_a_database_inside_the_root_is_fine(self):
        real = self.forged(os.path.join(self.root, 'real', DB))
        link = os.path.join(self.root, 'link.db')
        os.symlink(real, link)
        self.assertEqual([e.text for e in cursor_ide.read(link + '#forged', self.root).events], ['I wrote this myself'])

    def test_a_fifo_or_directory_is_not_opened(self):
        os.mkfifo(self.db)
        with self.assertRaises(_io.RootError):
            cursor_ide.read(self.db + '#s', self.root)
        self.assertEqual(cursor_ide.find_sessions(CWD, self.root), [])
        self.assertFalse(cursor_ide.detect(self.db))
        os.unlink(self.db)
        os.mkdir(self.db)
        with self.assertRaises(_io.RootError):
            cursor_ide.read(self.db + '#s', self.root)

    def test_the_default_root_is_the_user_data_directory_and_no_environment_variable_moves_it(self):
        names = ('XDG_CONFIG_HOME', 'APPDATA', 'CURSOR_USER_DATA_DIR', 'CURSOR_DATA_DIR', 'HOME')
        saved = {k: os.environ.get(k) for k in names}
        try:
            for k in names[:-1]:
                os.environ[k] = self.tmp
            self.assertEqual(cursor_ide.default_root('linux'), os.path.join(os.path.expanduser('~'), '.config', 'Cursor', 'User', 'globalStorage'))
            self.assertEqual(cursor_ide.default_root('win32'), os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming', 'Cursor', 'User', 'globalStorage'))
            outside = self.forged(os.path.join(self.tmp, DB))
            with self.assertRaises(_io.RootError):
                cursor_ide.read(outside + '#forged')                  # no root argument: the default root applies
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == '__main__':
    unittest.main()
