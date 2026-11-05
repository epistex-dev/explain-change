"""Transcript adapters: the Copilot CLI and Codex readers, their guards and their hostile-input handling."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'skills', 'explain-change', 'scripts'))

from lib import adapters  # noqa: E402
from lib.adapters import _io, codex, copilot  # noqa: E402
from lib.adapters.model import (ASSISTANT_TEXT, COMPACTION, INJECTED, MAIN, SUBAGENT, TOOL_CALL, USER_TEXT)  # noqa: E402

FIX = os.path.join(HERE, 'fixtures')
CP_ROOT = os.path.join(FIX, 'copilot')
CX_ROOT = os.path.join(FIX, 'codex', 'sessions')
CWD = '/work/repo'


def kinds(sess, *want):
    return [e for e in sess.events if e.kind in want]


def calls(sess):
    return [e.tool for e in sess.events if e.kind == TOOL_CALL]


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='adapters-'))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.root = os.path.join(self.tmp, 'root')
        os.makedirs(self.root)

    def write(self, rel, lines, mode='w'):
        p = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, mode) as fh:
            for ln in lines:
                if isinstance(ln, (dict, list)):
                    ln = json.dumps(ln)
                fh.write(ln + b'\n' if 'b' in mode else ln + '\n')
        return p


# ---------------------------------------------------------------- Copilot CLI

def cp(typ, data, ts='2026-11-04T10:00:00.000Z', **top):
    return dict(type=typ, data=data, timestamp=ts, **top)


def cp_start(cwd=CWD, sid='sess-1'):
    return cp('session.start', {'sessionId': sid, 'startTime': '2026-11-04T09:59:00.000Z', 'copilotVersion': '1.0.105', 'context': {'cwd': cwd}})


def cp_user(text, **extra):
    return cp('user.message', dict({'content': text, 'transformedContent': text}, **extra))


def cp_call(cid, name='bash', args=None, content=None):
    return cp('assistant.message', {'content': content or '', 'toolRequests': [{'toolCallId': cid, 'name': name, 'arguments': args if args is not None else {'command': 'true'}}]})


def cp_done(cid, **data):
    return cp('tool.execution_complete', dict({'toolCallId': cid, 'success': True}, **data))


class CopilotFixtures(unittest.TestCase):
    def read(self, name):
        return copilot.read(os.path.join(CP_ROOT, name), CP_ROOT)

    def test_user_shell_exit_zero_and_one(self):
        s = self.read('user-shell.jsonl')
        zero, one = calls(s)
        self.assertEqual((zero.command, zero.exit_code, zero.is_error, zero.by_user, zero.output), ('echo marker-77', 0, False, True, 'marker-77'))
        self.assertEqual((one.command, one.exit_code, one.is_error), ('ls /no-such-dir', 1, True))
        self.assertIn('No such file', one.output)
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['Reply with the word done'])
        self.assertEqual([e.text for e in kinds(s, ASSISTANT_TEXT)], ['done'])
        self.assertEqual((s.id, s.cwd, s.kind), ('3fe12164-aeb4-4d8a-920e-765c98e98609', '/private/tmp/copilot-v1', MAIN))

    def test_tool_exercise_counts_match_the_specstory_expectations(self):
        s = self.read('tool-exercise.jsonl')
        self.assertEqual(len(kinds(s, USER_TEXT)), 8)                       # 8 typed prompts (the 9th "user turn" is the `!` command)
        self.assertEqual(len([t for t in calls(s) if t.by_user]), 1)
        self.assertEqual(len([e for e in kinds(s, INJECTED)]), 0)           # the sub-agent prompts live in the children
        failed = [t for t in calls(s) if t.is_error]
        self.assertEqual(len([t for t in failed if t.exit_code is None]), 4)    # the 4 success:false calls
        self.assertEqual([(t.command, t.exit_code) for t in failed if t.exit_code is not None], [('ls /nonexistent-dir', 1)])

    def test_success_true_with_exit_one_is_an_error(self):
        s = self.read('tool-exercise.jsonl')
        t = [t for t in calls(s) if t.command == 'ls /nonexistent-dir'][0]
        self.assertEqual((t.exit_code, t.is_error), (1, True))
        ok = [t for t in calls(s) if t.command and t.command.startswith('cd /private/tmp/copilot-v3 && wc')][0]
        self.assertEqual((ok.exit_code, ok.is_error), (0, False))

    def test_subagents_are_child_sessions_linked_to_their_task_call(self):
        s = self.read('tool-exercise.jsonl')
        self.assertEqual(len(s.children), 3)
        task_ids = {t.call_id for t in calls(s) if t.name == 'task'}
        self.assertEqual(sum(c.parent_call_id in task_ids for c in s.children), 2)   # the third was started by a workflow
        for c in s.children:
            self.assertEqual((c.kind, c.parent_id, c.cwd), (SUBAGENT, s.id, s.cwd))
            self.assertTrue(c.parent_call_id)
            self.assertTrue(c.events)
            self.assertEqual(kinds(c, USER_TEXT), [])             # the agent's prompt is not the user's
            self.assertEqual(kinds(c, INJECTED)[0].kind, INJECTED)
        counter = [c for c in s.children if any(t.command and 'wc -l' in t.command for t in calls(c))][0]
        self.assertEqual([t.exit_code for t in calls(counter)], [0])
        self.assertNotIn('27', [e.text for e in kinds(s, ASSISTANT_TEXT)])

    def test_resume_appends_to_the_same_session(self):
        s = self.read('tool-exercise.jsonl')
        texts = [e.text for e in kinds(s, USER_TEXT)]
        self.assertEqual(texts[-2:], ["k, it's on", 'Reply with the word finished'])

    def test_locations_point_at_the_transcript_line(self):
        s = self.read('user-shell.jsonl')
        path, line = kinds(s, USER_TEXT)[0].loc
        with open(path, encoding='utf-8') as fh:
            self.assertIn('Reply with the word done', fh.read().splitlines()[line - 1])


class CopilotClassification(TmpCase):
    def run_sources(self, cases):
        out = {}
        for i, (label, extra, text) in enumerate(cases):
            p = self.write('s%d/events.jsonl' % i, [cp_start(sid='s%d' % i), cp_user(text, **extra)])
            ev = copilot.read(p, self.root).events
            out[label] = ev[0].kind if ev else None
        return out

    def test_only_typed_prompts_are_user_text(self):
        got = self.run_sources([
            ('empty', {}, 'typed'), ('user', {'source': 'user'}, 'typed'),
            ('agent', {'source': 'agent-abc'}, 'sub-agent prompt'), ('autopilot', {'source': 'autopilot'}, 'nudge'),
            ('system', {'source': 'system'}, 'sys'), ('skill', {'source': 'skill-foo'}, 'skill body'),
            ('instr', {'source': 'instruction-discovery'}, 'AGENTS'), ('new', {'source': 'something-new'}, 'who knows'),
            ('notice', {}, '<system_notification>\nWorkflow done\n</system_notification>'),
            ('agent-notice', {'source': 'agent-workspace-1'}, '<system_notification>x</system_notification>'),
            ('starts-with-tag', {}, '<system_notification> is a tag I want you to explain'),
        ])
        self.assertEqual(got, {
            'empty': USER_TEXT, 'user': USER_TEXT, 'agent': INJECTED, 'autopilot': INJECTED, 'system': INJECTED,
            'skill': INJECTED, 'instr': INJECTED, 'new': INJECTED, 'notice': INJECTED, 'agent-notice': INJECTED,
            'starts-with-tag': USER_TEXT})

    def test_a_user_message_inside_a_subagent_is_not_user_text(self):
        p = self.write('sub/events.jsonl', [cp_start(), cp('subagent.started', {'toolCallId': 't1'}, agentId='ag1'),
                                            cp('user.message', {'content': 'plain looking text', 'transformedContent': 'plain looking text'}, agentId='ag1')])
        s = copilot.read(p, self.root)
        self.assertEqual(s.events, [])
        self.assertEqual([(e.kind, e.text) for e in s.children[0].events], [(INJECTED, 'plain looking text')])

    def test_message_from_another_session_is_not_user_text(self):
        env = '<cross_session_message>\nfrom_session_id: abc\nhello\n</cross_session_message>'
        p = self.write('a/events.jsonl', [cp_start(), cp('user.message', {'content': 'hello', 'transformedContent': env + '\nhello'})])
        self.assertEqual([e.kind for e in copilot.read(p, self.root).events], [INJECTED])
        quoted = cp('user.message', {'content': 'what is <cross_session_message>?', 'transformedContent': 'what is <cross_session_message>?'})
        p = self.write('b/events.jsonl', [cp_start(), quoted])
        self.assertEqual([e.kind for e in copilot.read(p, self.root).events], [USER_TEXT])


class CopilotExitCodes(TmpCase):
    def one(self, *recs):
        p = self.write('x/events.jsonl', [cp_start(), *recs])
        return calls(copilot.read(p, self.root))[0]

    def test_success_true_does_not_hide_a_failed_command(self):
        t = self.one(cp_call('c1'), cp_done('c1', shellExecution={'exitCode': 1}, result={'content': 'boom\n<shellId: 0 completed with exit code 1>'}))
        self.assertEqual((t.exit_code, t.is_error), (1, True))

    def test_exit_code_from_the_trailing_shell_line_when_no_structured_field(self):
        t = self.one(cp_call('c1'), cp_done('c1', result={'content': 'x\n<shellId: demo completed with exit code 2>'}))
        self.assertEqual((t.exit_code, t.is_error), (2, True))

    def test_exit_zero_is_not_an_error(self):
        t = self.one(cp_call('c1'), cp_done('c1', shellExecution={'exitCode': 0}, result={'content': 'ok'}))
        self.assertEqual((t.exit_code, t.is_error, t.output), (0, False, 'ok'))

    def test_failed_tool_without_exit_code_is_an_error_with_the_message(self):
        t = self.one(cp_call('c1', 'view', {'path': '/x'}), cp_done('c1', success=False, error={'message': 'Path does not exist', 'code': 'failure'}))
        self.assertEqual((t.exit_code, t.is_error, t.output, t.is_shell), (None, True, 'Path does not exist', False))

    def test_a_file_that_mentions_an_exit_line_is_not_a_shell_exit(self):
        t = self.one(cp_call('c1', 'view', {'path': '/x'}), cp_done('c1', result={'content': '<shellId: 1 completed with exit code 9>'}))
        self.assertEqual((t.exit_code, t.is_error), (None, False))

    def test_a_number_over_18_digits_is_not_an_exit_code(self):
        for digits, want in (('9' * 18, 10 ** 18 - 1), ('9' * 19, None), ('9' * 5000, None)):
            t = self.one(cp_call('c1'), cp_done('c1', result={'content': 'x\n<shellId: demo completed with exit code %s>' % digits}))
            self.assertEqual(t.exit_code, want)

    def test_user_bang_command_failure_shape(self):
        s = copilot.read(self.write('u/events.jsonl', [
            cp_start(), cp('tool.user_requested', {'toolCallId': 'u1', 'toolName': 'local_shell', 'arguments': {'command': 'false'}}),
            cp_done('u1', success=False, shellExecution={'exitCode': 1}, error={'message': ''})]), self.root)
        t = calls(s)[0]
        self.assertEqual((t.command, t.exit_code, t.is_error, t.by_user), ('false', 1, True, True))

    def test_task_complete_is_the_closing_answer(self):
        p = self.write('t/events.jsonl', [cp_start(), cp_call('c1', 'task_complete', {'summary': 'All done.'})])
        s = copilot.read(p, self.root)
        self.assertEqual([(e.kind, e.text) for e in s.events], [(ASSISTANT_TEXT, 'All done.')])

    def test_apply_patch_keeps_the_raw_patch(self):
        t = self.one(cp_call('c1', 'apply_patch', '*** Begin Patch\n*** End Patch'), cp_done('c1', result={'content': 'ok'}))
        self.assertEqual((t.args, t.command, t.is_shell), ('*** Begin Patch\n*** End Patch', None, False))


class CopilotFind(TmpCase):
    def test_find_sessions_matches_by_recorded_cwd(self):
        a = self.write('a/events.jsonl', [cp_start(CWD, 'a'), cp_user('hi')])
        self.write('b/events.jsonl', [cp_start('/work/other', 'b'), cp_user('hi')])
        self.write('c/events.jsonl', ['not json at all'])
        self.write('d/other.jsonl', [cp_start(CWD, 'd')])
        self.assertEqual(copilot.find_sessions(CWD, self.root), [a])
        self.assertEqual(copilot.find_sessions('/work/nowhere', self.root), [])
        self.assertEqual(copilot.find_sessions(CWD, os.path.join(self.tmp, 'missing')), [])

    def test_a_trailing_slash_or_dotdot_still_matches(self):
        a = self.write('a/events.jsonl', [cp_start(CWD, 'a')])
        self.assertEqual(copilot.find_sessions(CWD + '/', self.root), [a])
        self.assertEqual(copilot.find_sessions('/work/x/../repo', self.root), [a])


# ---------------------------------------------------------------- Codex

def cx(typ, payload, ts='2026-11-04T10:00:00.000Z'):
    return {'timestamp': ts, 'type': typ, 'payload': payload}


def cx_meta(sid='019a0000-0001-7000-8000-000000000001', cwd=CWD, **kw):
    return cx('session_meta', dict({'id': sid, 'timestamp': '2026-11-04T10:00:00.000Z', 'cwd': cwd, 'source': 'cli'}, **kw))


def cx_user(text):
    return cx('event_msg', {'type': 'user_message', 'message': text})


def cx_call(cid, name='exec_command', args=None):
    return cx('response_item', {'type': 'function_call', 'name': name, 'arguments': json.dumps(args if args is not None else {'cmd': 'true'}), 'call_id': cid})


def cx_out(cid, output, typ='function_call_output'):
    return cx('response_item', {'type': typ, 'call_id': cid, 'output': output})


class CodexFixtures(unittest.TestCase):
    def sessions(self):
        paths = codex.find_sessions(CWD, CX_ROOT)
        return {os.path.basename(p)[-13:-6]: codex.read(p, CX_ROOT) for p in paths}

    def test_find_sessions_returns_main_and_fork_but_not_the_subagent(self):
        self.assertEqual(sorted(self.sessions()), ['0000001', '0000003'])

    def test_user_text_versus_injected(self):
        s = self.sessions()['0000001']
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['Add a retry to fetch() in client.py', 'Now also log each retry'])
        self.assertTrue(kinds(s, INJECTED)[0].text.startswith('<environment_context>'))
        self.assertEqual([e.text for e in kinds(s, ASSISTANT_TEXT)][-1], 'Done: each retry logs a warning.')

    def test_compacted_record_is_never_user_text(self):
        s = self.sessions()['0000001']
        comp = kinds(s, COMPACTION)
        self.assertEqual(len(comp), 1)
        self.assertTrue(comp[0].text.startswith('Summary:'))
        self.assertNotIn('Add a retry to fetch() in client.py', [e.text for e in kinds(s, USER_TEXT)][1:])

    def test_each_tool_command_and_output_shape(self):
        t = {x.call_id: x for x in calls(self.sessions()['0000001'])}
        self.assertEqual(t['call_pytest'].command, 'pytest -q')                # exec_command: cmd
        self.assertEqual(t['call_ls'].command, 'ls src')                       # shell_command: command
        self.assertEqual(t['call_git'].command, 'git status --short')          # shell: ["bash","-lc",...] unwrapped
        self.assertEqual((t['call_patch'].command, t['call_patch'].is_shell), (None, False))
        self.assertTrue(t['call_patch'].args.startswith('*** Begin Patch'))    # custom_tool_call: raw input
        self.assertEqual(t['call_ls'].output, 'client.py\nutil.py\n')          # JSON {"output", "metadata"}
        self.assertTrue(t['call_pytest'].output.startswith('Chunk ID'))        # plain string
        self.assertEqual(t['call_img'].output, 'image attached\n[image]')      # [{text}] items

    def test_exit_codes_and_is_error(self):
        t = {x.call_id: x for x in calls(self.sessions()['0000001'])}
        self.assertEqual((t['call_pytest'].exit_code, t['call_pytest'].is_error), (1, True))   # "Process exited with code 1"
        self.assertEqual((t['call_git'].exit_code, t['call_git'].is_error), (0, False))        # "Exit code: 0"
        self.assertEqual((t['call_ls'].exit_code, t['call_ls'].is_error), (0, False))          # metadata.exit_code
        self.assertEqual((t['call_patch'].exit_code, t['call_patch'].is_error), (0, False))
        self.assertEqual((t['call_img'].exit_code, t['call_img'].is_error), (None, False))
        self.assertEqual((t['call_spawn'].exit_code, t['call_spawn'].is_error), (None, False))

    def test_subagent_is_a_child_of_its_parent(self):
        s = self.sessions()['0000001']
        self.assertEqual(len(s.children), 1)
        c = s.children[0]
        self.assertEqual((c.kind, c.parent_id, c.id[-4:]), (SUBAGENT, s.id, '0002'))
        self.assertEqual(kinds(c, USER_TEXT), [])
        self.assertEqual([e.kind for e in c.events], [INJECTED, TOOL_CALL, ASSISTANT_TEXT])
        self.assertEqual(calls(c)[0].exit_code, 0)

    def test_user_fork_does_not_repeat_the_parents_turns(self):
        sessions = self.sessions()
        fork = sessions['0000003']
        self.assertEqual((fork.kind, fork.parent_id[-4:]), (MAIN, '0001'))
        self.assertEqual([e.text for e in kinds(fork, USER_TEXT)], ['Try exponential backoff instead'])
        self.assertEqual(calls(fork), [])
        everything = [e.text for s in sessions.values() for e in kinds(s, USER_TEXT)]
        self.assertEqual(everything.count('Add a retry to fetch() in client.py'), 1)

    def test_the_subagents_replayed_history_is_dropped_too(self):
        c = self.sessions()['0000001'].children[0]
        self.assertNotIn('pytest -q', [t.command for t in calls(c)])
        self.assertEqual([t.command for t in calls(c)], ['git diff -- client.py'])


class CodexOutputs(TmpCase):
    def one(self, *recs, first=None):
        p = self.write('2026/11/04/rollout-2026-11-04T10-00-00-x.jsonl', [first or cx_meta(), *recs])
        return calls(codex.read(p, self.root))[0]

    def test_header_exit_code_forms(self):
        t = self.one(cx_call('c'), cx_out('c', 'Wall time: 1 seconds\nProcess exited with code 3\nOutput:\nhi'))
        self.assertEqual((t.exit_code, t.is_error), (3, True))
        t = self.one(cx_call('c'), cx_out('c', 'Exit code: 2\nWall time: 1 seconds\nOutput:\nhi'))
        self.assertEqual((t.exit_code, t.is_error), (2, True))

    def test_a_number_over_18_digits_is_not_an_exit_code(self):
        for line in ('Process exited with code %s', 'Exit code: %s'):
            for digits, want in (('9' * 18, 10 ** 18 - 1), ('9' * 19, None), ('9' * 5000, None)):
                t = self.one(cx_call('c'), cx_out('c', 'Wall time: 1 seconds\n%s\nOutput:\nhi' % (line % digits)))
                self.assertEqual(t.exit_code, want)

    def test_exit_text_in_the_body_is_not_the_exit_code(self):
        t = self.one(cx_call('c'), cx_out('c', 'Wall time: 1 seconds\nProcess exited with code 0\nOutput:\nProcess exited with code 7\nExit code: 9'))
        self.assertEqual((t.exit_code, t.is_error), (0, False))
        t = self.one(cx_call('c'), cx_out('c', 'Wall time: 1 seconds\nProcess running with session ID 4\nOutput:\nProcess exited with code 7'))
        self.assertEqual((t.exit_code, t.is_error), (None, False))

    def test_exec_command_end_wins_whenever_it_arrives(self):
        end = cx('event_msg', {'type': 'exec_command_end', 'call_id': 'c', 'exit_code': 5})
        before = self.one(cx_call('c'), end, cx_out('c', 'plain output'))
        after = self.one(cx_call('c'), cx_out('c', 'plain output'), end)
        self.assertEqual([(t.exit_code, t.is_error) for t in (before, after)], [(5, True), (5, True)])

    def test_json_metadata_exit_code(self):
        t = self.one(cx_call('c'), cx_out('c', json.dumps({'output': 'bad', 'metadata': {'exit_code': 127}})))
        self.assertEqual((t.output, t.exit_code, t.is_error), ('bad', 127, True))

    def test_running_process_has_no_exit_code(self):
        t = self.one(cx_call('c'), cx_out('c', 'Wall time: 0.1 seconds\nProcess running with session ID 4\nOutput:\n'))
        self.assertEqual((t.exit_code, t.is_error), (None, False))

    def test_custom_tool_call_and_its_output(self):
        t = self.one(cx('response_item', {'type': 'custom_tool_call', 'name': 'apply_patch', 'input': 'PATCH', 'call_id': 'p'}),
                     cx_out('p', 'done', 'custom_tool_call_output'))
        self.assertEqual((t.name, t.args, t.output, t.is_shell), ('apply_patch', 'PATCH', 'done', False))

    def test_command_forms(self):
        for args, want in (({'cmd': 'a b'}, 'a b'), ({'command': 'c d'}, 'c d'), ({'command': ['bash', '-lc', 'x && y']}, 'x && y'),
                           ({'command': ['ls', '-la', 'my dir']}, "ls -la 'my dir'"), ({'cmd': 5}, None), ({}, None)):
            self.assertEqual(self.one(cx_call('c', 'shell_command', args)).command, want)
        self.assertEqual(self.one(cx_call('c', 'update_plan', {'cmd': 'nope'})).command, None)

    def test_item_completed_user_message(self):
        item = cx('event_msg', {'type': 'item_completed', 'item': {'type': 'UserMessage', 'content': [{'type': 'text', 'text': 'hello '}, {'type': 'text', 'text': 'there'}]}})
        p = self.write('2026/11/04/rollout-a.jsonl', [cx_meta(), item, cx('event_msg', {'type': 'item_completed', 'item': {'type': 'Reasoning'}})])
        self.assertEqual([(e.kind, e.text) for e in codex.read(p, self.root).events], [(USER_TEXT, 'hello there')])

    def test_injected_wrappers_and_subagent_prompts(self):
        for text, kind in (('<environment_context>\nx\n</environment_context>', INJECTED), ('<user_instructions>x</user_instructions>', INJECTED),
                           ('# AGENTS.md instructions for /work/repo\n\n<INSTRUCTIONS>..</INSTRUCTIONS>', INJECTED),
                           ('<environment_context> explain this tag to me', USER_TEXT), ('plain request', USER_TEXT),
                           ('<div>fix my html</div>', USER_TEXT)):
            p = self.write('2026/11/04/rollout-b.jsonl', [cx_meta(), cx_user(text)])
            self.assertEqual(codex.read(p, self.root).events[0].kind, kind, text)
        sub = cx_meta(source={'subagent': {'thread_spawn': {'parent_thread_id': 'P', 'depth': 1}}}, forked_from_id='P', thread_source='subagent')
        p = self.write('2026/11/04/rollout-c.jsonl', [sub, cx('turn_context', {'model': 'm'}), cx_user('do the review')])
        s = codex.read(p, self.root)
        self.assertEqual((s.kind, s.parent_id, [e.kind for e in s.events]), (SUBAGENT, 'P', [INJECTED]))


class CodexFork(TmpCase):
    PARENT = '019a0000-0001-7000-8000-000000000001'
    CHILD = '019a0000-0002-7000-8000-000000000002'
    OLD = '019a0000-0001-7aaa-8000-0000000000aa'
    NEW = '019a0000-0002-7bbb-8000-0000000000bb'

    def replay(self, *own, meta=None, with_parent_meta=True, old_turn=True):
        rows = [meta or cx_meta(self.CHILD, forked_from_id=self.PARENT, thread_source='user')]
        if with_parent_meta:
            rows.append(cx_meta(self.PARENT))
        rows += ([cx('turn_context', {'turn_id': self.OLD})] if old_turn else []) + [cx_user('parent prompt'), cx_call('old', args={'cmd': 'parent cmd'}),
                 cx('event_msg', {'type': 'agent_message', 'message': 'parent answer'})]
        p = self.write('2026/11/04/rollout-f.jsonl', rows + list(own))
        return codex.read(p, self.root)

    def test_replayed_parent_turns_are_dropped(self):
        s = self.replay(cx('turn_context', {'turn_id': self.NEW}), cx_user('my own prompt'))
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['my own prompt'])
        self.assertEqual(calls(s), [])
        self.assertEqual((s.id, s.parent_id), (self.CHILD, self.PARENT))        # the child's own session_meta, not the copied parent's

    def test_replay_is_recognised_without_a_copied_parent_meta(self):
        s = self.replay(cx('turn_context', {'turn_id': self.NEW}), cx_user('mine'), with_parent_meta=False)
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['mine'])

    def test_a_fork_with_no_own_turn_yet_has_no_events(self):
        self.assertEqual(self.replay().events, [])

    def test_turn_ids_without_a_uuid7_end_the_replay_at_the_first_turn_context(self):
        s = self.replay(cx('turn_context', {}), cx_user('mine'), meta=cx_meta('child', forked_from_id='parent'), with_parent_meta=False, old_turn=False)
        self.assertEqual([e.text for e in kinds(s, USER_TEXT)], ['mine'])

    def test_same_millisecond_turn_needs_a_task_started_unless_a_user_fork(self):
        same = '019a0000-0002-7ccc-8000-0000000000cc'
        sub = cx_meta(self.CHILD, forked_from_id=self.PARENT, thread_source='subagent', source={'subagent': {'thread_spawn': {'parent_thread_id': self.PARENT}}})
        own = [cx('turn_context', {'turn_id': same}), cx_user('mine')]
        self.assertEqual(self.replay(*own, meta=sub).events, [])
        announced = [cx('event_msg', {'type': 'task_started', 'turn_id': same})] + own
        self.assertEqual([e.text for e in self.replay(*announced, meta=sub).events], ['mine'])
        self.assertEqual([e.text for e in self.replay(*own).events], ['mine'])       # user fork

    def test_a_task_started_for_an_ancestors_turn_does_not_announce_it(self):
        sub = cx_meta(self.CHILD, forked_from_id=self.PARENT, thread_source='subagent')
        s = self.replay(cx('event_msg', {'type': 'task_started', 'turn_id': self.OLD}), cx('turn_context', {'turn_id': self.OLD}), cx_user('still replay'), meta=sub)
        self.assertEqual(s.events, [])

    def test_a_non_fork_session_keeps_everything(self):
        p = self.write('2026/11/04/rollout-n.jsonl', [cx_meta(), cx('turn_context', {'turn_id': self.OLD}), cx_user('a')])
        self.assertEqual([e.text for e in codex.read(p, self.root).events], ['a'])


class CodexFind(TmpCase):
    def test_find_sessions_matches_by_session_meta_cwd(self):
        a = self.write('2026/11/04/rollout-a.jsonl', [cx_meta('a', CWD), cx_user('x')])
        self.write('2026/11/05/rollout-b.jsonl', [cx_meta('b', '/work/other'), cx_user('x')])
        self.write('2026/11/05/rollout-c.jsonl', [cx_user('no meta first')])
        self.write('2026/11/05/notes.jsonl', [cx_meta('d', CWD)])
        self.write('2026/11/05/rollout-e.jsonl', [cx_meta('e', None)])
        self.assertEqual(codex.find_sessions(CWD, self.root), [a])
        self.assertEqual(codex.find_sessions(CWD, os.path.join(self.tmp, 'missing')), [])

    def test_a_subagent_rollout_is_listed_only_through_its_parent(self):
        self.write('2026/11/04/rollout-2026-11-04T10-00-00-a.jsonl', [cx_meta('a', CWD)])
        self.write('2026/11/04/rollout-2026-11-04T10-00-05-b.jsonl', [cx_meta('b', CWD, thread_source='subagent', source={'subagent': {'thread_spawn': {'parent_thread_id': 'a'}}})])
        self.assertEqual(len(codex.find_sessions(CWD, self.root)), 1)
        s = codex.read(codex.find_sessions(CWD, self.root)[0], self.root)
        self.assertEqual([c.id for c in s.children], ['b'])


# ---------------------------------------------------------------- shared guards and hostile input

class Harness:
    """What the hostile-input tests need to know about one adapter."""
    def __init__(self, mod, rel, header, user, call, out):
        self.mod, self.rel, self.header, self.user, self.call, self.out = mod, rel, header, user, call, out

    def path(self, case, name='s'):
        return os.path.join(case.root, self.rel % name)


COPILOT = Harness(copilot, '%s/events.jsonl', cp_start, cp_user,
                  lambda cid: cp_call(cid, args={'command': 'echo %s' % cid}), lambda cid, text: cp_done(cid, result={'content': text}))
CODEX = Harness(codex, '2026/11/04/rollout-%s.jsonl', cx_meta, cx_user,
                lambda cid: cx_call(cid, 'shell_command', {'command': 'echo %s' % cid}), cx_out)


class HostileFiles:
    """Hostile-input tests that need only a header and user lines: every adapter of a JSON-lines transcript runs them."""
    H = None

    def make(self, lines, name='s', mode='w'):
        return self.write(self.H.rel % name, lines, mode)

    def read(self, path):
        return self.H.mod.read(path, self.root)

    def test_empty_file(self):
        s = self.read(self.make([]))
        self.assertEqual((s.events, s.id), ([], None))

    def test_truncated_last_line_is_skipped(self):
        p = self.make([self.H.header(), self.H.user('first')])
        with open(p, 'a') as fh:
            fh.write(json.dumps(self.H.user('second'))[:-9])
        self.assertEqual([e.text for e in self.read(p).events], ['first'])

    def test_complete_last_line_without_newline_is_kept(self):
        p = self.make([self.H.header()])
        with open(p, 'a') as fh:
            fh.write(json.dumps(self.H.user('last')))
        self.assertEqual([e.text for e in self.read(p).events], ['last'])

    def test_invalid_utf8_is_replaced_not_fatal(self):
        p = self.make([json.dumps(self.H.header()).encode(), b'\xff\xfe not json', json.dumps(self.H.user('café ok')).encode(),
                       json.dumps(self.H.user('bad \udcff')).encode().replace(b'\\udcff', b'\xff')], mode='wb')
        texts = [e.text for e in self.read(p).events]
        self.assertEqual(texts[0], 'café ok')
        self.assertEqual(texts[1], 'bad �')

    def test_a_5mb_line_is_read_whole(self):
        big = 'x' * (5 * 1024 * 1024)
        p = self.make([self.H.header(), self.H.user(big), self.H.user('after')])
        self.assertEqual([len(e.text) for e in self.read(p).events], [len(big), 5])

    def test_a_line_over_the_cap_is_skipped_and_reading_continues(self):
        old = _io.MAX_LINE
        _io.MAX_LINE = 1000
        try:
            smuggled = 'z' * 1001 + json.dumps(self.H.user('smuggled'))     # the tail past the cap is itself a valid record
            p = self.make([self.H.header(), smuggled, self.H.user('y' * 5000), self.H.user('after')])
            self.assertEqual([e.text for e in self.read(p).events], ['after'])
        finally:
            _io.MAX_LINE = old

    def test_unknown_record_types_and_non_objects_are_ignored(self):
        p = self.make([self.H.header(), {'type': 'brand.new.kind', 'data': {'x': 1}, 'payload': {'y': 2}}, '[1,2,3]', '"str"', '42', 'null',
                       self.H.user('kept')])
        self.assertEqual([e.text for e in self.read(p).events], ['kept'])

    def test_a_file_that_grows_while_read_is_read_as_of_open(self):
        p = self.make([self.H.header(), self.H.user('one'), self.H.user('two')])
        it = _io.records(os.path.realpath(p))
        next(it)
        with open(p, 'a') as fh:
            fh.write(json.dumps(self.H.user('late')) + '\n')
        self.assertEqual(len(list(it)), 2)        # the rest of the snapshot; the appended line is not part of it
        self.assertEqual([e.text for e in self.read(p).events], ['one', 'two', 'late'])

    def test_a_writer_appending_during_a_read_never_breaks_it(self):
        p = self.make([self.H.header(), self.H.user('seed')])
        stop = threading.Event()

        def writer():
            n = 0
            while not stop.is_set():
                with open(p, 'a') as fh:
                    fh.write(json.dumps(self.H.user('w%d' % n)) + '\n')
                n += 1
        t = threading.Thread(target=writer)
        t.start()
        try:
            for _ in range(20):
                self.assertEqual(self.read(p).events[0].text, 'seed')
        finally:
            stop.set()
            t.join()

    def test_detect_and_registry(self):
        p = self.make([self.H.header()])
        self.assertTrue(self.H.mod.detect(p))
        self.assertEqual(adapters.detect_format(p), self.H.mod.HARNESS)
        self.assertIs(adapters.get(self.H.mod.HARNESS), self.H.mod)
        junk = self.make(['{"type":"other"}'], 'junk')
        self.assertFalse(self.H.mod.detect(junk))
        self.assertIsNone(adapters.detect_format(junk))
        self.assertFalse(self.H.mod.detect(os.path.join(self.root, 'missing')))


class Hostile(HostileFiles):
    """Adds the tests that need tool calls and their output records."""

    def test_missing_fields_become_none(self):
        p = self.make([{'type': 'session.start' if self.H is COPILOT else 'session_meta'}, {'type': 'tool.execution_complete', 'data': 5, 'payload': 5},
                       {'type': 'assistant.message', 'data': {'toolRequests': [{}, 7, {'name': 'bash'}]}},
                       {'type': 'response_item', 'payload': {'type': 'function_call'}},
                       {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell_command'}}])
        s = self.read(p)
        self.assertEqual((s.id, s.cwd, s.started_at), (None, None, None))
        for t in calls(s):
            self.assertEqual((t.call_id, t.output, t.exit_code, t.is_error), (None, None, None, False))


    def test_a_duplicated_call_id_pairs_in_order_and_a_repeated_output_is_ignored(self):
        p = self.make([self.H.header(), self.H.call('d'), self.H.call('d'), self.H.out('d', 'first'), self.H.out('d', 'second'), self.H.out('d', 'third')])
        self.assertEqual([t.output for t in calls(self.read(p))], ['first', 'second'])


    def test_an_output_with_no_call_makes_no_event(self):
        p = self.make([self.H.header(), self.H.out('ghost', 'orphan'), self.H.call('a'), self.H.out('a', 'mine')])
        s = self.read(p)
        self.assertEqual([(t.call_id, t.output) for t in calls(s)], [('a', 'mine')])


    def test_a_call_with_no_output_keeps_none(self):
        p = self.make([self.H.header(), self.H.call('a')])
        t = calls(self.read(p))[0]
        self.assertEqual((t.output, t.exit_code, t.is_error, t.command), (None, None, False, 'echo a'))


class Guards:
    H = None

    def test_a_transcript_outside_the_root_is_refused(self):
        outside = os.path.join(self.tmp, 'outside', 'forged.jsonl')
        os.makedirs(os.path.dirname(outside))
        with open(outside, 'w') as fh:
            fh.write(json.dumps(self.H.header()) + '\n')
        with self.assertRaises(_io.RootError):
            self.H.mod.read(outside, self.root)

    def test_a_symlink_that_escapes_the_root_is_refused(self):
        outside = os.path.join(self.tmp, 'outside', 'forged.jsonl')
        os.makedirs(os.path.dirname(outside))
        with open(outside, 'w') as fh:
            fh.write(json.dumps(self.H.header()) + '\n')
        link = self.H.path(self)
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(outside, link)
        with self.assertRaises(_io.RootError):
            self.H.mod.read(link, self.root)
        self.assertEqual(self.H.mod.find_sessions(CWD, self.root), [])

    def test_a_symlinked_directory_that_escapes_the_root_is_refused(self):
        outside = os.path.join(self.tmp, 'outside')
        real = os.path.join(outside, os.path.dirname(self.H.rel % 's'))
        os.makedirs(real)
        with open(os.path.join(outside, self.H.rel % 's'), 'w') as fh:
            fh.write(json.dumps(self.H.header()) + '\n')
        top = (self.H.rel % 's').split('/')[0]
        os.symlink(os.path.join(outside, top), os.path.join(self.root, top))
        with self.assertRaises(_io.RootError):
            self.H.mod.read(os.path.join(self.root, self.H.rel % 's'), self.root)
        self.assertEqual(self.H.mod.find_sessions(CWD, self.root), [])

    def test_dotdot_cannot_climb_out_of_the_root(self):
        outside = os.path.join(self.tmp, 'forged.jsonl')
        with open(outside, 'w') as fh:
            fh.write(json.dumps(self.H.header()) + '\n')
        with self.assertRaises(_io.RootError):
            self.H.mod.read(os.path.join(self.root, '..', 'forged.jsonl'), self.root)

    def test_a_sibling_directory_sharing_the_roots_name_prefix_is_outside(self):
        sibling = self.root + '-evil'
        os.makedirs(sibling)
        p = os.path.join(sibling, 's.jsonl')
        with open(p, 'w') as fh:
            fh.write(json.dumps(self.H.header()) + '\n')
        with self.assertRaises(_io.RootError):
            self.H.mod.read(p, self.root)

    def test_a_symlink_inside_the_root_to_a_file_inside_the_root_is_fine(self):
        real = self.write(self.H.rel % 'real', [self.H.header(), self.H.user('ok')])
        link = self.H.path(self, 'link')
        os.makedirs(os.path.dirname(link), exist_ok=True)
        os.symlink(real, link)
        self.assertEqual([e.text for e in self.H.mod.read(link, self.root).events], ['ok'])

    def test_a_fifo_or_directory_is_not_read(self):
        fifo = self.H.path(self, 'fifo')
        os.makedirs(os.path.dirname(fifo), exist_ok=True)
        os.mkfifo(fifo)
        for target in (fifo, os.path.dirname(fifo)):
            with self.assertRaises(_io.RootError):
                self.H.mod.read(target, self.root)

    def test_the_default_root_is_the_harness_directory_and_no_environment_variable_moves_it(self):
        saved = {k: os.environ.get(k) for k in ('COPILOT_HOME', 'CODEX_HOME', 'HOME')}
        try:
            os.environ['COPILOT_HOME'] = os.environ['CODEX_HOME'] = self.tmp
            home = os.path.expanduser('~')
            self.assertEqual(self.H.mod.default_root(), os.path.join(home, *self.H.default_parts))
            outside = os.path.join(self.tmp, 'forged.jsonl')
            with open(outside, 'w') as fh:
                fh.write(json.dumps(self.H.header()) + '\n')
            with self.assertRaises(_io.RootError):
                self.H.mod.read(outside)             # no root argument: the default root applies
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class CopilotHostile(Hostile, TmpCase):
    H = COPILOT


class CodexHostile(Hostile, TmpCase):
    H = CODEX


class CopilotGuards(Guards, TmpCase):
    H = COPILOT
    H.default_parts = ('.copilot', 'session-state')


class CodexGuards(Guards, TmpCase):
    H = CODEX
    H.default_parts = ('.codex', 'sessions')


if __name__ == '__main__':
    unittest.main()
