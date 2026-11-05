"""Gemini CLI adapter: JSONL and legacy JSON transcripts, $set / $patch / $rewindTo, shell exit codes, sub-agents, guards and hostile input."""
import hashlib
import itertools
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'scripts'))
sys.path.insert(0, HERE)

from lib import adapters  # noqa: E402
from lib.adapters import _io, gemini  # noqa: E402
from lib.adapters.model import (ASSISTANT_TEXT, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT)  # noqa: E402
from test_adapters import CWD, Guards, Harness, Hostile, TmpCase, calls, kinds  # noqa: E402

FIX = os.path.join(HERE, 'fixtures', 'gemini')
ROOT = os.path.join(FIX, 'tmp')
HASH = hashlib.sha256(CWD.encode()).hexdigest()
_ids = itertools.count(1)


def head(sid='sess-1', kind='main', cwd=CWD):
    return {'sessionId': sid, 'projectHash': hashlib.sha256(cwd.encode()).hexdigest(), 'startTime': '2026-11-04T10:00:00.000Z', 'kind': kind}


def user(text, mid=None):
    return {'id': mid or 'u%d' % next(_ids), 'timestamp': '2026-11-04T10:00:01.000Z', 'type': 'user', 'content': text}


def gem(text='', calls_=None, mid=None):
    rec = {'id': mid or 'g%d' % next(_ids), 'timestamp': '2026-11-04T10:00:02.000Z', 'type': 'gemini', 'content': text}
    if calls_ is not None:
        rec['toolCalls'] = calls_
    return rec


def resp(cid, out=None, err=None, name='run_shell_command'):
    return [{'functionResponse': {'id': cid, 'name': name, 'response': {'output': out} if err is None else {'error': err}}}]


def shell(cid, cmd='echo hi', out=None, status='success'):
    return {'id': cid, 'name': 'run_shell_command', 'args': {'command': cmd}, 'status': status, 'timestamp': '2026-11-04T10:00:03.000Z',
            **({'result': resp(cid, out)} if out is not None else {})}


def by_cmd(sess):
    return {t.command: t for t in calls(sess) if t.command}


class Fixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        found = {os.path.basename(p): p for p in gemini.find_sessions(CWD, ROOT)}
        cls.found = found
        cls.main = gemini.read(found['session-2026-11-04T10-00-0f1e2d3c.jsonl'], ROOT)
        cls.legacy = gemini.read(found['session-2026-11-03T09-00-legacy-1.json'], ROOT)

    def test_find_sessions_matches_the_project_hash_in_the_file_and_skips_subagents(self):
        self.assertEqual(sorted(self.found), ['session-2026-11-03T09-00-legacy-1.json', 'session-2026-11-04T10-00-0f1e2d3c.jsonl'])
        self.assertEqual([os.path.basename(p) for p in gemini.find_sessions('/work/other', ROOT)], ['session-2026-11-04T11-00-other001.jsonl'])
        self.assertEqual(gemini.find_sessions('/work/nowhere', ROOT), [])
        self.assertEqual(len(gemini.find_sessions(CWD + '/', ROOT)), 2)
        self.assertEqual(len(gemini.find_sessions('/work/x/../repo', ROOT)), 2)
        self.assertEqual(gemini.find_sessions(CWD, os.path.join(FIX, 'absent')), [])

    def test_user_text_versus_injected(self):
        s = self.main
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['Add a retry to fetch() in client.py', 'Try exponential backoff instead', '/memory show'])
        self.assertEqual([e.text[:16] for e in kinds(s, INJECTED)], ['<session_context', '<hook_context>li'])
        self.assertEqual((s.id, s.kind, s.started_at), ('0f1e2d3c-aaaa-4bbb-8ccc-000000000001', MAIN, '2026-11-04T10:00:00.000Z'))

    def test_shell_output_and_exit_code(self):
        t = by_cmd(self.main)
        self.assertEqual((t['ls src'].exit_code, t['ls src'].is_error, t['ls src'].is_shell), (0, False, True))
        self.assertIn('client.py\nutil.py', t['ls src'].output)
        self.assertEqual((t['pytest -q'].exit_code, t['pytest -q'].is_error), (1, True))          # status stays success; the footer says Exit Code: 1
        self.assertIn('1 failed, 4 passed', t['pytest -q'].output)
        self.assertEqual((t['git diff --stat'].exit_code, t['git diff --stat'].is_error), (0, False))
        self.assertEqual(t['ls src'].args, {'command': 'ls src', 'description': 'ls src'})

    def test_exit_lines_inside_the_output_are_not_the_exit_code(self):
        t = by_cmd(self.main)['cat notes.txt']
        self.assertEqual((t.exit_code, t.is_error), (0, False))           # the body holds "Exit Code: 9 ..." and "Exit Code: 7"
        read_file = [x for x in calls(self.main) if x.name == 'read_file'][0]
        self.assertEqual((read_file.is_shell, read_file.command, read_file.exit_code, read_file.is_error), (False, None, None, False))

    def test_error_cancelled_and_unfinished_calls(self):
        t = by_cmd(self.main)
        self.assertEqual((t['missing-tool'].exit_code, t['missing-tool'].is_error, t['missing-tool'].output), (None, True, 'command not found: missing-tool'))
        self.assertEqual((t['sleep 99'].exit_code, t['sleep 99'].is_error), (None, True))              # cancelled, killed by a signal
        self.assertEqual((t['true'].exit_code, t['true'].is_error), (None, False))                      # moved to the background: no exit yet

    def test_patch_fills_in_a_tool_result_and_replaces_content(self):
        self.assertEqual(by_cmd(self.main)['pytest -q'].output.splitlines()[1], 'Output: 1 failed, 4 passed')
        texts = [e.text for e in kinds(self.main, ASSISTANT_TEXT)]
        self.assertIn('Done: fetch() retries twice (patched).', texts)           # $patch.updates
        self.assertIn('Backoff added: waits 1s, 2s, 4s (patched).', texts)       # $patch with a top-level id

    def test_rewind_drops_the_message_and_everything_after_it(self):
        everything = [e.text for e in self.main.events if e.text]
        self.assertNotIn('Now also log each retry', everything)
        self.assertNotIn('An answer that is rewound away.', everything)

    def test_a_repeated_id_replaces_the_earlier_record_in_place(self):
        texts = [(e.kind, e.text) for e in self.main.events if e.text]
        self.assertNotIn((ASSISTANT_TEXT, 'First draft of the answer.'), texts)
        i = [k for k, e in enumerate(texts) if e[1].startswith('Try exponential')][0]
        self.assertEqual(texts[i + 1][1], 'Backoff added: waits 1s, 2s, 4s (patched).')    # still right after u4

    def test_a_subagent_file_is_a_child_of_its_parent(self):
        self.assertEqual(len(self.main.children), 1)
        c = self.main.children[0]
        self.assertEqual((c.id, c.kind, c.parent_id), ('sub-1', SUBAGENT, self.main.id))
        self.assertEqual([e.kind for e in c.events], [INJECTED, TOOL_CALL, ASSISTANT_TEXT])     # the parent agent's prompt is not the user's
        self.assertEqual(kinds(c, USER_TEXT), [])
        self.assertEqual(calls(c)[0].exit_code, 0)
        self.assertFalse([p for p in self.found if 'sub-1' in p])

    def test_a_legacy_json_transcript(self):
        s = self.legacy
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['Run the linter'])
        t = calls(s)[0]
        self.assertEqual((t.command, t.exit_code, t.is_error), ('ruff check .', 1, True))
        self.assertEqual(kinds(s, ASSISTANT_TEXT)[0].text, 'Linter finished with one error.')

    def test_locations_point_at_the_transcript_line(self):
        path, line = kinds(self.main, USER_TEXT)[0].loc
        with open(path, encoding='utf-8') as fh:
            self.assertIn('Add a retry to fetch()', fh.read().splitlines()[line - 1])

    def test_the_vendored_v040_capture(self):
        s = gemini.read(os.path.join(FIX, 'vendored', 'jsonl_v040.jsonl'), FIX)
        self.assertEqual([(e.kind, e.text) for e in s.events if e.tool is None], [(USER_TEXT, 'Say hello and list files.'), (ASSISTANT_TEXT, 'Hello! I listed the files.')])
        t = calls(s)[0]
        self.assertEqual((t.call_id, t.command, t.exit_code, t.is_error, t.output), ('run_shell_command_stage0', 'ls -F', 0, False, 'Output: AgentSessions/\nREADME.md\nProcess Group PGID: 12345'))
        self.assertEqual((s.id, s.kind), ('gemini_stage0_jsonl', MAIN))
        legacy = gemini.read(os.path.join(FIX, 'vendored', 'small.json'), FIX)
        self.assertEqual([(e.kind, e.text) for e in legacy.events], [(USER_TEXT, 'Hello'), (ASSISTANT_TEXT, 'Hi!')])

    def test_detect_and_registry(self):
        p = os.path.join(FIX, 'vendored', 'jsonl_v040.jsonl')
        self.assertTrue(gemini.detect(p))
        self.assertEqual(adapters.detect_format(p), 'gemini')
        self.assertTrue(gemini.detect(os.path.join(FIX, 'vendored', 'small.json')))
        self.assertIs(adapters.get('gemini'), gemini)
        self.assertEqual(gemini.project_hash(CWD), HASH)


class ShellExit(unittest.TestCase):
    def test_footer_forms(self):
        wrapped = lambda t: '<untrusted_context>\n%s\n</untrusted_context>' % t       # noqa: E731
        for text, status, want in (
                ('Output: ok\nProcess Group PGID: 5', 'success', 0),
                ('Output: ok', 'success', 0),
                ('Output: x\nExit Code: 2\nProcess Group PGID: 5', 'success', 2),
                ('Output: x\nError: boom\nExit Code: -1\nSignal: SIGKILL\nBackground PIDs: 9, 10\nProcess Group PGID: 5', 'success', -1),
                (wrapped('Output: x\nExit Code: 3'), 'success', 3),
                (wrapped('Output: x\nProcess Group PGID: 5'), 'success', 0),
                ('Output: x\nExit Code: 3 is the code\nmore', 'success', 0),
                ('Output: x\nSignal: SIGTERM\nProcess Group PGID: 5', 'success', None),
                ('Output: x\nExit Code: ' + '9' * 5000, 'success', None), ('Output: x\nExit Code: ' + '9' * 18, 'success', 10 ** 18 - 1),
                ('Output: x', 'error', None), ('Output: x', 'cancelled', None), ('Output: x', None, None),
                ('Command is running in background. PID: 5', 'success', None), ('', 'success', None), (None, 'success', None)):
            self.assertEqual(gemini.shell_exit_code(text, status), want, (text, status))


class Records(TmpCase):
    def write_session(self, lines, name='session-2026-11-04T10-00-aaaa.jsonl', sub='tmp1/chats'):
        return self.write('%s/%s' % (sub, name), lines)

    def texts(self, path):
        return [(e.kind, e.text) for e in gemini.read(path, self.root).events]

    def test_rewind_to_an_unknown_id_clears_every_message(self):
        p = self.write_session([head(), user('a', 'u1'), gem('b', mid='g1'), {'$rewindTo': 'nope'}, user('c', 'u2')])
        self.assertEqual(self.texts(p), [(USER_TEXT, 'c')])

    def test_set_messages_replaces_the_conversation(self):
        p = self.write_session([head(), user('old', 'u1'), {'$set': {'messages': [user('new', 'n1'), gem('answer', mid='n2')], 'summary': 's'}}])
        self.assertEqual(self.texts(p), [(USER_TEXT, 'new'), (ASSISTANT_TEXT, 'answer')])

    def test_patch_remove_and_reorder(self):
        p = self.write_session([head(), user('one', 'a'), user('two', 'b'), user('three', 'c'), {'$patch': {'removeIds': ['b', 7]}},
                                {'$patch': {'orderIds': ['c', 'zz', 'a']}}])
        self.assertEqual(self.texts(p), [(USER_TEXT, 'three'), (USER_TEXT, 'one')])

    def test_patch_of_a_missing_message_or_a_non_gemini_message_changes_nothing(self):
        p = self.write_session([head(), user('keep', 'u1'), {'$patch': {'id': 'ghost', 'content': 'x'}},
                                {'$patch': {'id': 'u1', 'toolCalls': [{'id': 't', 'result': 'x'}]}}, {'$patch': 'text'}, {'$patch': {'id': 5}}])
        self.assertEqual(self.texts(p), [(USER_TEXT, 'keep')])

    def test_patch_result_applies_only_to_the_named_call(self):
        p = self.write_session([head(), gem(calls_=[shell('a', 'one'), shell('b', 'two')], mid='g1'),
                                {'$patch': {'id': 'g1', 'toolCalls': [{'id': 'b', 'result': resp('b', 'Output: two\nExit Code: 4')}, {'id': 'zz', 'result': 'x'}, 'bad']}}])
        t = by_cmd(gemini.read(p, self.root))
        self.assertEqual((t['one'].output, t['one'].exit_code), (None, None))
        self.assertEqual((t['two'].exit_code, t['two'].is_error), (4, True))

    def test_a_repeated_id_keeps_the_first_position_and_takes_the_last_content(self):
        p = self.write_session([head(), user('a', 'ua'), gem('first', mid='g'), user('b', 'ub'), gem('second', mid='g')])
        self.assertEqual(self.texts(p), [(USER_TEXT, 'a'), (ASSISTANT_TEXT, 'second'), (USER_TEXT, 'b')])

    def test_a_metadata_set_does_not_make_a_message(self):
        p = self.write_session([head(), {'$set': {'lastUpdated': 'x', 'summary': 'a chat'}}, {'$set': 'bad'}, user('hi')])
        s = gemini.read(p, self.root)
        self.assertEqual([e.text for e in s.events], ['hi'])

    def test_a_jsonl_beats_the_legacy_json_of_the_same_session(self):
        a = self.write_session([head('same'), user('new format')])
        legacy = dict(head('same'), messages=[user('old format')])
        self.write_session([json.dumps(legacy)], 'session-2026-11-04T10-00-aaaa.json')
        other = self.write_session([json.dumps(dict(head('only-legacy'), messages=[]))], 'session-2026-11-03T10-00-bbbb.json')
        self.assertEqual(sorted(gemini.find_sessions(CWD, self.root)), sorted([a, other]))

    def test_find_sessions_matches_a_symlinked_cwd_by_its_real_path_or_as_given(self):
        real = os.path.join(self.tmp, 'proj')
        os.makedirs(real)
        link = os.path.join(self.tmp, 'link')
        os.symlink(real, link)
        a = self.write_session([head('r', cwd=os.path.realpath(real)), user('x')], 'session-2026-11-04T10-00-r.jsonl')
        b = self.write_session([head('l', cwd=link), user('x')], 'session-2026-11-04T10-00-l.jsonl')
        self.assertEqual(sorted(gemini.find_sessions(link, self.root)), sorted([a, b]))

    def test_the_project_directory_name_does_not_matter(self):
        a = self.write_session([head(), user('x')], sub='short-id/chats')
        b = self.write_session([head('b'), user('x')], sub='%s/chats' % HASH)
        self.write_session([head('c'), user('x')], sub='short-id/not-chats')
        self.assertEqual(sorted(gemini.find_sessions(CWD, self.root)), sorted([a, b]))

    def test_subagents_of_a_subagent_and_a_sanitized_parent_directory(self):
        sid = 'we/ird id'
        p = self.write_session([head(sid), user('top')])
        self.write('tmp1/chats/we_ird_id/sub-a.jsonl', [head('sub-a', 'subagent'), user('prompt a')])
        self.write('tmp1/chats/sub-a/sub-b.jsonl', [head('sub-b', 'subagent'), user('prompt b')])
        self.write('tmp1/chats/we_ird_id/not-a-subagent.jsonl', [head('plain', 'main'), user('x')])
        s = gemini.read(p, self.root)
        self.assertEqual([(c.id, c.parent_id, [g.id for g in c.children]) for c in s.children], [('sub-a', sid, ['sub-b'])])
        self.assertEqual(s.children[0].children[0].parent_id, 'sub-a')

    def test_a_subagent_that_names_its_parent_as_its_own_id_does_not_loop(self):
        p = self.write_session([head('x'), user('top')])
        self.write('tmp1/chats/x/x.jsonl', [head('x', 'subagent'), user('self')])
        self.assertEqual(gemini.read(p, self.root).children[0].children, [])

    def test_a_subagent_file_that_sits_among_the_sessions_is_not_listed(self):
        self.write_session([head('sub', 'subagent'), user('x')], 'session-2026-11-04T10-00-sub.jsonl')
        self.assertEqual(gemini.find_sessions(CWD, self.root), [])

    def test_info_error_warning_messages_and_odd_content_make_no_events(self):
        recs = [head(), {'id': 'i', 'type': 'info', 'content': 'Model changed'}, {'id': 'e', 'type': 'error', 'content': 'boom'}, {'id': 'w', 'type': 'warning', 'content': 'hm'},
                {'id': 'u1', 'type': 'user', 'content': 7}, {'id': 'u2', 'type': 'user', 'content': [1, None, {'inlineData': {}}]},
                {'id': 'u3', 'type': 'user', 'content': [{'functionResponse': {'response': {'output': 'tool answer'}}}]},
                {'id': 'g', 'type': 'gemini', 'content': None, 'toolCalls': 'nope'}, {'id': 'g2', 'type': 'gemini', 'content': {'text': 'x'}, 'toolCalls': [3, None, {}]}]
        s = gemini.read(self.write_session(recs), self.root)
        self.assertEqual([(e.kind, e.tool and (e.tool.name, e.tool.call_id, e.tool.output, e.tool.exit_code)) for e in s.events], [(TOOL_CALL, (None, None, None, None))])

    def test_odd_results(self):
        results = [None, 5, 'plain text', [], [1, 'a string part'], [{'functionResponse': None}], [{'functionResponse': {'response': {'output': 3}}}],
                   [{'functionResponse': {'response': {'output': 'a'}}}, {'functionResponse': {'response': {'error': 'b'}}}], {'functionResponse': {'response': {'output': 'single'}}}]
        calls_ = [dict(shell('c%d' % i), result=r) for i, r in enumerate(results)]
        out = [t.output for t in calls(gemini.read(self.write_session([head(), gem(calls_=calls_)]), self.root))]
        self.assertEqual(out, [None, None, 'plain text', None, 'a string part', None, None, 'a\nb', 'single'])


class GeminiHostile(Hostile, TmpCase):
    H = Harness(gemini, 'tmp1/chats/session-%s.jsonl', head, user, lambda cid: gem(calls_=[shell(cid, 'echo %s' % cid)]), lambda cid, text: None)

    # the generic tests below assume one record per output; Gemini keeps a call and its result in one record
    def test_missing_fields_become_none(self):
        p = self.make([{'sessionId': 5}, {'id': 'a', 'type': 'gemini', 'toolCalls': [{}, 7, {'name': 'run_shell_command'}, {'id': 'x', 'name': 'run_shell_command', 'args': 3}]}, {'id': 'b'}])
        s = self.read(p)
        self.assertEqual((s.id, s.cwd, s.started_at), (None, None, None))
        for t in calls(s):
            self.assertEqual((t.output, t.exit_code, t.is_error), (None, None, False))

    def test_a_duplicated_call_id_pairs_in_order_and_a_repeated_output_is_ignored(self):
        p = self.make([self.H.header(), gem(calls_=[shell('d', 'one'), shell('d', 'two')], mid='g1'),
                       {'$patch': {'id': 'g1', 'toolCalls': [{'id': 'd', 'result': resp('d', 'first')}, {'id': 'd', 'result': resp('d', 'second')}]}}])
        self.assertEqual([t.output for t in calls(self.read(p))], ['second', None])        # a patch names a call by id: the first one with that id takes it, later patches replace

    def test_an_output_with_no_call_makes_no_event(self):
        p = self.make([self.H.header(), {'$patch': {'id': 'ghost', 'toolCalls': [{'id': 'x', 'result': resp('x', 'orphan')}]}}, gem(calls_=[shell('a', 'echo a', 'Output: a')])])
        self.assertEqual([(t.call_id, t.output) for t in calls(self.read(p))], [('a', 'Output: a')])

    def test_a_call_with_no_output_keeps_none(self):
        p = self.make([self.H.header(), gem(calls_=[shell('a', 'echo a')])])
        t = calls(self.read(p))[0]
        self.assertEqual((t.output, t.exit_code, t.is_error, t.command), (None, None, False, 'echo a'))

    def test_a_legacy_json_that_is_too_big_or_not_json_reads_as_empty(self):
        p = self.write('tmp1/chats/session-big.json', [json.dumps(dict(head(), messages=[user('x')]))])
        old = gemini.MAX_LEGACY
        gemini.MAX_LEGACY = 10
        try:
            self.assertEqual((gemini.read(p, self.root).events, gemini.detect(p), gemini.find_sessions(CWD, self.root)), ([], False, []))
        finally:
            gemini.MAX_LEGACY = old
        bad = self.write('tmp1/chats/session-bad.json', ['{"sessionId": "x", "projectHash": '])
        self.assertEqual((gemini.read(bad, self.root).events, gemini.detect(bad)), ([], False))
        self.assertEqual([e.text for e in gemini.read(p, self.root).events], ['x'])


class GeminiGuards(Guards, TmpCase):
    H = Harness(gemini, 'tmp1/chats/session-%s.jsonl', head, user, None, None)
    H.default_parts = ('.gemini', 'tmp')

    def test_the_default_root_is_the_harness_directory_and_no_environment_variable_moves_it(self):
        saved = {k: os.environ.get(k) for k in ('GEMINI_CLI_HOME', 'GEMINI_HOME', 'HOME')}
        try:
            os.environ['GEMINI_CLI_HOME'] = os.environ['GEMINI_HOME'] = self.tmp
            self.assertEqual(gemini.default_root(), os.path.join(os.path.expanduser('~'), '.gemini', 'tmp'))
            outside = os.path.join(self.tmp, 'forged.jsonl')
            with open(outside, 'w') as fh:
                fh.write(json.dumps(head()) + '\n')
            with self.assertRaises(_io.RootError):
                gemini.read(outside)                  # no root argument: the default root applies
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_a_subagent_directory_that_escapes_the_root_is_not_followed(self):
        p = self.write('tmp1/chats/session-a.jsonl', [head('a'), user('top')])
        outside = os.path.join(self.tmp, 'outside')
        os.makedirs(outside)
        with open(os.path.join(outside, 'forged.jsonl'), 'w') as fh:
            fh.write(json.dumps(head('forged', 'subagent')) + '\n' + json.dumps(user('I wrote this')) + '\n')
        os.symlink(outside, os.path.join(self.root, 'tmp1', 'chats', 'a'))
        self.assertEqual(gemini.read(p, self.root).children, [])
        os.unlink(os.path.join(self.root, 'tmp1', 'chats', 'a'))
        os.makedirs(os.path.join(self.root, 'tmp1', 'chats', 'a'))
        os.symlink(os.path.join(outside, 'forged.jsonl'), os.path.join(self.root, 'tmp1', 'chats', 'a', 'forged.jsonl'))
        self.assertEqual(gemini.read(p, self.root).children, [])

    def test_a_chats_directory_that_escapes_the_root_lists_nothing(self):
        outside = os.path.join(self.tmp, 'outside', 'chats')
        os.makedirs(outside)
        with open(os.path.join(outside, 'session-a.jsonl'), 'w') as fh:
            fh.write(json.dumps(head('forged')) + '\n')
        os.makedirs(os.path.join(self.root, 'tmp1'))
        os.symlink(outside, os.path.join(self.root, 'tmp1', 'chats'))
        self.assertEqual(gemini.find_sessions(CWD, self.root), [])


if __name__ == '__main__':
    unittest.main()
