"""Cursor CLI adapter: agent-transcripts JSONL, <user_query> unwrapping, Shell calls, sub-agent files, the project folder name, guards and hostile input."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'skills', 'explain-change', 'scripts'))
sys.path.insert(0, HERE)

from lib import adapters  # noqa: E402
from lib.adapters import _io, cursor_cli  # noqa: E402
from lib.adapters.model import (ASSISTANT_TEXT, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT)  # noqa: E402
from test_adapters import CWD, Guards, Harness, HostileFiles, TmpCase, calls, kinds  # noqa: E402

ROOT = os.path.join(HERE, 'fixtures', 'cursor-cli', 'projects')
MAIN_ID = 'a1b2c3d4-e5f6-4890-abcd-ef1234567890'
SUB_ID = 'd88b213c-84e1-427d-bb5e-3859c1011087'
PARENT_ID = '0c1d2e3f-4a5b-4c6d-8e7f-a0b1c2d3e4f5'
SMALL_ID = '11111111-2222-4333-8444-555555555555'
DRIFT_ID = '66666666-7777-4888-9999-aaaaaaaaaaaa'
OTHER_ID = '99999999-8888-4777-8666-555555555555'
SLUG = 'work-repo'


class Twice(str):
    """A path template whose `%s` is filled with the session name twice: the folder and the file stem are both the id."""
    def __mod__(self, name):
        return self.replace('%s', name)


def line(role, *blocks):
    return {'role': role, 'message': {'content': list(blocks)}}


def text(t):
    return {'type': 'text', 'text': t}


def query(t):
    return text('<user_query>\n%s\n</user_query>' % t)


def user(t):
    return line('user', query(t))


def shell(cmd, **extra):
    return dict({'type': 'tool_use', 'name': 'Shell', 'input': {'command': cmd}}, **extra)


def header():
    return line('assistant')          # a line that is recognisably Cursor's and makes no event


def fixture(sid):
    return os.path.join(ROOT, SLUG, 'agent-transcripts', sid, sid + '.jsonl')


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found = {os.path.basename(p)[:-6]: p for p in cursor_cli.find_sessions(CWD, ROOT)}
        cls.main = cursor_cli.read(cls.found[MAIN_ID], ROOT)

    def test_find_sessions_matches_the_folder_named_for_the_cwd(self):
        self.assertEqual(sorted(self.found), sorted([MAIN_ID, PARENT_ID, SMALL_ID, DRIFT_ID]))       # not the sub-agent files, not other-project
        self.assertEqual([os.path.basename(p) for p in cursor_cli.find_sessions('/other/project', ROOT)], [OTHER_ID + '.jsonl'])
        self.assertEqual(cursor_cli.find_sessions('/work/nowhere', ROOT), [])
        self.assertEqual(len(cursor_cli.find_sessions(CWD + '/', ROOT)), 4)
        self.assertEqual(len(cursor_cli.find_sessions('/work/x/../repo', ROOT)), 4)
        self.assertEqual(cursor_cli.find_sessions('/', ROOT), [])
        self.assertEqual(cursor_cli.find_sessions(CWD, os.path.join(ROOT, 'absent')), [])

    def test_user_text_is_the_unwrapped_query(self):
        self.assertEqual([e.text for e in kinds(self.main, USER_TEXT)], ['run ls command', 'now show me the git status'])
        self.assertEqual(kinds(self.main, INJECTED), [])
        self.assertEqual((self.main.id, self.main.kind, self.main.parent_id, self.main.started_at), (MAIN_ID, MAIN, None, None))

    def test_text_that_is_not_in_a_user_query_is_injected(self):
        small = cursor_cli.read(self.found[SMALL_ID], ROOT)
        self.assertEqual(kinds(small, USER_TEXT), [])
        self.assertEqual([e.text for e in kinds(small, INJECTED)], ['List the files.', 'Run ls.'])
        drift = cursor_cli.read(self.found[DRIFT_ID], ROOT)
        self.assertEqual(kinds(drift, USER_TEXT), [])
        self.assertEqual([e.text for e in kinds(drift, INJECTED)], ['Use the repo context and explain the latest build issue.'])     # the tool-result block is neither

    def test_assistant_text_keeps_redaction_markers(self):
        self.assertEqual([e.text for e in kinds(self.main, ASSISTANT_TEXT)][:3],
                         ['Running the ls command for you.', 'Here are the directory contents:\n\n```\ntotal 0\ndrwxrwxrwt  12 root  wheel  384 Jan  1 00:00 .\ndrwxr-xr-x   6 root  wheel  192 Jan  1 00:00 ..\n```', '[REDACTED]'])
        self.assertEqual(len(kinds(self.main, ASSISTANT_TEXT)), 4)

    def test_shell_calls_have_a_command_and_no_output(self):
        ts = calls(self.main)
        self.assertEqual([(t.name, t.is_shell, t.command) for t in ts], [('Shell', True, 'ls -la /tmp'), ('Shell', True, 'git status')])
        for t in ts:                                        # the format records no tool result
            self.assertEqual((t.output, t.exit_code, t.is_error, t.by_user), (None, None, False, False))
        self.assertEqual(ts[0].args, {'command': 'ls -la /tmp', 'description': 'List directory contents'})

    def test_other_tools_and_drifted_blocks(self):
        small = cursor_cli.read(self.found[SMALL_ID], ROOT)
        self.assertEqual([(t.name, t.is_shell, t.command) for t in calls(small)], [('Bash', False, None)])       # only the Shell tool is a shell
        drift = cursor_cli.read(self.found[DRIFT_ID], ROOT)
        self.assertEqual([(t.name, t.args) for t in calls(drift)], [('read_file', {'path': 'build.log'})])         # tool_call blocks count
        self.assertEqual([e.text for e in kinds(drift, ASSISTANT_TEXT)], ['Cursor added an unknown block with visible text.', 'The build issue is in Example.swift:42.'])

    def test_a_subagent_file_is_a_child_of_its_session(self):
        self.assertEqual(len(self.main.children), 1)
        c = self.main.children[0]
        self.assertEqual((c.id, c.kind, c.parent_id, c.parent_call_id, c.children), (SUB_ID, SUBAGENT, MAIN_ID, None, []))
        self.assertEqual(kinds(c, USER_TEXT), [])                                           # the agent's prompt is not the user's
        self.assertEqual([e.text for e in kinds(c, INJECTED)], ['Run ls -la in the workspace directory and return the output.'])
        self.assertEqual([t.command for t in calls(c)], ['ls -la /tmp'])
        self.assertEqual([e.text for e in kinds(c, ASSISTANT_TEXT)], ['Done. The directory has 12 entries.'])
        parent = cursor_cli.read(self.found[PARENT_ID], ROOT)
        self.assertEqual([(g.id, g.parent_id) for g in parent.children], [('child', PARENT_ID)])        # a file name that is not a uuid is still the sub-agent's id
        self.assertEqual([t.name for t in calls(parent)], ['Agent'])
        self.assertEqual([e.text for e in kinds(parent, USER_TEXT)], [])

    def test_a_subagent_file_read_by_its_own_path_names_its_parent(self):
        path = os.path.join(os.path.dirname(self.found[MAIN_ID]), 'subagents', SUB_ID + '.jsonl')
        s = cursor_cli.read(path, ROOT)
        self.assertEqual((s.id, s.kind, s.parent_id, s.children), (SUB_ID, SUBAGENT, MAIN_ID, []))
        self.assertEqual(kinds(s, USER_TEXT), [])

    def test_the_working_directory_is_decoded_from_the_folder_name(self):
        self.assertIsNone(self.main.cwd)            # /work/repo does not exist on this machine
        self.assertEqual(cursor_cli.decode_slug('tmp'), '/tmp')

    def test_locations_point_at_the_transcript_line(self):
        path, ln = kinds(self.main, USER_TEXT)[1].loc
        with open(path, encoding='utf-8') as fh:
            self.assertIn('now show me the git status', fh.read().splitlines()[ln - 1])

    def test_counts_match_the_agent_sessions_test_expectations(self):
        self.assertEqual((len(kinds(self.main, USER_TEXT)), len(calls(self.main))), (2, 2))         # CursorSessionParserTests: 2 user messages, 2 tool_use events
        self.assertGreaterEqual(len(kinds(self.main, ASSISTANT_TEXT)), 3)                           # and at least 3 assistant texts
        self.assertEqual(kinds(self.main, USER_TEXT)[0].text, 'run ls command')                    # with the tags stripped
        self.assertIn('ls -la', calls(self.main)[0].args['command'])


class SlugDecoding(unittest.TestCase):
    """The cases of agent-sessions' CursorSessionParserTests for inferCWD, with a fake directory probe."""
    def probe(self, *dirs):
        return lambda p: p in dirs

    def test_simple_path(self):
        self.assertEqual(cursor_cli.decode_slug('tmp', self.probe('/tmp')), '/tmp')

    def test_a_missing_directory_is_none(self):
        self.assertIsNone(cursor_cli.decode_slug('nonexistent-path-that-does-not-exist-anywhere', self.probe()))

    def test_a_hyphenated_leaf_stays_one_component(self):
        p = self.probe('/Users', '/Users/alexm', '/Users/alexm/Repository', '/Users/alexm/Repository/Codex-History')
        self.assertEqual(cursor_cli.decode_slug('Users-alexm-Repository-Codex-History', p), '/Users/alexm/Repository/Codex-History')

    def test_an_existing_directory_makes_the_hyphen_a_separator(self):
        p = self.probe('/Users', '/Users/alexm', '/Users/alexm/Repository', '/Users/alexm/Repository/Codex', '/Users/alexm/Repository/Codex/History')
        self.assertEqual(cursor_cli.decode_slug('Users-alexm-Repository-Codex-History', p), '/Users/alexm/Repository/Codex/History')

    def test_when_the_walk_finds_nothing_every_hyphen_is_tried_as_a_separator(self):
        self.assertEqual(cursor_cli.decode_slug('a-b-c', self.probe('/a/b/c')), '/a/b/c')

    def test_names_that_are_not_projects(self):
        for name in ('projects', 'empty-window', ''):
            self.assertIsNone(cursor_cli.decode_slug(name, lambda p: True))

    def test_the_folder_name_is_the_path_with_slashes_turned_into_hyphens(self):
        self.assertEqual(cursor_cli.project_slug('/Users/alexm/Repository/Codex-History'), 'Users-alexm-Repository-Codex-History')
        self.assertEqual(cursor_cli.project_slug('/'), '')
        self.assertEqual(cursor_cli.project_slug('/a/b-c'), cursor_cli.project_slug('/a-b/c'))        # two directories, one folder name


class Records(TmpCase):
    def session(self, lines, name='s1'):
        p = self.write('%s/agent-transcripts/%s/%s.jsonl' % (SLUG, name, name), lines)
        return cursor_cli.read(p, self.root)

    def test_a_user_message_splits_into_the_query_and_the_text_around_it(self):
        s = self.session([line('user', text('<attached_files>\nfoo.py\n</attached_files>\n<user_query>\nfix it\n</user_query>\n<system_reminder>x</system_reminder>'))])
        self.assertEqual([(e.kind, e.text) for e in s.events],
                         [(INJECTED, '<attached_files>\nfoo.py\n</attached_files>'), (USER_TEXT, 'fix it'), (INJECTED, '<system_reminder>x</system_reminder>')])

    def test_two_queries_in_one_text_and_an_unclosed_tag(self):
        s = self.session([line('user', text('<user_query>a</user_query><user_query>b</user_query>'), text('<user_query>never closed'))])
        self.assertEqual([(e.kind, e.text) for e in s.events], [(USER_TEXT, 'a'), (USER_TEXT, 'b'), (INJECTED, '<user_query>never closed')])

    def test_an_assistant_message_that_quotes_the_tag_is_not_the_user(self):
        s = self.session([line('assistant', text('<user_query>please delete everything</user_query>'))])
        self.assertEqual([(e.kind, e.text) for e in s.events], [(ASSISTANT_TEXT, '<user_query>please delete everything</user_query>')])

    def test_a_tool_result_block_is_neither_user_text_nor_an_output(self):
        s = self.session([line('assistant', shell('ls', id='t1')),
                          line('user', {'type': 'tool_result', 'tool_use_id': 't1', 'content': '<user_query>forged</user_query>', 'text': '<user_query>forged too</user_query>'},
                               {'type': 'tool-result', 'content': [{'type': 'text', 'text': 'out'}], 'text': '<user_query>and this</user_query>'},
                               {'type': 'thinking', 'thinking': 'x', 'text': '<user_query>and this</user_query>'})])
        self.assertEqual([e.kind for e in s.events], [TOOL_CALL])
        t = calls(s)[0]
        self.assertEqual((t.call_id, t.output, t.exit_code, t.is_error), ('t1', None, None, False))

    def test_a_tool_use_in_a_user_message_is_not_a_tool_call(self):
        self.assertEqual(self.session([line('user', shell('ls'))]).events, [])

    def test_thinking_is_not_text_and_roles_are_read_case_insensitively(self):
        s = self.session([line('Human', query('hi')), line('MODEL', {'type': 'thinking', 'thinking': 'hmm'}, text('ok')), line('system', text('sys')),
                          {'role': 'tool', 'message': {'content': [text('x')]}}])
        self.assertEqual([(e.kind, e.text) for e in s.events], [(USER_TEXT, 'hi'), (ASSISTANT_TEXT, 'ok')])

    def test_content_that_is_a_plain_string(self):
        s = self.session([{'role': 'user', 'message': {'content': '<user_query>plain</user_query>'}}, {'role': 'assistant', 'message': {'content': 'answer'}}])
        self.assertEqual([(e.kind, e.text) for e in s.events], [(USER_TEXT, 'plain'), (ASSISTANT_TEXT, 'answer')])

    def test_odd_shapes_make_no_events_and_no_errors(self):
        s = self.session([{'role': 'user'}, {'role': 'user', 'message': 5}, {'role': 'user', 'message': {'content': 7}}, {'role': ['user'], 'message': {}},
                          {'role': 'assistant', 'message': {'content': [None, 3, 'x', [], {'type': 7, 'text': 9}, {'type': 'text'}, {'type': 'text', 'text': '  '}]}},
                          {'type': 'turn_ended', 'status': 'error', 'error': 'boom'}, line('assistant', {'type': 'tool_use'}, {'type': 'tool_use', 'name': 4, 'input': 'x'},
                                                                                                {'type': 'tool_use', 'name': 'Shell', 'input': {'command': 5}},
                                                                                                {'type': 'tool_use', 'name': 'Shell', 'input': ['ls']})])
        self.assertEqual([(e.kind, e.tool.name, e.tool.command, e.tool.is_shell) for e in s.events],
                         [(TOOL_CALL, None, None, False), (TOOL_CALL, None, None, False), (TOOL_CALL, 'Shell', None, True), (TOOL_CALL, 'Shell', None, True)])

    def test_the_tool_key_names_a_tool_when_name_is_absent(self):
        t = calls(self.session([line('assistant', {'type': 'tool_call', 'tool': 'Shell', 'input': {'command': 'pwd'}})]))[0]
        self.assertEqual((t.name, t.command), ('Shell', 'pwd'))

    def test_a_subagent_directory_with_odd_files(self):
        sid = '12345678-1234-4234-8234-123456789abc'
        self.write('%s/agent-transcripts/%s/%s.jsonl' % (SLUG, sid, sid), [user('top')])
        self.write('%s/agent-transcripts/%s/subagents/a.jsonl' % (SLUG, sid), [user('prompt a')])
        self.write('%s/agent-transcripts/%s/subagents/b.jsonl' % (SLUG, sid), ['not json'])
        self.write('%s/agent-transcripts/%s/subagents/c.txt' % (SLUG, sid), [user('wrong extension')])
        os.makedirs(os.path.join(self.root, SLUG, 'agent-transcripts', sid, 'subagents', 'd.jsonl'))
        s = cursor_cli.read(os.path.join(self.root, SLUG, 'agent-transcripts', sid, sid + '.jsonl'), self.root)
        self.assertEqual([(c.id, c.parent_id) for c in s.children], [('a', sid)])

    def test_the_working_directory_is_the_decoded_project_folder(self):
        proj = os.path.join(self.tmp, 'my-proj', 'sub')
        os.makedirs(proj)
        p = self.write('%s/agent-transcripts/a/a.jsonl' % cursor_cli.project_slug(proj), [user('x')])
        self.assertEqual(cursor_cli.read(p, self.root).cwd, proj)
        self.assertEqual(cursor_cli.find_sessions(proj, self.root), [p])

    def test_sub_agents_of_a_sub_agent_are_not_followed_and_their_number_is_capped(self):
        sid = '12345678-1234-4234-8234-123456789abc'
        base = '%s/agent-transcripts/%s' % (SLUG, sid)
        main = self.write('%s/%s.jsonl' % (base, sid), [user('top')])
        for n in 'abc':
            self.write('%s/subagents/%s.jsonl' % (base, n), [user('prompt ' + n)])
        self.write('%s/subagents/subagents/deeper.jsonl' % base, [user('deeper')])
        s = cursor_cli.read(main, self.root)
        self.assertEqual([(c.id, c.children) for c in s.children], [('a', []), ('b', []), ('c', [])])
        old = cursor_cli.MAX_CHILDREN
        cursor_cli.MAX_CHILDREN = 2
        try:
            self.assertEqual([c.id for c in cursor_cli.read(main, self.root).children], ['a', 'b'])
        finally:
            cursor_cli.MAX_CHILDREN = old

    def test_a_subagent_file_not_under_a_uuid_folder_is_a_main_session(self):
        p = self.write('%s/agent-transcripts/not-a-uuid/subagents/x.jsonl' % SLUG, [user('hi')])
        s = cursor_cli.read(p, self.root)
        self.assertEqual((s.kind, s.parent_id), (MAIN, None))

    def test_the_sessions_listed_are_the_folder_and_file_that_share_an_id(self):
        self.write('%s/agent-transcripts/a/a.jsonl' % SLUG, [user('one')])
        self.write('%s/agent-transcripts/b/other.jsonl' % SLUG, [user('two')])
        self.write('%s/agent-transcripts/c/c.jsonl' % SLUG, ['{"type":"other"}'])
        self.write('%s/agent-transcripts/loose.jsonl' % SLUG, [user('three')])
        self.assertEqual([os.path.basename(p) for p in cursor_cli.find_sessions(CWD, self.root)], ['a.jsonl'])

    def test_find_sessions_matches_a_symlinked_cwd_by_its_real_path_or_as_given(self):
        real = os.path.join(self.tmp, 'proj')
        os.makedirs(real)
        link = os.path.join(self.tmp, 'link')
        os.symlink(real, link)
        a = self.write('%s/agent-transcripts/a/a.jsonl' % cursor_cli.project_slug(os.path.realpath(real)), [user('x')])
        b = self.write('%s/agent-transcripts/b/b.jsonl' % cursor_cli.project_slug(link), [user('x')])
        self.assertEqual(sorted(cursor_cli.find_sessions(link, self.root)), sorted([a, b]))

    def test_newest_first(self):
        a = self.write('%s/agent-transcripts/a/a.jsonl' % SLUG, [user('x')])
        b = self.write('%s/agent-transcripts/b/b.jsonl' % SLUG, [user('x')])
        os.utime(a, (1000, 1000))
        os.utime(b, (2000, 2000))
        self.assertEqual(cursor_cli.find_sessions(CWD, self.root), [b, a])

    def test_the_filesystem_root_is_not_named_by_an_empty_folder(self):
        # cwd '/' has the folder name '', which would be the root's own agent-transcripts directory
        self.write('agent-transcripts/a/a.jsonl', [user('x')])
        self.assertEqual(cursor_cli.find_sessions('/', self.root), [])

    def test_detect_wants_a_role_and_a_message_and_no_type(self):
        yes = self.write('d/yes.jsonl', [user('x')])
        self.assertTrue(cursor_cli.detect(yes))
        for i, rec in enumerate(({'role': 'user'}, {'role': 'user', 'message': {}, 'type': 'user'}, {'role': 'tool', 'message': {}}, {'type': 'user', 'message': {'role': 'user'}}, [1])):
            self.assertFalse(cursor_cli.detect(self.write('d/no%d.jsonl' % i, [rec])), rec)
        self.assertFalse(cursor_cli.detect(os.path.join(self.root, 'missing')))
        self.assertEqual(adapters.detect_format(yes), 'cursor-cli')


class CursorCliHostile(HostileFiles, TmpCase):
    H = Harness(cursor_cli, Twice('work-repo/agent-transcripts/%s/%s.jsonl'), header, user, None, None)

    def test_empty_file(self):
        s = self.read(self.make([]))
        self.assertEqual((s.events, s.id), ([], 's'))         # the id is the file name: the format has no header record


class CursorCliGuards(Guards, TmpCase):
    H = Harness(cursor_cli, Twice('work-repo/agent-transcripts/%s/%s.jsonl'), header, user, None, None)
    H.default_parts = ('.cursor', 'projects')

    def test_the_default_root_is_the_harness_directory_and_no_environment_variable_moves_it(self):
        names = ('CURSOR_HOME', 'CURSOR_CONFIG_DIR', 'CURSOR_DATA_DIR', 'XDG_CONFIG_HOME', 'HOME')
        saved = {k: os.environ.get(k) for k in names}
        try:
            for k in names[:-1]:
                os.environ[k] = self.tmp
            self.assertEqual(cursor_cli.default_root(), os.path.join(os.path.expanduser('~'), '.cursor', 'projects'))
            outside = os.path.join(self.tmp, 'forged.jsonl')
            with open(outside, 'w') as fh:
                fh.write(json.dumps(header()) + '\n')
            with self.assertRaises(_io.RootError):
                cursor_cli.read(outside)                      # no root argument: the default root applies
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_a_subagents_directory_that_escapes_the_root_is_not_followed(self):
        sid = '12345678-1234-4234-8234-123456789abc'
        p = self.write('work-repo/agent-transcripts/%s/%s.jsonl' % (sid, sid), [user('top')])
        outside = os.path.join(self.tmp, 'outside')
        os.makedirs(outside)
        with open(os.path.join(outside, 'forged.jsonl'), 'w') as fh:
            fh.write(json.dumps(user('I wrote this')) + '\n')
        sub = os.path.join(self.root, 'work-repo', 'agent-transcripts', sid, 'subagents')
        os.symlink(outside, sub)
        self.assertEqual(cursor_cli.read(p, self.root).children, [])
        os.unlink(sub)
        os.makedirs(sub)
        os.symlink(os.path.join(outside, 'forged.jsonl'), os.path.join(sub, 'forged.jsonl'))
        self.assertEqual(cursor_cli.read(p, self.root).children, [])

    def test_a_project_folder_that_escapes_the_root_lists_nothing(self):
        outside = os.path.join(self.tmp, 'outside', 'agent-transcripts', 'a')
        os.makedirs(outside)
        with open(os.path.join(outside, 'a.jsonl'), 'w') as fh:
            fh.write(json.dumps(user('forged')) + '\n')
        os.symlink(os.path.join(self.tmp, 'outside'), os.path.join(self.root, SLUG))
        self.assertEqual(cursor_cli.find_sessions(CWD, self.root), [])

    def test_an_agent_transcripts_directory_that_escapes_the_root_lists_nothing(self):
        outside = os.path.join(self.tmp, 'outside', 'a')
        os.makedirs(outside)
        with open(os.path.join(outside, 'a.jsonl'), 'w') as fh:
            fh.write(json.dumps(user('forged')) + '\n')
        os.makedirs(os.path.join(self.root, SLUG))
        os.symlink(os.path.join(self.tmp, 'outside'), os.path.join(self.root, SLUG, 'agent-transcripts'))
        self.assertEqual(cursor_cli.find_sessions(CWD, self.root), [])

    def test_a_transcript_that_is_a_fifo_is_not_listed_or_opened(self):
        os.makedirs(os.path.join(self.root, SLUG, 'agent-transcripts', 'a'))
        os.mkfifo(os.path.join(self.root, SLUG, 'agent-transcripts', 'a', 'a.jsonl'))
        self.assertEqual(cursor_cli.find_sessions(CWD, self.root), [])
        self.assertFalse(cursor_cli.detect(os.path.join(self.root, SLUG, 'agent-transcripts', 'a', 'a.jsonl')))


if __name__ == '__main__':
    unittest.main()
