"""The transcript adapters wired into collect, validate and render: a session of any supported harness grounds a change doc and a session doc.

Each harness is built from its adapter fixtures under a throwaway HOME, at the folder that harness really uses (the root of an adapter has no
override, so HOME is what moves it). Every case runs the real scripts or the real validators."""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from helpers2 import V2Case  # noqa: E402
from lib import adapters, check_session, neutral, session, transcript  # noqa: E402
from lib.adapters import cursor_ide, opencode  # noqa: E402

import test_adapters as ta  # noqa: E402
import test_adapters_cursor_ide as tide  # noqa: E402
import test_adapters_opencode as toc  # noqa: E402

FIX = os.path.join(HERE, 'fixtures')
SKILL = os.path.join(os.path.dirname(HERE), 'skills', 'explain-change')
CWD = '/work/repo'
CODEX_MAIN = 'rollout-2026-11-04T10-00-00-019a0000-0001-7000-8000-000000000001.jsonl'
GEMINI_MAIN = 'session-2026-11-04T10-00-0f1e2d3c.jsonl'
CLI_MAIN, CLI_INJECTED = 'a1b2c3d4-e5f6-4890-abcd-ef1234567890', '66666666-7777-4888-9999-aaaaaaaaaaaa'
PUSH = 'git push origin main'
HARNESSES = ('copilot', 'codex', 'opencode', 'gemini', 'cursor-cli', 'cursor-ide')


class Spec:
    """What a harness's fixture session offers: `refs` per role (main, err, unk, inj), the user quote, and the shell calls (command, excerpt)
    whose result is ok, an error, or unknown."""

    def __init__(self, name, refs, quote, ok=None, err=None, unk=None, injected=None):
        self.name, self.refs, self.quote, self.ok, self.err, self.unk, self.injected = name, refs, quote, ok, err, unk, injected

    @property
    def main(self):
        return self.refs['main']


def build_copilot(home, extra=()):
    d = os.path.join(home, '.copilot', 'session-state', 'ab68f63a-ec2a-4635-947c-487f56661807')
    os.makedirs(d)
    p = os.path.join(d, 'events.jsonl')
    shutil.copy(os.path.join(FIX, 'copilot', 'tool-exercise.jsonl'), p)
    with open(p, 'a', encoding='utf-8') as fh:
        for rec in [ta.cp('user.message', {'content': 'AUTOPILOT-NUDGE keep going on the retry', 'source': 'autopilot'})] + list(extra):
            fh.write(json.dumps(rec) + '\n')
    return Spec('copilot', {'main': p}, 'Reply with the word finished', ok=('echo audit-marker', 'audit-marker'),
                err=('ls /nonexistent-dir', 'No such file or directory'), unk=('sleep 300', 'command started in background'),
                injected='AUTOPILOT-NUDGE keep going')


def build_codex(home, extra=()):
    root = os.path.join(home, '.codex', 'sessions')
    shutil.copytree(os.path.join(FIX, 'codex', 'sessions'), root)
    p = os.path.join(root, '2026', '11', '04', CODEX_MAIN)
    if extra:
        with open(p, 'a', encoding='utf-8') as fh:
            for rec in extra:
                fh.write(json.dumps(rec) + '\n')
    return Spec('codex', {'main': p}, 'Add a retry to fetch() in client.py', ok=('ls src', 'client.py'), err=('pytest -q', 'FAILED test_client.py'),
                injected='<environment_context>')


def build_gemini(home):
    root = os.path.join(home, '.gemini', 'tmp')
    shutil.copytree(os.path.join(FIX, 'gemini', 'tmp'), root)
    p = os.path.join(root, 'ddc5e473a09bd156', 'chats', GEMINI_MAIN)
    return Spec('gemini', {'main': p}, 'Add a retry to fetch() in client.py', ok=('ls src', 'client.py'), err=('pytest -q', '1 failed, 4 passed'),
                unk=('true', 'Command is running in background'), injected='This is the Gemini CLI')


def build_cursor_cli(home):
    root = os.path.join(home, '.cursor', 'projects')
    shutil.copytree(os.path.join(FIX, 'cursor-cli', 'projects'), root)

    def ref(sid):
        return os.path.join(root, 'work-repo', 'agent-transcripts', sid, sid + '.jsonl')
    return Spec('cursor-cli', {'main': ref(CLI_MAIN), 'inj': ref(CLI_INJECTED)}, 'run ls command', unk=('ls -la /tmp', 'total 0'),
                injected='Use the repo context and explain the latest build issue')


def build_cursor_ide(home):
    root = cursor_ide.default_root()
    os.makedirs(root)
    db = os.path.join(root, tide.DB)
    tide.build_fixture(db)
    ref = os.path.realpath(db) + '#' + tide.C3
    return Spec('cursor-ide', {'main': ref}, 'Add a retry to fetch() in client.py', err=('nosuchcmd', 'command not found'), unk=('ls src', 'client.py'))


def build_opencode(home):
    root = opencode.default_root()
    os.makedirs(root)
    db = os.path.join(root, toc.DB)
    con = toc.build_v2(db, ('tui-session.jsonl', 'tool-exercise.jsonl', 'model-error.jsonl'))
    toc.v2_session(con, 'ses_unk', cwd='/work/unk')
    toc.v2_msg(con, 'ses_unk', 1, 'assistant', {'content': [toc.v2_tool('c1', 'shell', {'command': 'make build'}, status='running')]})
    con.commit()
    con.close()
    real = os.path.realpath(db)
    ref = lambda sid: real + '#' + sid  # noqa: E731
    return Spec('opencode', {'main': ref('ses_f34a1dc63ffe0cCnMWOTpjumbx'), 'err': ref('ses_f34a354dbffe8waMGOZgKvK6cK'), 'unk': ref('ses_unk')},
                'In one sentence, what did the review conclude?', ok=('git status --short', 'M hello.py'), err=('cat does-not-exist.txt', 'No such file or directory'),
                unk=('make build', 'built'), injected='You are in Plan mode')


BUILDERS = {'copilot': build_copilot, 'codex': build_codex, 'gemini': build_gemini, 'cursor-cli': build_cursor_cli, 'cursor-ide': build_cursor_ide,
            'opencode': build_opencode}


class HomeCase(unittest.TestCase):
    """A throwaway HOME; `spec(name)` builds a harness's fixture under it."""

    def setUp(self):
        transcript.forget()
        self.addCleanup(transcript.forget)
        self._tmp = tempfile.TemporaryDirectory(prefix='explain-wire-')
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.realpath(self._tmp.name)
        patch = mock.patch.dict(os.environ, {'HOME': self.home})
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop('EXPLAIN_PROJECTS_DIR', None)
        self.env = {'HOME': self.home}

    def fresh_home(self):
        """A new empty HOME for the next harness of a loop (each fixture is copied to the folder its harness uses)."""
        self.home = tempfile.mkdtemp(prefix='wire-', dir=self.home)
        os.environ['HOME'] = self.home

    def spec(self, name, **kw):
        return BUILDERS[name](self.home, **kw)

    def cli(self, script, *args, timeout=60):
        return subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', script), *args], capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, 'HOME': self.home})


def src_tool(cmd, excerpt):
    return {'kind': 'tool_call', 'command': cmd, 'excerpt': excerpt}


def session_doc(spec, events, outward=(), status='done'):
    turn = session.quote_turns(transcript.safe_path(spec.main), [spec.quote])[spec.quote][0]
    events = [dict(e, order=e.get('order', turn)) if e.get('source') != {'inferred': True} else e for e in events]
    evs = [{'kind': 'asked', 'text': 'The ask', 'order': turn, 'source': {'kind': 'user_reported', 'quote': spec.quote}}] + list(events)
    return {'schema': 'explain-session/1', 'lang': 'en', 'title': 'A session', 'summary': 'One theme.',
            'themes': [{'id': 'a', 'title': 'Theme A', 'status': status, 'outcome': 'Done.', 'events': evs}],
            'needs_you': [], 'decided': [], 'outward': list(outward)}


def done(cmd, excerpt):
    return {'kind': 'done', 'text': 'The run finished', 'source': src_tool(cmd, excerpt)}


class EndToEnd(HomeCase, V2Case):
    """validate.py gives ok and render.py writes the page, for a change doc and for a session doc grounded in each harness's fixture."""

    def setUp(self):
        V2Case.setUp(self)
        HomeCase.setUp(self)

    def adapt(self, d, spec):
        """The v2 good_doc with every transcript source moved onto the harness's session."""
        def walk(n):
            if isinstance(n, dict):
                if n.get('kind') in ('transcript', 'user_reported') and 'quote' in n:
                    n['quote'] = spec.quote
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)
        walk(d)
        for r in d['requests']:
            r['quote'] = spec.quote
        src = src_tool(*spec.ok) if spec.ok else {'kind': 'user_reported', 'quote': spec.quote}
        d['evidence']['ran'] = [{'id': 'e1', 'what': 'A run', 'result': 'passed' if spec.ok else 'mixed', 'detail': 'It ran.', 'modules': ['tests'], 'source': src}]
        return d

    def put_doc(self, name, doc):
        p = os.path.join(self.repo, name)
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        return p

    def test_a_change_doc_is_ok_and_renders_for_every_harness(self):
        for name in HARNESSES:
            with self.subTest(harness=name):
                self.fresh_home()
                spec = self.spec(name)
                path = self.put_doc('%s.json' % name, self.adapt(self.good_doc(), spec))
                v = self.cli('validate.py', path, '--repo', self.repo, '--transcript', spec.main)
                self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
                self.assertEqual(v.stdout.splitlines()[0], 'ok')
                out = os.path.join(self.repo, '%s.html' % name)
                r = self.cli('render.py', path, '--repo', self.repo, '--transcript', spec.main, '--out', out)
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(out, encoding='utf-8') as fh:
                    self.assertIn('validated=yes', fh.read())

    def test_a_session_doc_is_ok_and_renders_for_every_harness(self):
        for name in HARNESSES:
            with self.subTest(harness=name):
                self.fresh_home()
                spec = self.spec(name)
                ev = [done(*spec.ok)] if spec.ok else [{'kind': 'in_progress', 'text': 'Waiting', 'source': {'inferred': True}}]
                path = self.put_doc('s-%s.json' % name, session_doc(spec, ev, status='done' if spec.ok else 'in_progress'))
                v = self.cli('validate.py', path, '--transcript', spec.main)
                self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
                self.assertEqual(v.stdout.splitlines()[0], 'ok')
                out = os.path.join(self.repo, 's-%s.html' % name)
                r = self.cli('render.py', path, '--transcript', spec.main, '--out', out)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertGreater(os.path.getsize(out), 1000)

    def passed(self, spec, source):
        d = self.adapt(self.good_doc(), spec)
        d['evidence']['ran'][0].update(source=source, result='passed')
        errs, _ = __import__('lib.check', fromlist=['validate']).validate(d, self.repo, spec.refs.get('unk', spec.main))
        return errs

    def test_a_passed_run_needs_a_result_that_is_known_and_not_an_error(self):
        for name in HARNESSES:
            with self.subTest(harness=name):
                self.fresh_home()
                spec = self.spec(name)
                if spec.err:
                    d = self.adapt(self.good_doc(), spec)
                    d['evidence']['ran'][0].update(source=src_tool(*spec.err), result='passed')
                    from lib import check
                    errs, _ = check.validate(d, self.repo, spec.refs.get('err', spec.main))
                    self.assertTrue(any('an errored run cannot back a pass' in e for e in errs), errs)
                if spec.unk:
                    errs = self.passed(spec, src_tool(*spec.unk))
                    self.assertTrue(any('unknown' in e for e in errs), errs)
                    self.assertFalse(any('errored run' in e for e in errs), errs)

    def test_the_doc_transcript_field_and_an_explicit_format_work(self):
        spec = self.spec('codex')
        d = self.adapt(self.good_doc(), spec)
        d['transcript'] = spec.main
        path = self.put_doc('f.json', d)
        for fmt in ('auto', 'codex'):
            v = self.cli('validate.py', path, '--repo', self.repo, '--format', fmt)
            self.assertEqual(v.stdout.splitlines()[0], 'ok', v.stdout)


class Rejections(HomeCase):
    """The grounding rules hold on the normalized model of each harness."""

    def errors(self, spec, events, role='main', outward=()):
        doc = session_doc(spec, events, outward)
        errs, _ = check_session.validate(doc, spec.refs[role])
        return errs

    def assertRejected(self, errs, needle):
        self.assertTrue(any(needle in e for e in errs), 'expected %r in %r' % (needle, errs))

    def for_each(self, check):
        for name in HARNESSES:
            with self.subTest(harness=name):
                self.fresh_home()
                check(name, self.spec(name))

    def test_a_quote_from_injected_text_is_rejected(self):
        def check(name, spec):
            if not spec.injected:
                return  # the Cursor IDE adapter records no injected text
            ref = spec.refs.get('inj', spec.main)
            mod = adapters.get(name)
            injected = [e.text for e in mod.read(ref, mod.default_root()).events if e.kind == 'injected']
            self.assertTrue([t for t in injected if spec.injected in t], 'the fixture has no such injected text')
            doc = session_doc(spec, [])
            doc['themes'][0]['events'][0]['source']['quote'] = spec.injected
            errs, _ = check_session.validate(doc, ref)
            self.assertRejected(errs, 'quote not found in a message of the user')
        self.for_each(check)

    def test_a_mismatched_command_is_rejected(self):
        self.for_each(lambda n, spec: self.assertRejected(self.errors(spec, [done('definitely-not-run --flag', 'whatever output')]), 'command not found in any tool call'))

    def test_a_mismatched_output_is_rejected(self):
        def check(name, spec):
            cmd, role = (spec.ok, 'main') if spec.ok else (spec.err, 'err') if spec.err else (spec.unk, 'unk')
            role = role if role in spec.refs else 'main'
            errs = self.errors(spec, [done(cmd[0], 'text the call never printed')], role)
            self.assertTrue(any('result excerpt is not in the result' in e or 'no recorded result' in e for e in errs), errs)
        self.for_each(check)

    def test_an_error_result_cannot_back_done(self):
        def check(name, spec):
            if not spec.err:
                return  # the Cursor CLI adapter records no error flag
            role = 'err' if 'err' in spec.refs else 'main'
            self.assertRejected(self.errors(spec, [done(*spec.err)], role), 'an errored run cannot back a done')
        self.for_each(check)

    def test_a_result_unknown_cannot_back_done(self):
        def check(name, spec):
            if not spec.unk:
                return
            role = 'unk' if 'unk' in spec.refs else 'main'
            errs = self.errors(spec, [done(*spec.unk)], role)
            self.assertRejected(errs, 'no recorded result' if name in ('cursor-cli', 'opencode') else 'result is unknown')
            self.assertFalse([e for e in errs if 'an errored run' in e], errs)
        self.for_each(check)

    def test_a_known_ok_result_can_back_done(self):
        self.for_each(lambda n, spec: spec.ok and self.assertEqual(self.errors(spec, [done(*spec.ok)]), []))


class Outward(HomeCase):
    """Session mode classifies outward actions from the shell command of any harness."""

    def push_calls(self):
        return {
            'copilot': [ta.cp('assistant.message', {'content': '', 'toolRequests': [{'toolCallId': 'px', 'name': 'bash', 'arguments': {'command': PUSH}}]}),
                        ta.cp_done('px', shellExecution={'exitCode': 0}, result={'content': 'Everything up-to-date'})],
            'codex': [ta.cx_call('px', args={'cmd': PUSH}), ta.cx_out('px', 'Exit code: 0\nWall time: 0.1 seconds\nOutput:\nEverything up-to-date')]}

    def test_a_push_is_outward_in_copilot_and_codex(self):
        for name, extra in self.push_calls().items():
            with self.subTest(harness=name):
                self.fresh_home()
                spec = self.spec(name, extra=extra)
                self.assertEqual(dict(session.scan(transcript.safe_path(spec.main)).counts()), {'push': 1})

    def cursor_with_push(self):
        spec = self.spec('cursor-ide')
        db = spec.main.split('#')[0]
        con = sqlite3.connect(db, isolation_level=None)
        tide.composer(con, 'pushed', fullConversationHeadersOnly=[tide.header(b, t) for b, t in [('q1', 1), ('q2', 2)]])
        tide.bubble(con, 'pushed', 'q1', 1, 'Push the branch')
        tide.tool_bubble(con, 'pushed', 'q2', tide.tool_data(command=PUSH, output='Everything up-to-date'))
        con.close()
        return db + '#pushed'

    def test_a_push_in_a_cursor_ide_session_is_counted_and_flagged_as_having_no_recorded_result(self):
        text, _ = session.digest(transcript.safe_path(self.cursor_with_push()))
        self.assertIn('u1  push', text.replace('  push', '  push'))
        self.assertIn('1 of these ran with no result recorded', text)

    def test_a_session_doc_must_match_the_outward_count(self):
        spec = self.spec('copilot', extra=self.push_calls()['copilot'])
        good = {'kind': 'push', 'count': 1, 'themes': ['a'], 'evidence': [src_tool(PUSH, 'Everything up-to-date')]}
        out_ev = {'kind': 'outward', 'text': 'Pushed', 'source': src_tool(PUSH, 'Everything up-to-date')}
        errs, _ = check_session.validate(session_doc(spec, [out_ev], [good]), spec.main)
        self.assertEqual(errs, [])
        errs, _ = check_session.validate(session_doc(spec, [out_ev], []), spec.main)
        self.assertTrue(any('push: 1 successful call(s) in the transcript but the doc does not list them' in e for e in errs), errs)


class Listing(HomeCase):
    """collect.py lists the sessions recorded in the repo's folder, labelled by harness."""

    def test_the_session_listing_names_each_harness(self):
        for name in ('codex', 'gemini', 'cursor-cli', 'cursor-ide'):
            self.spec(name)
        out = self.cli('collect.py', '--session', '--repo', CWD)
        self.assertEqual(out.returncode, 0, out.stderr)
        for name in ('codex', 'gemini', 'cursor-cli', 'cursor-ide'):
            self.assertIn('[%s] ' % name, out.stdout, name)
        self.assertIn('none found under ~/.claude/projects', out.stdout)

    def test_a_credential_in_the_first_message_is_masked_in_the_listing(self):
        spec = self.spec('codex')
        secret = 'Zq9-fake-Cred7'  # synthetic, only for this test
        newer = os.path.join(os.path.dirname(spec.main), 'rollout-2026-11-04T11-00-00-019a0000-0009-7000-8000-000000000009.jsonl')
        with open(newer, 'w', encoding='utf-8') as fh:
            for rec in (ta.cx_meta(sid='019a0000-0009-7000-8000-000000000009'), ta.cx_user('the shared password: %s, please fix it' % secret)):
                fh.write(json.dumps(rec) + '\n')
        out = self.cli('collect.py', '--session', '--repo', CWD)
        self.assertIn('please fix it', out.stdout)
        self.assertNotIn(secret, out.stdout)
        self.assertIn(transcript.MASK, out.stdout)

    def test_the_listing_of_opencode_and_copilot(self):
        spec = self.spec('opencode')
        out = self.cli('collect.py', '--session', '--repo', '/Users/dev/oc-tools')
        self.assertIn('[opencode] ' + spec.main.split('#')[0], out.stdout)
        self.assertEqual(out.stdout.count('[opencode] '), 2)
        self.fresh_home()
        spec = self.spec('copilot')
        out = self.cli('collect.py', '--session', '--repo', '/private/tmp/copilot-v3')
        self.assertIn('[copilot] ' + spec.main, out.stdout)

    def test_the_digest_of_every_harness_counts_user_turns_and_leaves_injected_text_out(self):
        for name in HARNESSES:
            with self.subTest(harness=name):
                self.fresh_home()
                spec = self.spec(name)
                out = self.cli('collect.py', '--session', '--repo', CWD, '--transcript', spec.main)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn('[u1 ', out.stdout)
                self.assertNotIn(spec.injected or '\0', out.stdout)


class Hostile(HomeCase):
    """--transcript and --format on files nobody should trust: one clear line, no traceback, no hang."""

    def one_line(self, p, code=None):
        self.assertNotIn('Traceback', p.stderr)
        self.assertEqual(len(p.stderr.strip().splitlines()), 1, p.stderr)
        if code is not None:
            self.assertEqual(p.returncode, code, p.stderr)

    def codex_root(self):
        spec = self.spec('codex')
        return os.path.dirname(spec.main), spec

    def test_an_undetectable_file_exits_1_naming_the_supported_formats(self):
        d, _ = self.codex_root()
        bad = os.path.join(d, 'notes.txt')
        with open(bad, 'w') as fh:
            fh.write('just some words\n')
        p = self.cli('collect.py', '--session', '--transcript', bad)
        self.one_line(p, 1)
        self.assertIn('claude, copilot, codex, opencode, gemini, cursor-cli, cursor-ide', p.stderr)

    def test_an_empty_file_is_undetectable(self):
        d, _ = self.codex_root()
        empty = os.path.join(d, 'empty.jsonl')
        open(empty, 'w').close()
        for args in ((), ('--format', 'codex')):
            p = self.cli('collect.py', '--session', '--transcript', empty, *args)
            self.one_line(p, 1)

    def test_invalid_utf8_inside_a_line_is_replaced_not_fatal(self):
        spec = self.spec('codex')
        with open(spec.main, 'ab') as fh:
            fh.write(b'{"type": "event_msg", "payload": {"type": "user_message", "message": "bad \xff\xfe bytes"}}\n')
        p = self.cli('collect.py', '--session', '--transcript', spec.main)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('[u3 ', p.stdout)

    def test_a_huge_line_is_skipped(self):
        spec = self.spec('codex')
        with open(spec.main, 'ab') as fh:
            fh.write(b'{"type": "event_msg", "payload": {"message": "' + b'x' * (33 * 1024 * 1024) + b'"}}\n')
        p = self.cli('collect.py', '--session', '--transcript', spec.main, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr[-300:])
        self.assertIn('User turns (2', p.stdout)

    def test_a_symlink_out_of_the_root_is_refused(self):
        spec = self.spec('codex')
        outside = os.path.join(self.home, 'outside.jsonl')
        shutil.copy(spec.main, outside)
        link = os.path.join(os.path.dirname(spec.main), 'link.jsonl')
        os.symlink(outside, link)
        p = self.cli('collect.py', '--session', '--transcript', link)
        self.one_line(p)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('transcript must be under', p.stderr)

    def test_a_fifo_does_not_block(self):
        d, _ = self.codex_root()
        fifo = os.path.join(d, 'pipe.jsonl')
        os.mkfifo(fifo)
        p = self.cli('collect.py', '--session', '--transcript', fifo, timeout=20)
        self.one_line(p)
        self.assertNotEqual(p.returncode, 0)

    def test_a_file_that_vanishes_during_the_read_is_one_error(self):
        spec = self.spec('codex')
        real = adapters.codex.read

        def vanishing(path, root=None):
            os.remove(path)
            return real(path, root)
        with mock.patch.object(adapters.codex, 'read', vanishing):
            with self.assertRaises(neutral.ExplainError) as cm:
                transcript.safe_path(spec.main)
        self.assertNotIn('\n', str(cm.exception))

    def test_a_mismatched_format_exits_1(self):
        spec = self.spec('codex')
        for fmt in ('copilot', 'gemini', 'cursor-ide', 'opencode', 'cursor-cli', 'claude'):
            p = self.cli('collect.py', '--session', '--transcript', spec.main, '--format', fmt)
            self.one_line(p)
            self.assertNotEqual(p.returncode, 0, fmt)
        p = self.cli('collect.py', '--session', '--transcript', spec.main, '--format', 'copilot')
        self.assertIn('is not a copilot transcript', p.stderr)
        self.assertEqual(p.returncode, 1)

    def test_an_unknown_format_name_is_refused(self):
        spec = self.spec('codex')
        p = self.cli('collect.py', '--session', '--transcript', spec.main, '--format', 'vim')
        self.assertEqual(p.returncode, 2)

    def test_a_sqlite_file_of_the_wrong_kind_is_refused_in_both_formats(self):
        spec = self.spec('opencode')
        db = spec.main.split('#')[0]
        p = self.cli('collect.py', '--session', '--transcript', db + '#ses_nope')
        self.assertNotEqual(p.returncode, 0)
        self.one_line(p)
        p = self.cli('collect.py', '--session', '--transcript', spec.main, '--format', 'cursor-ide')
        self.one_line(p, 1)


class NeutralModel(unittest.TestCase):
    """The parts the grounding walks, from a normalized session."""

    def result_of(self, tool):
        sess = adapters.Session('x', 's1')
        sess.add('tool_call', tool=tool)
        np = neutral.NPath('x')
        np.session = sess
        parts = list(neutral.iter_parts(neutral.session_files(np)['main'], transcript.Stats()))
        return [p for p in parts if p[2] == 'tool_result']

    def test_a_shell_call_with_no_output_or_no_exit_code_has_an_unknown_result(self):
        for out, code, unknown in ((None, 0, True), ('x', None, True), (None, None, True), ('x', 0, False), ('x', 1, False)):
            with self.subTest(output=out, exit_code=code):
                r = self.result_of(adapters.Tool('c1', 'sh', True, 'ls', out, code, code == 1))
                self.assertEqual(len(r), 1)
                self.assertEqual(r[0][4][2], unknown)

    def test_a_tool_that_is_not_a_shell_never_has_an_unknown_result(self):
        self.assertFalse(self.result_of(adapters.Tool('c1', 'read', False, None, 'text', None, False))[0][4][2])
        self.assertEqual(self.result_of(adapters.Tool('c1', 'read', False, None, None, None, False)), [])


class Docs(unittest.TestCase):
    """The harness table of README.md and references/transcripts.md is the table of the readers."""

    PATHS = (os.path.join(SKILL, 'references', 'transcripts.md'), os.path.join(os.path.dirname(os.path.dirname(SKILL)), 'README.md'))

    def rows(self, path):
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        return {m.group(3): m.group(2) for m in re.finditer(r'^\| ([^|]+) \| `([^`]+)`[^|]*\| `([a-z-]+)` \|$', text, re.M)}

    def test_each_row_names_the_folder_the_reader_uses(self):
        home = os.path.expanduser('~')
        for path in self.PATHS:
            rows = self.rows(path)
            self.assertEqual(sorted(rows), sorted(neutral.FORMATS), path)
            self.assertEqual(rows['claude'], '~/.claude/projects')
            for name, mod in adapters.ADAPTERS.items():
                want = mod.default_root().replace(home, '~', 1)
                if name == 'cursor-ide':
                    want = mod.default_root('linux').replace(home, '~', 1)
                self.assertEqual(rows[name], want, name)

    def test_the_docs_make_no_hedged_claims(self):
        for path in self.PATHS + (os.path.join(SKILL, 'SKILL.md'),):
            with open(path, encoding='utf-8') as fh:
                text = fh.read().lower()
            for word in ('unverified', 'experimental', 'planned'):
                self.assertNotIn(word, text, '%s in %s' % (word, path))


class ClaudeUnchanged(unittest.TestCase):
    def test_a_claude_transcript_outside_the_projects_folder_keeps_its_error(self):
        with tempfile.TemporaryDirectory(prefix='wire-claude-') as d:
            p = os.path.join(d, 't.jsonl')
            with open(p, 'w') as fh:
                fh.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'hello there'}}) + '\n')
            r = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'collect.py'), '--session', '--transcript', p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(r.stderr.strip(), 'error: transcript must be under %s (got %s)' % (transcript.projects_root(), p))

    def test_format_claude_never_reads_an_adapter(self):
        with tempfile.TemporaryDirectory(prefix='wire-home-') as h, mock.patch.dict(os.environ, {'HOME': h}):
            spec = build_codex(h)
            with self.assertRaises(neutral.ExplainError) as cm:
                transcript.safe_path(spec.main, 'claude')
            self.assertIn('transcript must be under', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
