"""Session mode: the explain-session/1 validator, the session digest (collect.py --session) and the shared grounding.
Each mutation of a valid doc must be rejected for its own reason; the digest is checked on a synthetic session under a throwaway projects root."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from helpers2 import rec, tool_result, write_jsonl  # noqa: E402
from helpers2 import tool_use as _tool_use  # noqa: E402
from lib import check_session, page_session, session, transcript  # noqa: E402
from sample_env import without_transcript  # noqa: E402

SKILL = os.path.join(os.path.dirname(HERE), 'skills', 'explain-change')
SAMPLE = os.path.join(SKILL, 'references', 'examples', 'portal-day.session.json')
SECRET = 'Zq9-fake-Cred7'  # synthetic, only for this test
U1, U2 = 'back up my settings to github please', 'fix the four polish items'
GH = 'cd /tmp/r && gh repo create notes-config --private --source . --remote origin'
PUSH = 'git -C /tmp/r push -u origin main'
FORCE = 'git -C /tmp/r push --force-with-lease origin main'
RM = 'rm -rf /tmp/build-1 && echo removed'
FAILED_PUSH = 'git push origin main'
FAILED_TEST = 'python3 -m unittest tests.test_polish'


def tool_use(tid, cmd, cwd=None):
    r = _tool_use(tid, cmd)
    if cwd:
        r['cwd'] = cwd
    return r


def main_records(secret=True):
    r = [
        rec('user', U1),
        rec('assistant', [{'type': 'text', 'text': 'There is no remote configured yet, so I create one.'}]),
        tool_use('g1', GH), tool_result('g1', 'Created repository epistex/notes-config on GitHub'),
        tool_use('g2', PUSH), tool_result('g2', "branch 'main' set up to track 'origin/main'"),
        rec('user', [{'type': 'text', 'text': '<system-reminder>injected block text</system-reminder>'}]),
        rec('user', 'This session is being continued from a previous conversation: compaction summary text', isCompactSummary=True),
        rec('user', U2),
        tool_use('g3', FORCE), tool_result('g3', 'forced update'),
        tool_use('g4', FAILED_PUSH, cwd='/work'), tool_result('g4', 'Exit code 1\nrejected: non-fast-forward', err=True),
        tool_use('g5', FAILED_TEST), tool_result('g5', 'Exit code 1\nFAILED (failures=1)', err=True),
        tool_use('g6', RM), tool_result('g6', 'removed'),
        rec('assistant', [{'type': 'text', 'text': 'all three hits are synthetic and went into an ignore file'}]),
    ]
    if secret:
        r.append(rec('user', 'the shared password: %s, change it later' % SECRET))
    return r


def worker_records():
    return [rec('user', 'brief from the orchestrator', isSidechain=True),
            tool_use('w1', 'git -C /tmp/r2 push -q origin main'), tool_result('w1', 'pushed to origin')]


def src_tool(cmd, excerpt):
    return {'kind': 'tool_call', 'command': cmd, 'excerpt': excerpt}


def good_doc():
    ask = {'kind': 'user_reported', 'quote': U1}
    return {
        'schema': 'explain-session/1', 'lang': 'en', 'title': 'A short day', 'summary': 'Two pieces of work are finished and one is in progress.',
        'themes': [
            {'id': 'backup', 'title': 'Config backup', 'status': 'done_needs_you', 'outcome': 'The settings are in a private repo.', 'events': [
                {'kind': 'asked', 'text': 'Back up the settings', 'order': 1, 'source': ask},
                {'kind': 'outward', 'text': 'Private repo created', 'order': 1, 'source': src_tool(GH, 'Created repository')},
                {'kind': 'outward', 'text': 'Pushed', 'order': 1, 'source': src_tool(PUSH, 'set up to track')}]},
            {'id': 'polish', 'title': 'Polish', 'status': 'done', 'outcome': 'The four polish items are done.', 'events': [
                {'kind': 'asked', 'text': 'Fix four items', 'order': 2, 'source': {'kind': 'user_reported', 'quote': U2}},
                {'kind': 'outward', 'text': 'Force-pushed', 'order': 2, 'source': src_tool(FORCE, 'forced update')},
                {'kind': 'done', 'text': 'Hits explained', 'order': 2, 'source': {'kind': 'report', 'quote': 'all three hits are synthetic'}}]},
            {'id': 'cleanup', 'title': 'Cleanup', 'status': 'in_progress', 'outcome': 'The build folder is gone.', 'events': [
                {'kind': 'outward', 'text': 'Build folder deleted', 'order': 2, 'source': src_tool(RM, 'removed')},
                {'kind': 'in_progress', 'text': 'Checking for leftovers', 'source': {'inferred': True}}]}],
        'needs_you': [{'text': 'Review the settings change', 'theme': 'backup', 'source': {'kind': 'user_reported', 'quote': 'change it later'}}],
        'decided': [{'text': 'Force-push on a fresh repo', 'reversible': False, 'theme': 'polish', 'source': src_tool(FORCE, 'forced update')}],
        'outward': [
            {'kind': 'repo_created', 'count': 1, 'themes': ['backup'], 'evidence': [src_tool(GH, 'Created repository')]},
            {'kind': 'push', 'count': 2, 'themes': ['backup'], 'evidence': [src_tool(PUSH, 'set up to track')]},
            {'kind': 'force_push', 'count': 1, 'themes': ['polish'], 'evidence': [src_tool(FORCE, 'forced update')]},
            {'kind': 'delete', 'count': 1, 'scratch': 1, 'themes': ['cleanup'], 'evidence': [src_tool(RM, 'removed')]}]}


class Case(unittest.TestCase):
    def setUp(self):
        transcript.forget()
        self.addCleanup(transcript.forget)
        self.tmp = tempfile.TemporaryDirectory(prefix='explain-session-')
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        os.environ['EXPLAIN_PROJECTS_DIR'] = self.root
        self.addCleanup(os.environ.pop, 'EXPLAIN_PROJECTS_DIR', None)
        self.transcript = os.path.join(self.root, '-fixture', 'sess1.jsonl')
        write_jsonl(self.transcript, main_records())
        write_jsonl(os.path.join(self.root, '-fixture', 'sess1', 'subagents', 'agent-abc123.jsonl'), worker_records())

    def validate(self, mutate=None, transcript_path=True):
        d = good_doc()
        if mutate:
            mutate(d)
        return check_session.validate(d, self.transcript if transcript_path is True else transcript_path)

    def rejects(self, mutate, needle, **kw):
        errs, _ = self.validate(mutate, **kw)
        self.assertTrue(any(needle in e for e in errs), 'expected %r in %r' % (needle, errs))
        return errs

    def off(self, mutate=None):
        def m(d):
            d['transcript_unavailable'] = 'synthetic'
            if mutate:
                mutate(d)
        return m


class Accepts(Case):
    def test_a_valid_doc_passes_with_the_transcript(self):
        errs, stats = self.validate()
        self.assertEqual(errs, [])
        self.assertEqual(stats['outward'], {'repo_created': 1, 'push': 2, 'force_push': 1, 'delete': 1})
        self.assertTrue(stats['transcript'])
        self.assertEqual(stats['not_compared'], 0)
        self.assertGreaterEqual(stats['verified_in_transcript'], 12)

    def test_the_shipped_sample_without_its_transcript_passes_with_checks_off(self):
        with open(SAMPLE, encoding='utf-8') as fh:
            doc = without_transcript(json.load(fh))
        with tempfile.TemporaryDirectory(prefix='sample-session-') as tmp:
            path = os.path.join(tmp, 'sample.session.json')
            shutil.copy(os.path.join(os.path.dirname(SAMPLE), 'password-autofill.v2.json'), tmp)  # the change doc its `login` theme links
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh)
            p = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'validate.py'), path], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('ok\nsession | themes 8', p.stdout)
        self.assertIn('transcript checks off', p.stdout)

    def test_without_a_transcript_a_reason_is_required(self):
        errs, _ = self.validate(None, transcript_path=None)
        self.assertTrue(any(e.startswith('transcript:') for e in errs), errs)
        errs, stats = self.validate(self.off(), transcript_path=None)
        self.assertEqual(errs, [])
        self.assertFalse(stats['transcript'])


class Mutations(Case):
    """The seven rejections of the done check, then the structure rules, one test each."""

    def test_unknown_status(self):
        self.rejects(lambda d: d['themes'][0].update(status='finished'), 'themes[0].status')

    def test_theme_without_events(self):
        self.rejects(lambda d: d['themes'][2].update(events=[]), 'themes[2].events')

    def test_dangling_needs_you_theme(self):
        self.rejects(lambda d: d['needs_you'][0].update(theme='ghost'), "needs_you[0].theme: no theme with id 'ghost'")

    def test_dangling_decided_theme(self):
        self.rejects(lambda d: d['decided'][0].update(theme='ghost'), 'decided[0].theme')

    def test_outward_count_that_differs_from_the_digest(self):
        errs = self.rejects(lambda d: d['outward'][1].update(count=3), 'push: the doc says 3, the transcript shows 2')
        self.assertEqual(len(errs), 1)

    def test_a_failed_push_is_not_in_the_digest(self):
        self.assertEqual(session.scan(self.transcript).counts()['push'], 2)  # g2 and the worker's; g4 was rejected
        self.rejects(lambda d: d['outward'][1].update(count=3), 'push')

    def test_outward_kind_in_the_transcript_but_not_in_the_doc(self):
        self.rejects(lambda d: d.update(outward=d['outward'][:3]), 'delete: 1 successful call(s) in the transcript but the doc does not list them')

    def test_done_backed_by_an_error_tool_call(self):
        self.rejects(lambda d: d['themes'][1]['events'][2].update(source=src_tool(FAILED_TEST, 'FAILED')), 'themes[1].events[2].kind: "done" rests on tool calls whose result is an error')

    def test_blocked_may_rest_on_an_error_tool_call(self):
        def m(d):
            d['themes'][1]['events'][2].update(kind='blocked', source=src_tool(FAILED_TEST, 'FAILED'))
        errs, _ = self.validate(m)
        self.assertEqual(errs, [])

    def test_done_backed_by_an_error_call_and_a_user_quote_stands(self):
        def m(d):
            d['themes'][1]['events'][2].update(source=[src_tool(FAILED_TEST, 'FAILED'), {'kind': 'user_reported', 'quote': U2}])
        errs, _ = self.validate(m)
        self.assertEqual(errs, [])

    def test_quote_missing_from_the_transcript(self):
        self.rejects(lambda d: d['themes'][0]['events'][0].update(source={'kind': 'user_reported', 'quote': 'a sentence nobody typed'}), 'quote not found')

    def test_a_user_quote_must_come_from_the_user(self):
        self.rejects(lambda d: d['themes'][0]['events'][0].update(source={'kind': 'user_reported', 'quote': 'no remote configured'}), 'quote not found')

    def test_tool_call_command_that_never_ran(self):
        self.rejects(lambda d: d['themes'][2]['events'][0].update(source=src_tool('rm -rf /tmp/other', 'removed')), 'command not found')

    def test_learned_secret_in_the_doc(self):
        errs = self.rejects(lambda d: d['themes'][0].update(outcome='Settings saved; the password is %s' % SECRET), 'contains a password, token or key that the session shows')
        self.assertFalse(any(SECRET in e for e in errs), errs)

    def test_learned_secret_in_a_key_or_a_source(self):
        errs = self.rejects(lambda d: d['themes'][0].update({SECRET: SECRET}), 'a key contains a password')
        self.assertFalse(any(SECRET in e for e in errs), errs)  # the key is part of the path in the error line
        self.rejects(lambda d: d['needs_you'][0].update(source={'kind': 'user_reported', 'quote': 'password: %s, change' % SECRET}), 'needs_you[0].source.quote: contains a password')

    def test_a_labelled_secret_is_refused_even_without_a_transcript(self):
        errs, _ = self.validate(self.off(lambda d: d['themes'][0].update(outcome='Reset it: password: Xy7!rareValue99')), transcript_path=None)
        self.assertTrue(any('looks like a password' in e for e in errs), errs)
        self.assertFalse(any('Xy7!rareValue99' in e for e in errs), errs)

    def test_schema_and_lang(self):
        self.rejects(lambda d: d.update(schema='explain-change/2'), 'schema')
        self.rejects(lambda d: d.update(lang='fr'), 'lang')

    def test_a_doc_that_is_not_an_object(self):
        self.assertEqual(check_session.validate([], None)[0], ['$: the doc must be an object'])

    def test_duplicate_theme_id(self):
        self.rejects(lambda d: d['themes'][1].update(id='backup'), 'duplicate theme id')

    def test_unknown_event_kind(self):
        self.rejects(lambda d: d['themes'][0]['events'][0].update(kind='celebrated'), 'events[0].kind')

    def test_a_code_source_is_not_accepted(self):
        self.rejects(lambda d: d['themes'][0]['events'][0].update(source={'kind': 'code', 'ref': {}}), 'source.kind')

    def test_event_without_a_source(self):
        def m(d):
            del d['themes'][0]['events'][0]['source']
        self.rejects(m, 'events[0].source')

    def test_events_must_follow_their_order(self):
        self.rejects(lambda d: d['themes'][0]['events'][2].update(order=0), 'events must be in order')

    def test_order_past_the_last_turn(self):
        self.rejects(lambda d: d['themes'][2]['events'][0].update(order=9), 'u9 does not exist')

    def test_order_must_be_the_turn_of_a_user_quote(self):
        self.rejects(lambda d: d['themes'][1]['events'][0].update(order=1), 'the user quote sits in turn(s) u2, not u1')

    def test_order_must_be_a_whole_number(self):
        self.rejects(lambda d: d['themes'][0]['events'][0].update(order='1'), 'events[0].order')

    def test_an_event_is_one_line(self):
        self.rejects(lambda d: d['themes'][0]['events'][0].update(text='two\nlines'), 'one line')

    def test_done_needs_you_wants_a_needs_you_item(self):
        self.rejects(lambda d: d.update(needs_you=[]), "theme 'backup' is done_needs_you")

    def test_outward_kind_listed_twice(self):
        self.rejects(lambda d: d['outward'].append(copy.deepcopy(d['outward'][0])), 'listed twice')

    def test_outward_theme_needs_an_outward_event(self):
        self.rejects(lambda d: d['outward'][0].update(themes=['backup', 'ghost']), "no theme with id 'ghost'")

        def m(d):
            d['themes'][1]['events'][1]['kind'] = 'done'
        self.rejects(m, "theme 'polish' has no event of kind outward")

    def test_outward_evidence_must_be_an_action_of_that_kind(self):
        self.rejects(lambda d: d['outward'][1].update(evidence=[src_tool(FORCE, 'forced update')]), 'this command is not a push action')

    def test_outward_needs_evidence_and_a_positive_count(self):
        self.rejects(lambda d: d['outward'][0].update(evidence=[]), 'outward[0].evidence')
        self.rejects(lambda d: d['outward'][0].update(count=0), 'outward[0].count')

    def test_blocks_are_required_lists(self):
        def m(d):
            del d['decided']
        self.rejects(m, 'decided: required list')

    def test_change_doc_is_a_relative_json_path(self):
        for bad in ('/etc/x.json', '../x.json', 'x.txt', '~/x.json'):
            with self.subTest(bad=bad):
                errs, _ = check_session.validate({**good_doc(), 'transcript_unavailable': 'x', 'themes': [{**good_doc()['themes'][0], 'change_doc': bad}]}, None)
                self.assertTrue(any('change_doc' in e for e in errs), errs)

    def test_change_doc_must_exist_and_be_a_change_doc(self):
        d = {**good_doc(), 'transcript_unavailable': 'x'}
        d['themes'][0]['change_doc'] = 'nothing.json'
        self.assertTrue(any('cannot read' in e for e in check_session.validate(d, None, base_dir=self.root)[0]))
        with open(os.path.join(self.root, 'other.json'), 'w') as fh:
            json.dump({'schema': 'explain-session/1'}, fh)
        d['themes'][0]['change_doc'] = 'other.json'
        self.assertTrue(any('not an explain-change/2' in e for e in check_session.validate(d, None, base_dir=self.root)[0]))


class IdTypes(Case):
    """An id-valued field that is a list, a dict, a number or null is a `path: reason` line and exit 1, never a traceback."""
    BAD = ([['backup']], {'a': 1}, 7, None)
    # (path into the doc, the needle the error line must contain)
    SITES = [
        (('themes', 0, 'id'), 'themes[0].id'), (('themes', 2, 'id'), 'themes[2].id'),
        (('themes', 0, 'status'), 'themes[0].status'), (('themes', 0, 'events', 1, 'kind'), 'events[1].kind'),
        (('needs_you', 0, 'theme'), 'needs_you[0].theme'), (('decided', 0, 'theme'), 'decided[0].theme'),
        (('outward', 0, 'themes', 0), 'outward[0].themes'), (('outward', 1, 'kind'), 'outward[1].kind'),
        (('outward', 3, 'themes', 0), 'outward[3].themes'), (('outward', 0, 'themes'), 'outward[0].themes'),
    ]

    def put(self, d, path, v):
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = v

    def run_cli(self, script, doc, *args):
        f = os.path.join(self.root, 'doc.json')
        with open(f, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh)
        p = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', script), f, '--transcript', self.transcript, *args],
                           capture_output=True, text=True, env=dict(os.environ))
        return p

    def assert_clean_fail(self, p, needle):
        self.assertNotIn('Traceback', p.stderr + p.stdout)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertTrue(any(needle in ln and ': ' in ln for ln in p.stdout.splitlines()), (needle, p.stdout))

    def test_a_list_as_needs_you_theme_names_the_value(self):
        self.rejects(lambda d: d['needs_you'][0].update(theme=['backup']), "needs_you[0].theme: no theme with id ['backup']")

    def test_a_list_as_decided_theme(self):
        self.rejects(lambda d: d['decided'][0].update(theme=['polish']), "decided[0].theme: no theme with id ['polish']")

    def test_a_list_in_outward_themes(self):
        self.rejects(lambda d: d['outward'][0].update(themes=[['x']]), "outward[0].themes: no theme with id ['x']")

    def test_a_theme_with_a_list_id_and_an_outward_event(self):
        self.rejects(lambda d: d['themes'][0].update(id=[]), 'themes[0].id: required non-empty string')

    def test_each_site_in_the_validator_and_both_scripts(self):
        for path, needle in self.SITES:
            for bad in self.BAD:
                with self.subTest(path=path, bad=bad):
                    d = good_doc()
                    self.put(d, path, copy.deepcopy(bad))
                    errs, _ = check_session.validate(d, self.transcript)  # raises on a TypeError
                    self.assertTrue(any(needle in e and ': ' in e for e in errs), (needle, errs))
        for path, needle in self.SITES[:2] + self.SITES[4:7]:
            for bad in self.BAD:
                with self.subTest(cli=path, bad=bad):
                    d = good_doc()
                    self.put(d, path, copy.deepcopy(bad))
                    self.assert_clean_fail(self.run_cli('validate.py', d), needle)
                    self.assert_clean_fail(self.run_cli('render.py', d, '--out', os.path.join(self.root, 'o.html')), needle)

    def test_every_value_of_the_doc_replaced_never_raises(self):
        def paths(o, pre=()):
            yield pre
            for k, v in (o.items() if isinstance(o, dict) else enumerate(o) if isinstance(o, list) else ()):
                yield from paths(v, pre + (k,))
        for path in paths(good_doc()):
            if not path:
                continue
            for bad in self.BAD + ('', True, -1, 1.5):
                d = good_doc()
                self.put(d, path, copy.deepcopy(bad))
                try:
                    check_session.validate(copy.deepcopy(d), self.transcript)
                    if not page_session.shape_problems(d):
                        page_session.render(d)
                except Exception as e:  # noqa: BLE001 - the point is that nothing raises
                    self.fail('%s = %r raised %s: %s' % ('.'.join(map(str, path)), bad, type(e).__name__, e))

    def test_no_validate_shape_check_survives_unhashable_ids(self):
        for path, _ in self.SITES:
            for bad in self.BAD:
                with self.subTest(path=path, bad=bad):
                    d = good_doc()
                    self.put(d, path, copy.deepcopy(bad))
                    p = self.run_cli('render.py', d, '--no-validate', '--out', os.path.join(self.root, 'o.html'))
                    self.assertNotIn('Traceback', p.stderr + p.stdout)
                    self.assertIn(p.returncode, (0, 1), p.stderr)
                    if p.returncode == 1:
                        self.assertTrue(any(': ' in ln for ln in p.stdout.splitlines()), p.stdout)


class Digest(Case):
    def run_collect(self, *args):
        return subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'collect.py'), '--session', *args], capture_output=True, text=True,
                              env={**os.environ, 'EXPLAIN_PROJECTS_DIR': self.root})

    def test_turns_are_numbered_and_injected_text_is_left_out(self):
        p = self.run_collect('--transcript', self.transcript)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('User turns (3, main transcript)', p.stdout)
        self.assertIn('[u1 ', p.stdout)
        self.assertIn(U2, p.stdout)
        self.assertNotIn('injected block text', p.stdout)
        self.assertNotIn('compaction summary text', p.stdout)
        self.assertNotIn('brief from the orchestrator', p.stdout)

    def test_outward_actions_carry_their_turn_and_failures_are_left_out(self):
        out = self.run_collect('--transcript', self.transcript).stdout
        self.assertIn('u1  repo_created  gh repo create', out)
        self.assertIn('u2  force_push  git push --force', out)
        self.assertIn('totals: repo_created 1, push 2, force_push 1, delete 1', out)
        self.assertIn('[agent-abc123]', out)

    def test_repos_touched_with_first_and_last_turn(self):
        out = self.run_collect('--transcript', self.transcript).stdout
        self.assertIn('/tmp/r  u1..u2  3', out)  # gh after `cd /tmp/r`, push -C, force push -C
        self.assertIn('/work  u2..u2  1', out)  # a git call with neither: the directory of its record
        self.assertIn('/tmp/r2  u3..u3  1', out)  # a worker's call, placed on the turn that was open at its time

    def test_work_between_turns_is_grouped(self):
        out = self.run_collect('--transcript', self.transcript).stdout
        self.assertIn('after u1: 2 calls (Bash 2)', out)
        self.assertIn('after u2: 4 calls (Bash 4)', out)

    def test_a_credential_in_a_message_is_masked(self):
        out = self.run_collect('--transcript', self.transcript).stdout
        self.assertNotIn(SECRET, out)
        self.assertIn(transcript.MASK, out)

    def test_a_path_outside_the_projects_folder_is_refused(self):
        p = self.run_collect('--transcript', '/etc/hostname')
        self.assertEqual(p.returncode, 1)  # a file no supported format recognises: exit 1, one line naming the formats
        self.assertIn('transcript must be under', p.stderr)
        self.assertEqual(len(p.stderr.strip().splitlines()), 1)
        self.assertIn('claude, ', p.stderr)

    def test_bad_lines_are_skipped_and_reported(self):
        with open(self.transcript, 'ab') as fh:
            fh.write(b'{not json\n\xff\xfe\n')
        p = self.run_collect('--transcript', self.transcript)
        self.assertEqual(p.returncode, 0)
        self.assertIn('skipped 2 of', p.stderr)

    def test_the_scan_keeps_short_excerpts_of_a_huge_message(self):
        write_jsonl(self.transcript, [rec('user', 'start ' + 'x' * 2_000_000)] + main_records()[1:])
        sc = session.scan(self.transcript)
        self.assertLessEqual(len(sc.users[0][2]), session.USER_CLIP)


class Grounding(Case):
    def test_v2_and_session_share_one_grounder(self):
        from lib import check2
        self.assertTrue(hasattr(check2, 'ground') and check2.ground is sys.modules['lib.ground'])
        self.assertIs(check_session.ground, check2.ground)


if __name__ == '__main__':
    unittest.main()
