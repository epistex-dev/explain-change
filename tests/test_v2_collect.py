import json
import os
import time
import tracemalloc
import unittest

from helpers2 import ARCH, PHPUNIT, USER_1, USER_2, V2Case, main_records, rec, tool_result, tool_use, write_jsonl
from lib import arch as A
from lib import transcript


class GlobSemantics(unittest.TestCase):
    def m(self, pattern, path):
        return bool(A.glob_regex(pattern).match(path))

    def test_double_star_single_star_question(self):
        self.assertTrue(self.m('src/**', 'src/a/b/c.js'))
        self.assertTrue(self.m('src/**', 'src/c.js'))
        self.assertTrue(self.m('src/*.js', 'src/c.js'))
        self.assertFalse(self.m('src/*.js', 'src/a/c.js'))
        self.assertTrue(self.m('**/*.test.js', 'c.test.js'))
        self.assertTrue(self.m('**/*.test.js', 'a/b/c.test.js'))
        self.assertTrue(self.m('src/?.js', 'src/a.js'))
        self.assertFalse(self.m('src/?.js', 'src/ab.js'))

    def test_alternation_and_plain_directory(self):
        self.assertTrue(self.m('x/*.{ts,tsx}', 'x/a.tsx'))
        self.assertFalse(self.m('x/*.{ts,tsx}', 'x/a.js'))
        self.assertTrue(self.m('backend/app', 'backend/app/Models/U.php'))
        self.assertTrue(self.m('backend/app', 'backend/app'))
        self.assertFalse(self.m('backend/app', 'backend/application/x'))

    def test_bracket_folder_names_are_literal(self):
        self.assertTrue(self.m('app/orders/[id]/**', 'app/orders/[id]/page.js'))
        self.assertFalse(self.m('app/orders/[id]/**', 'app/orders/5/page.js'))
        self.assertTrue(self.m('app/[...slug]/x.js', 'app/[...slug]/x.js'))

    def test_non_ascii_paths(self):
        self.assertTrue(self.m('tài-liệu/**', 'tài-liệu/ghi-chú.md'))


class Assignment(unittest.TestCase):
    def arch(self, nodes, **kw):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, d)
        os.makedirs(os.path.join(d, 'floorplan'))
        p = os.path.join(d, 'floorplan', 'architecture.json')
        with open(p, 'w') as fh:
            json.dump({'nodes': nodes, **kw}, fh)
        return A.Architecture(p)

    def test_deepest_node_wins(self):
        a = self.arch([{'id': 'p', 'paths': ['src/**']}, {'id': 'p.c', 'parent': 'p', 'paths': ['src/auth/**']}])
        self.assertEqual(a.assign('src/auth/x.js')[0], 'p.c')
        self.assertEqual(a.assign('src/other/x.js')[0], 'p')
        # depth beats a longer literal prefix and an earlier declaration
        b = self.arch([{'id': 'p', 'paths': ['src/auth/deep/**']}, {'id': 'c', 'parent': 'p', 'paths': ['src/**']}])
        self.assertEqual(b.assign('src/auth/deep/x.js')[0], 'c')

    def test_same_depth_longer_literal_prefix_wins(self):
        a = self.arch([{'id': 'a', 'paths': ['src/**']}, {'id': 'b', 'paths': ['src/auth/**']}])
        self.assertEqual(a.assign('src/auth/x.js'), ('b', {'ignored': False, 'candidates': ['b', 'a'], 'tie': None}))

    def test_real_tie_first_declared_wins_and_is_reported(self):
        a = self.arch([{'id': 'a', 'paths': ['src/**']}, {'id': 'b', 'paths': ['src/**']}])
        nid, info = a.assign('src/x.js')
        self.assertEqual((nid, info['tie']), ('a', ['a', 'b']))

    def test_exclude_is_inherited_by_children(self):
        a = self.arch([{'id': 'p', 'paths': ['src/**'], 'exclude': ['**/*.test.js']}, {'id': 'p.c', 'parent': 'p', 'paths': ['src/c/**']},
                       {'id': 't', 'paths': ['**/*.test.js']}])
        self.assertEqual(a.assign('src/c/x.test.js')[0], 't')
        self.assertEqual(a.assign('src/c/x.js')[0], 'p.c')

    def test_ignore_list_leaves_a_file_off_the_board(self):
        a = self.arch([{'id': 'a', 'paths': ['src/**']}], ignore=['src/gen/**'])
        nid, info = a.assign('src/gen/x.js')
        self.assertEqual((nid, info['ignored']), (None, True))

    def test_unclaimed_file_has_no_node(self):
        a = self.arch([{'id': 'a', 'paths': ['src/**']}])
        self.assertIsNone(a.assign('README.md')[0])

    def test_paths_are_relative_to_the_folder_that_holds_floorplan(self):
        a = self.arch([{'id': 'fe', 'paths': ['frontend/src/**']}])
        self.assertEqual(a.relpath(os.path.join(a.root, 'frontend'), 'src/a.js'), 'frontend/src/a.js')
        self.assertEqual(a.relpath(a.root, 'src/a.js'), 'src/a.js')

    def test_broken_architecture_file_is_an_error_not_a_crash(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, d)
        os.makedirs(os.path.join(d, 'floorplan'))
        with open(os.path.join(d, 'floorplan', 'architecture.json'), 'w') as fh:
            fh.write('{ nope')
        with self.assertRaises(A.ArchError):
            A.Architecture(os.path.join(d, 'floorplan', 'architecture.json'))


class CollectV2(V2Case):
    def test_plain_collect_output_is_unchanged_by_v2(self):
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('## Modules', r.stdout)
        self.assertNotIn('Transcript', r.stdout)

    def test_modules_are_mapped_and_unassigned_are_listed(self):
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--v2')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn('## Modules (source A:', out)
        self.assertIn('app.svc  Dịch vụ [feature]', out)
        self.assertIn('M +', out)
        self.assertIn('Unassigned (module id "_other"): logo.png', out)
        self.assertIn('unused  Không liên quan', out)  # unchanged neighbours offered
        self.assertIn('## Transcript candidates', out)
        run_dir = out.split('RUN_DIR=')[1].strip()
        with open(os.path.join(run_dir, 'summary.json'), encoding='utf-8') as fh:
            s = json.load(fh)
        self.assertEqual(s['modules']['assigned']['app/Svc.php'], 'app.svc')
        self.assertEqual(s['modules']['unassigned'], ['logo.png'])

    def test_fallback_when_no_architecture(self):
        os.remove(os.path.join(self.repo, 'floorplan', 'architecture.json'))
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--v2')
        self.assertIn('source B', r.stdout)
        self.assertIn('tài-liệu  (directory)', r.stdout)

    def test_overlap_is_reported(self):
        arch = json.loads(json.dumps(ARCH))
        arch['nodes'].append({'id': 'dup', 'label': 'Trùng', 'kind': 'library', 'summary': 'x', 'paths': ['tests/**']})
        self.write_arch(arch)
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--v2')
        self.assertIn('OVERLAP: tests/SvcTest.php matches tests, dup equally; first declared wins -> tests', r.stdout)

    def test_empty_range_still_exits_3_with_v2(self):
        r = self.script('collect.py', 'HEAD..HEAD', '--repo', self.repo, '--v2')
        self.assertEqual(r.returncode, 3)

    def test_broken_architecture_is_a_clear_error(self):
        with open(os.path.join(self.repo, 'floorplan', 'architecture.json'), 'w') as fh:
            fh.write('{ nope')
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--v2')
        self.assertEqual(r.returncode, 2)
        self.assertIn('architecture.json', r.stderr)
        self.assertNotIn('Traceback', r.stderr)

    def test_digest_has_user_messages_and_test_calls(self):
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--transcript', self.transcript)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn('[u1 ', out)
        self.assertIn(USER_1, out)
        self.assertIn(USER_2, out)
        self.assertNotIn('fake request', out)  # delegated / notification messages are not the user
        self.assertNotIn('secret quote inside context', out)
        self.assertIn('$ ' + PHPUNIT, out)
        self.assertIn('OK (1 test, 1 assertion)', out)
        self.assertIn('[agent-abc123', out)  # worker transcripts are part of the session
        self.assertIn('pytest -q tests/test_worker.py', out)
        self.assertNotIn('curl -s', out)  # not test-like

    def test_digest_flags_errors_and_failed_exit(self):
        recs = main_records()[:1] + [tool_use('f1', 'npm run test'), tool_result('f1', 'Exit code 1\n3 failed', err=True)]
        write_jsonl(self.transcript, recs)
        text, _ = transcript.digest(self.transcript)
        self.assertIn('-> ERROR', text)

    def test_credentials_are_hidden_in_the_digest(self):
        recs = [rec('user', 'đăng nhập thử: admin@x.vn\nPass chung: Zq7!synthetic-91 nhé'), tool_use('c1', 'curl -H "Authorization: Bearer abcdefghijkl123" https://x/test && echo token=glpat-AAAAAAAAAAAA')]
        write_jsonl(self.transcript, recs)
        text, _ = transcript.digest(self.transcript)
        self.assertNotIn('Zq7!synthetic-91', text)
        self.assertNotIn('abcdefghijkl123', text)
        self.assertNotIn('glpat-AAAAAAAAAAAA', text)
        self.assertIn('Pass chung: [ẩn]', text)
        self.assertIn('đăng nhập thử: admin@x.vn', text)

    def test_runner_commands_rank_above_file_reading_ones(self):
        recs = [tool_use('r1', 'git show origin/dev:tests/a.test.js | head'), tool_use('r2', 'cat tests/b.test.js'), tool_use('r3', 'echo build ok'),
                tool_use('r4', 'make build docs'), tool_use('r5', 'npx vitest run tests/a.test.js'), tool_result('r5', '1 passed')]
        write_jsonl(self.transcript, recs)
        text, _ = transcript.digest(self.transcript)
        strong, weak = text.split('Other commands that mention')
        self.assertIn('npx vitest run', strong)
        self.assertNotIn('git show', text)  # read-only exploration is dropped
        self.assertNotIn('cat tests', text)
        self.assertIn('make build docs', weak)

    def test_transcript_outside_projects_is_refused_by_collect(self):
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--transcript', os.path.join(self.repo, 'x.jsonl'))
        self.assertEqual(r.returncode, 2)
        self.assertIn('must be under', r.stderr)

    def test_digest_is_capped(self):
        recs = [rec('user', 'câu số %d ' % i + 'dài ' * 60) for i in range(800)] + [tool_use('c%d' % i, 'npm run test %d' % i) for i in range(1)]
        write_jsonl(self.transcript, recs)
        text, _ = transcript.digest(self.transcript)
        self.assertLess(len(text), transcript.DIGEST_CAP + 3000)
        self.assertIn('omitted here', text)
        self.assertIn('câu số 799', text)  # the latest are kept
        self.assertIn('câu số 0 ', text)  # and the first

    def test_digest_of_a_big_file_streams(self):
        recs = [rec('assistant', [{'type': 'text', 'text': 'x' * 80}]) for _ in range(50000)]
        write_jsonl(self.transcript, main_records() + recs, extra_raw=[b'\xff\xfe', b'{bad'])
        t0 = time.time()
        tracemalloc.start()
        text, warns = transcript.digest(self.transcript)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        self.assertLess(time.time() - t0, 20)
        self.assertLess(peak, os.path.getsize(self.transcript) // 4, 'the transcript must be read line by line, not loaded whole')
        self.assertTrue(any('skipped 2' in w for w in warns), warns)
        self.assertIn(USER_1, text)


class Candidates(V2Case):
    def setUp(self):
        super().setUp()
        self.slug = transcript.slug_variants(self.repo)
        self.pdir = os.path.join(self.root, sorted(self.slug)[0])
        os.makedirs(self.pdir)

    def session(self, name, first, mtime):
        p = os.path.join(self.pdir, name + '.jsonl')
        write_jsonl(p, [rec('user', first, ts='2026-10-28T09:00:00.000Z'), rec('assistant', [{'type': 'text', 'text': 'ok'}], ts='2026-10-28T09:30:00.000Z')])
        os.utime(p, (mtime, mtime))
        return p

    def test_top_three_by_mtime_with_first_message_and_span(self):
        now = time.time()
        for i, n in enumerate(['a', 'b', 'c', 'd']):
            self.session(n, 'tin nhắn đầu của %s' % n, now - 1000 + i * 100)
        c = transcript.candidates(self.repo)
        self.assertEqual([os.path.basename(x['path']) for x in c], ['d.jsonl', 'c.jsonl', 'b.jsonl'])
        self.assertEqual(c[0]['first_user'], 'tin nhắn đầu của d')
        self.assertEqual((c[0]['start'], c[0]['end']), ('2026-10-28T09:00:00.000Z', '2026-10-28T09:30:00.000Z'))
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo)
        self.assertEqual(r.returncode, 0)
        r = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--v2')
        self.assertIn('1. ' + c[0]['path'], r.stdout)
        self.assertIn('first user message: tin nhắn đầu của d', r.stdout)
        self.assertNotIn('a.jsonl', r.stdout)

    def test_slug_matches_case_insensitively_and_in_parents(self):
        os.rename(self.pdir, os.path.join(self.root, sorted(self.slug)[0].upper()))
        self.pdir = os.path.join(self.root, sorted(self.slug)[0].upper())
        self.session('x', 'chạy ở thư mục cha', time.time())
        self.assertEqual(len(transcript.candidates(self.repo)), 1)
        sub = os.path.join(self.repo, 'sub')
        os.makedirs(sub)
        self.assertEqual(len(transcript.candidates(sub)), 1)  # session recorded one level up

    def test_nothing_outside_projects_is_listed_or_read(self):
        self.assertEqual(transcript.candidates('/'), [])
        os.environ['EXPLAIN_PROJECTS_DIR'] = os.path.join(self.root, 'does-not-exist')
        self.assertEqual(transcript.candidates(self.repo), [])

    def test_subagent_transcripts_are_not_candidates(self):
        self.session('only', 'duy nhất', time.time())
        os.makedirs(os.path.join(self.pdir, 'only', 'subagents'))
        write_jsonl(os.path.join(self.pdir, 'only', 'subagents', 'agent-x1.jsonl'), [rec('user', 'worker')])
        c = transcript.candidates(self.repo)
        self.assertEqual(len(c), 1)
        self.assertEqual(c[0]['subagents'], 1)


if __name__ == '__main__':
    unittest.main()
