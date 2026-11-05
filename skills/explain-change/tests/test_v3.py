"""Fix round 3: the map for a repo with no floorplan, --path scope, --slug and run folder name, no v1 hints in v2 output,
digest priority, `_other` rule, rationale `report` source, masked credentials in the digest, file rows on the page."""
import json
import os
import re
import secrets
import subprocess
import unittest

from helpers2 import USER_1, V2Case, main_records, rec, run, tool_result, tool_use, worker_records, write_jsonl
from lib import arch as A
from lib import gitio, page2, transcript
from test_v2 import drop_module_refs

SELF_FILES = [
    'skills/explain-change/DESIGN.md',
    'skills/explain-change/SKILL.md',
    'skills/explain-change/assets/ui/LICENSES.txt',
    'skills/explain-change/assets/ui/fonts/inter-latin.woff2',
    'skills/explain-change/assets/ui/fonts/inter-vietnamese.woff2',
    'skills/explain-change/assets/ui/fonts/jetbrains-mono-latin.woff2',
    'skills/explain-change/assets/ui/icons.svg',
    'skills/explain-change/assets/ui/page2.css',
    'skills/explain-change/assets/ui/page2.js',
    'skills/explain-change/assets/ui/route.js',
    'skills/explain-change/reference/examples/password-autofill.v2.json',
    'skills/explain-change/reference/ui/LICENSES.txt',
    'skills/explain-change/reference/ui/layout-2.html',
    'skills/explain-change/reference/ui/layout-2.notes.md',
    'skills/explain-change/reference/ui/shots/floorplan-1440x900.png',
    'skills/explain-change/reference/ui/shots/v3-layout2-1440-node-selected.png',
    'skills/explain-change/reference/ui/shots/v3-layout2-1440.png',
    'skills/explain-change/reference/ui/shots/v3-layout2-800.png',
    'skills/explain-change/reference/ui/theme.css',
    'skills/explain-change/references/explain-schema.md',
    'skills/explain-change/scripts/collect.py',
    'skills/explain-change/scripts/lib/arch.py',
    'skills/explain-change/scripts/lib/check.py',
    'skills/explain-change/scripts/lib/check2.py',
    'skills/explain-change/scripts/lib/collect2.py',
    'skills/explain-change/scripts/lib/i18n2.py',
    'skills/explain-change/scripts/lib/page2.py',
    'skills/explain-change/scripts/lib/transcript.py',
    'skills/explain-change/scripts/render.py',
    'skills/explain-change/scripts/validate.py',
    'skills/explain-change/tests/fixtures/geometry-fixture-1440.json',
    'skills/explain-change/tests/fixtures/geometry-fixture-800.json',
    'skills/explain-change/tests/fixtures/geometry-autofill-1440.json',
    'skills/explain-change/tests/fixtures/geometry-autofill-800.json',
    'skills/explain-change/tests/helpers2.py',
    'skills/explain-change/tests/red_check.py',
    'skills/explain-change/tests/route_driver.js',
    'skills/explain-change/tests/test_render2.py',
    'skills/explain-change/tests/test_route.py',
    'skills/explain-change/tests/test_v2.py',
    'skills/explain-change/tests/test_v2_collect.py',
    'skills/explain-change/tests/test_v2_hardening.py',
]


FAKE_CRED = 'Zq9-fake-Cred7'  # synthetic, only for this test


def ids(paths):
    return sorted(set(A.fallback_modules(paths).values()))


class FallbackRule(unittest.TestCase):
    def test_the_self_run_file_list_scoped_gives_three_to_eight_modules(self):
        got = ids(SELF_FILES)
        self.assertTrue(3 <= len(got) <= 8, got)
        self.assertIn('tests', got)
        self.assertIn('scripts', got)

    def test_the_self_run_whole_range_no_longer_piles_into_one_node(self):
        files = SELF_FILES + ['CLAUDE.md', 'agents/worker.md', 'agents/worker-leaf.md', 'hooks/guard.sh', 'hooks/orch-guard.py',
                              'hooks/tests/test_guard.py', 'hooks/tests/test_orch_guard.py', 'hooks/git/pre-commit', 'orchestrator/ui.md', 'orchestrator/work.md']
        mods = A.fallback_modules(files)
        got = sorted(set(mods.values()))
        self.assertTrue(3 <= len(got) <= 8, got)
        by = {}
        for p, m in mods.items():
            by.setdefault(m, []).append(p)
        self.assertLessEqual(max(len(v) for v in by.values()) / len(files), 0.6)

    def test_flat_files_give_dot_plus_top_directories(self):
        self.assertEqual(A.fallback_modules(['a.py', 'b.py', 'src/x.py', 'src/y.py', 'docs/z.md']),
                         {'a.py': '.', 'b.py': '.', 'src/x.py': 'src', 'src/y.py': 'src', 'docs/z.md': 'docs'})

    def test_a_single_file_is_one_module(self):
        self.assertEqual(A.fallback_modules(['pkg/deep/one.py']), {'pkg/deep/one.py': '.'})
        self.assertEqual(A.fallback_modules(['one.py']), {'one.py': '.'})

    def test_ids_are_relative_to_the_deepest_common_directory(self):
        got = A.fallback_modules(['svc/a/x.py', 'svc/a/y.py', 'svc/b/z.py', 'svc/w.py'])
        self.assertEqual(got, {'svc/a/x.py': 'a', 'svc/a/y.py': 'a', 'svc/b/z.py': 'b', 'svc/w.py': '.'})
        self.assertEqual(A.fallback_root(['svc/a/x.py', 'svc/b/z.py']), 'svc')
        self.assertEqual(A.fallback_root(['a.py', 'b/c.py']), '')

    def test_a_directory_with_most_files_is_split_by_its_children(self):
        files = ['top.py', 'core/m1.py', 'core/m2.py'] + ['core/sub/s%d.py' % i for i in range(4)] + ['ui/a.py', 'ui/b.py']
        got = A.fallback_modules(files)
        self.assertEqual(got['core/sub/s0.py'], 'core/sub')
        self.assertEqual(got['core/m1.py'], 'core')
        self.assertEqual(got['ui/a.py'], 'ui')

    def test_a_single_file_leftover_joins_its_parent(self):
        files = ['top.py', 'pkg/one.py'] + ['pkg/lib/f%d.py' % i for i in range(8)]
        got = A.fallback_modules(files)
        self.assertEqual(got['pkg/one.py'], '.')  # not a module of its own
        self.assertEqual(got['pkg/lib/f0.py'], 'pkg/lib')

    def test_never_more_than_eight_modules_and_the_result_does_not_depend_on_order(self):
        files = ['d%d/f.py' % i for i in range(12)] + ['d%d/g.py' % i for i in range(3)]
        got = ids(files)
        self.assertLessEqual(len(got), 8, got)
        self.assertEqual(A.fallback_modules(files), A.fallback_modules(list(reversed(files))))
        self.assertEqual(set(A.fallback_modules(files)), set(files))


class FallbackValidation(V2Case):
    """No floorplan: the validator and collect.py --v2 use one function, so the doc's module ids match."""

    def setUp(self):
        super().setUp()
        os.remove(os.path.join(self.repo, 'floorplan', 'architecture.json'))
        for i in range(5):
            self.write('pkg/core/m%d.py' % i, 'x = %d\n' % i)
        self.write('pkg/ui/a.py', 'a = 1\n')
        self.write('pkg/top.py', 't = 1\n')
        self.commit('pkg files')
        self.head2 = self.rev('HEAD')

    def collect(self, *extra):
        r = self.script('collect.py', '%s..%s' % (self.base, self.head2), '--repo', self.repo, '--v2', *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        run_dir = r.stdout.split('RUN_DIR=')[1].strip()
        with open(os.path.join(run_dir, 'summary.json'), encoding='utf-8') as fh:
            return r, run_dir, json.load(fh)

    def doc_for(self, summary):
        d = self.good_doc()
        drop_module_refs(d)
        d['range']['head'] = self.head2
        groups = summary['modules']['groups']
        d['map']['modules'] = [{'id': mid, 'name': mid, 'summary': 'Phần %s.' % mid, 'changed': True, 'what_changed': 'Đổi.',
                                'files': [self.counts_h(p) for p in ps]} for mid, ps in groups.items()]
        d['map']['edges'] = []
        return d

    def counts_h(self, path):
        f = {x['path']: x for x in gitio.changed_files(self.repo, self.base, self.head2)}[path]
        return {'path': path, 'add': f['add'], 'del': f['del']}

    def run_validate(self, d, run_dir):
        p = os.path.join(run_dir, 'explain.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, ensure_ascii=False)
        return self.script('validate.py', p, '--repo', self.repo, '--transcript', self.transcript)

    def test_collect_ids_are_the_ids_the_validator_wants(self):
        r, run_dir, s = self.collect('--path', 'pkg')
        self.assertIn('core', s['modules']['groups'])
        self.assertIn('ui', s['modules']['groups'])
        d = self.doc_for(s)
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)

    def test_a_module_id_the_rule_does_not_give_is_refused(self):
        _, run_dir, s = self.collect('--path', 'pkg')
        d = self.doc_for(s)
        d['map']['modules'][0]['id'] = 'nodir'
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 1)
        self.assertIn('is not a module of the directory map', v.stdout)

    def test_an_unchanged_neighbour_must_be_a_directory_that_exists(self):
        _, run_dir, s = self.collect('--path', 'pkg')
        d = self.doc_for(s)
        d['map']['modules'].append({'id': 'ui', 'name': 'x', 'summary': 'x', 'changed': False})  # dup of a changed module
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 1)
        self.assertIn('duplicate module id', v.stdout)
        d = self.doc_for(s)
        d['map']['modules'].append({'id': 'ghost', 'name': 'x', 'summary': 'x', 'changed': False})
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 1)
        self.assertIn('exists at head', v.stdout)

    def test_other_is_refused_without_an_architecture_and_the_message_says_path(self):
        _, run_dir, s = self.collect('--path', 'pkg')
        d = self.doc_for(s)
        d['map']['modules'][0]['id'] = '_other'
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 1)
        self.assertIn('_other', v.stdout)
        self.assertIn('--path', v.stdout)

    def legacy_doc(self, s):
        """A doc built on the old rule: one module per top directory of the repo ('pkg' holds every file)."""
        d = self.doc_for(s)
        files = [f for m in d['map']['modules'] for f in m['files']]
        d['map']['modules'] = [{'id': 'pkg', 'name': 'pkg', 'summary': 'Gói.', 'changed': True, 'what_changed': 'Đổi.', 'files': files}]
        return d

    def test_a_legacy_top_directory_doc_still_validates_and_renders(self):
        _, run_dir, s = self.collect('--path', 'pkg')
        d = self.legacy_doc(s)
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertIn('legacy top-directory ids', v.stdout)
        r = self.script('render.py', os.path.join(run_dir, 'explain.json'), '--repo', self.repo, '--transcript', self.transcript)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(run_dir, 'index.html')))

    def test_a_legacy_unchanged_neighbour_is_a_top_directory_that_exists(self):
        _, run_dir, s = self.collect('--path', 'pkg')
        d = self.legacy_doc(s)
        d['map']['modules'].append({'id': 'app', 'name': 'app', 'summary': 'Code.', 'changed': False})
        self.assertEqual(self.run_validate(d, run_dir).returncode, 0)
        d['map']['modules'][1]['id'] = 'ghost'
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 1)
        self.assertIn('exists at head', v.stdout)

    def test_a_doc_that_mixes_legacy_and_current_ids_fails(self):
        _, run_dir, s = self.collect('--path', 'pkg')
        d = self.legacy_doc(s)
        files = d['map']['modules'][0]['files']
        ui = [f for f in files if f['path'] == 'pkg/ui/a.py']
        d['map']['modules'][0]['files'] = [f for f in files if f not in ui]
        d['map']['modules'].append({'id': 'ui', 'name': 'ui', 'summary': 'UI.', 'changed': True, 'what_changed': 'Mới.', 'files': ui})
        v = self.run_validate(d, run_dir)
        self.assertEqual(v.returncode, 1)
        self.assertIn('belongs to module', v.stdout)
        d = self.legacy_doc(s)  # legacy changed ids with a current-rule neighbour id
        d['map']['modules'].append({'id': 'pkg/core', 'name': 'x', 'summary': 'x', 'changed': False})
        self.assertEqual(self.run_validate(d, run_dir).returncode, 1)

    def test_the_schema_says_the_same_as_the_validator(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'references', 'explain-schema.md'), encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('`_other` is allowed only with an architecture', text)
        self.assertIn('--path', text)
        self.assertIn('60%', text)
        self.assertIn('legacy top-directory', text)
        self.assertIn('summary.json', text)


class Pathspec(unittest.TestCase):
    def test_paths_come_after_double_dash_as_literals(self):
        self.assertEqual(gitio.pathspecs(['a b', 'x']), ['--', ':(literal)a b', ':(literal)x'])
        self.assertEqual(gitio.pathspecs([]), [])


class Scope(V2Case):
    def collect(self, *extra, rng=None):
        return self.script('collect.py', rng or '%s..%s' % (self.base, self.head), '--repo', self.repo, '--v2', *extra)

    def summary_of(self, r):
        run_dir = r.stdout.split('RUN_DIR=')[1].strip()
        with open(os.path.join(run_dir, 'summary.json'), encoding='utf-8') as fh:
            return run_dir, json.load(fh)

    def test_path_limits_the_diff_and_is_stored(self):
        r = self.collect('--path', 'app')
        self.assertEqual(r.returncode, 0, r.stderr)
        run_dir, s = self.summary_of(r)
        self.assertEqual(sorted(f['path'] for f in s['files']), ['app/Old.php', 'app/Svc.php'])
        self.assertEqual(s['scope'], ['app'])
        with open(os.path.join(run_dir, 'diff.patch'), encoding='utf-8') as fh:
            patch = fh.read()
        self.assertIn('app/Svc.php', patch)
        self.assertNotIn('tests/SvcTest.php', patch)
        self.assertNotIn('SvcTest', r.stdout.split('## Modules')[0].split('## Files')[1])

    def test_path_is_repeatable_and_a_path_with_spaces_and_non_ascii_works(self):
        self.write('my dir/file one.txt', 'x\n')
        self.commit('spaces')
        head = self.rev('HEAD')
        r = self.collect('--path', 'my dir', '--path', 'tài-liệu', rng='%s..%s' % (self.base, head))
        self.assertEqual(r.returncode, 0, r.stderr)
        _, s = self.summary_of(r)
        self.assertEqual(sorted(f['path'] for f in s['files']), ['my dir/file one.txt', 'tài-liệu/ghi-chú.md'])
        self.assertEqual(s['scope'], ['my dir', 'tài-liệu'])

    def test_a_glob_character_in_a_path_is_literal(self):
        r = self.collect('--path', 'app/*')
        self.assertEqual(r.returncode, 3)

    def test_unsafe_paths_are_refused_and_nothing_is_written(self):
        for bad in ('--path=-x', '--path=--output=/tmp/x', '--path=../outside', '--path=/etc', '--path=app/../../x', '--path=.'):
            r = self.collect(bad)
            self.assertEqual(r.returncode, 2, (bad, r.stdout, r.stderr))
            self.assertIn('--path', r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, '.explain')))

    def test_an_absolute_path_inside_the_repo_is_stored_relative(self):
        r = self.collect('--path', os.path.join(self.repo, 'app'))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.summary_of(r)[1]['scope'], ['app'])

    def test_validate_wants_only_the_in_scope_files_on_the_map(self):
        r = self.collect('--path', 'app')
        run_dir, _ = self.summary_of(r)
        d = self.good_doc()
        drop_module_refs(d)
        d['map']['modules'] = [m for m in d['map']['modules'] if m['id'] in ('browser', 'app.svc', 'app', 'db')]
        d['map']['edges'] = [e for e in d['map']['edges'] if e['to'] != 'tests']
        p = os.path.join(run_dir, 'explain.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, ensure_ascii=False)
        v = self.script('validate.py', p, '--repo', self.repo, '--transcript', self.transcript)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        # without the scope in summary.json the same doc leaves three changed files unassigned
        _, s = self.summary_of(r)
        s.pop('scope')
        with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as fh:
            json.dump(s, fh)
        v = self.script('validate.py', p, '--repo', self.repo, '--transcript', self.transcript)
        self.assertEqual(v.returncode, 1)
        self.assertIn('changed file not assigned', v.stdout)

    def test_a_file_outside_the_scope_on_the_map_is_refused(self):
        r = self.collect('--path', 'app')
        run_dir, _ = self.summary_of(r)
        d = self.good_doc()
        drop_module_refs(d)
        p = os.path.join(run_dir, 'explain.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, ensure_ascii=False)
        v = self.script('validate.py', p, '--repo', self.repo, '--transcript', self.transcript)
        self.assertEqual(v.returncode, 1)
        self.assertIn('not a changed file', v.stdout)


class RunFolderName(V2Case):
    def setUp(self):
        super().setUp()
        self.write('app/Extra.php', '<?php\n')
        self.commit('chung một việc')
        self.write('tests/Other.php', '<?php\n')
        self.commit('phiên khác làm việc khác')
        self.write('app/Extra2.php', '<?php\n')
        self.commit('chung một việc')
        self.write('app/Extra3.php', '<?php\n')
        self.commit('việc riêng lẻ mới nhất')
        self.write('docs/readme.md', 'x\n')
        self.commit('phiên khác lại commit')
        self.top = self.rev('HEAD')

    def folder(self, *extra):
        r = self.script('collect.py', '%s..%s' % (self.base, self.top), '--repo', self.repo, *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return os.path.basename(r.stdout.split('RUN_DIR=')[1].strip())

    def test_slug_flag_names_the_folder_and_keeps_the_timestamp(self):
        name = self.folder('--slug', 'Giải thích v2!')
        self.assertTrue(re.fullmatch(r'\d{8}-\d{4}-giai-thich-v2', name), name)

    def test_without_a_slug_the_most_common_subject_among_in_scope_commits_names_it(self):
        self.assertTrue(self.folder('--path', 'app').endswith('-chung-mot-viec'))

    def test_a_commit_that_misses_the_scope_does_not_name_the_folder(self):
        self.assertTrue(self.folder('--path', 'docs').endswith('-phien-khac-lai-commit'))

    def test_tie_goes_to_the_newest_commit(self):
        self.assertTrue(self.folder('--path', 'tests').endswith('-phien-khac-lam-viec-khac'))


class NoV1Hints(V2Case):
    def test_v2_output_has_no_explain_in_hint_and_v1_keeps_it(self):
        r1 = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo)
        self.assertIn('Logic bên trong', r1.stdout)
        r2 = self.script('collect.py', '%s..%s' % (self.base, self.head), '--repo', self.repo, '--v2')
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertNotIn('Logic bên trong', r2.stdout)
        self.assertNotIn('sub-change', r2.stdout)
        self.assertIn('branches=', r2.stdout)


class DigestPriority(V2Case):
    STRONG = ['python3 -m unittest discover -s tests', 'python3 tests/red_check.py', 'python3 -I tools/prove_fix.py --repo r --base b',
              'pytest -q tests/test_x.py', 'npm run lint']

    def test_strong_runs_in_workers_survive_two_hundred_noise_calls(self):
        noise = []
        for i in range(200):
            noise += [tool_use('n%d' % i, "python3 - <<'EOF'\nprint('npm run lint unittest test %d ' + 'x' * 600)\nEOF" % i), tool_result('n%d' % i, 'out %d ' % i + 'y' * 300)]
        write_jsonl(self.transcript, main_records() + noise)
        wdir = os.path.join(self.root, '-fixture', 'sess1', 'subagents')
        for k, c in enumerate(self.STRONG):
            write_jsonl(os.path.join(wdir, 'agent-s%d.jsonl' % k), [tool_use('s%d' % k, c), tool_result('s%d' % k, 'result of strong run %d: OK' % k)])
        text, _ = transcript.digest(self.transcript)
        for c in self.STRONG:
            self.assertIn(c, text)
        self.assertLess(len(text), transcript.DIGEST_CAP + 3000)
        strong_part = text.split('Other commands')[0]
        for c in self.STRONG:
            self.assertIn(c, strong_part)  # in the first list, not the low-priority one
        self.assertNotIn("python3 - <<'EOF'", strong_part)

    def test_strong_runs_take_the_budget_before_weaker_ones(self):
        strong = [tool_use('s%d' % i, 'pytest -q tests/test_%02d.py ' % (i, ) + '-k ' + 'abc' * 20) for i in range(33)]
        weak = [tool_use('w%d' % i, 'echo test %d' % i) for i in range(3)]
        recs = []
        for i, r in enumerate(strong):
            recs += [r, tool_result('s%d' % i, 'run %d ' % i + 'r' * 300 + ' end %d' % i)]
        for i, r in enumerate(weak):
            recs += [r, tool_result('w%d' % i, 'weak out')]
        write_jsonl(self.transcript, main_records() + recs)
        text, _ = transcript.digest(self.transcript)
        self.assertGreater(len(text.split('Other commands')[0]), 10500 + 3000, 'the strong list is bigger than the old 35% share')
        for i in range(33):
            self.assertIn('tests/test_%02d.py' % i, text)
        self.assertNotIn('omitted here', text.split('Other commands')[0].split('Test, lint, build')[1])
        self.assertLess(len(text), transcript.DIGEST_CAP + 3000)

    def test_reading_a_runner_file_is_not_running_it(self):
        recs = [tool_use('r1', 'sed -n 1,9p tests/red_check.py | cut -c1-80'), tool_result('r1', 'text of the file'),
                tool_use('r2', 'head -30 scripts/check.mjs | grep -n import'), tool_result('r2', 'imports'),
                tool_use('r3', 'cd x && python3 tests/red_check.py'), tool_result('r3', '225 guards, 0 not proven')]
        write_jsonl(self.transcript, main_records() + recs)
        text, _ = transcript.digest(self.transcript)
        strong, weak = text.split('Other commands')
        self.assertIn('python3 tests/red_check.py', strong)
        self.assertNotIn('sed -n 1,9p', strong)
        self.assertNotIn('head -30', strong)
        self.assertNotIn('sed -n 1,9p', text)  # a reader is not a candidate at all

    def test_runs_are_listed_by_time_not_by_transcript_file(self):
        early = rec('assistant', [{'type': 'tool_use', 'id': 'e1', 'name': 'Bash', 'input': {'command': 'pytest -q early'}}], ts='2026-10-28T09:00:00.000Z')
        late = rec('assistant', [{'type': 'tool_use', 'id': 'l1', 'name': 'Bash', 'input': {'command': 'pytest -q late'}}], ts='2026-10-28T18:00:00.000Z')
        write_jsonl(self.transcript, main_records() + [late, tool_result('l1', 'late ok')])
        write_jsonl(os.path.join(self.root, '-fixture', 'sess1', 'subagents', 'agent-abc123.jsonl'), [early, tool_result('e1', 'early ok')])
        text, _ = transcript.digest(self.transcript)
        self.assertLess(text.index('pytest -q early'), text.index('pytest -q late'))

    def test_an_inline_script_that_runs_a_test_runner_is_still_strong(self):
        write_jsonl(self.transcript, main_records() + [tool_use('h1', "cd x && pytest -q <<'EOF'\nEOF"), tool_result('h1', 'ok')])
        text, _ = transcript.digest(self.transcript)
        self.assertIn('pytest -q <<', text.split('Other commands')[0])


class MaskedMessages(V2Case):
    def test_a_message_with_a_credential_shows_with_the_value_masked_and_says_so(self):
        msg = 'Pass chung: %s rồi làm tiếp phần bản đồ cho repo không có floorplan nhé' % FAKE_CRED
        write_jsonl(self.transcript, main_records() + [rec('user', msg)])
        text, _ = transcript.digest(self.transcript)
        self.assertNotIn(FAKE_CRED, text)
        self.assertIn('rồi làm tiếp phần bản đồ cho repo không có floorplan nhé', text)
        self.assertIn('[ẩn]', text)
        self.assertIn('value masked', text)

    def test_the_rest_of_such_a_message_is_quotable(self):
        msg = 'Pass chung: %s rồi làm tiếp phần bản đồ cho repo không có floorplan nhé' % FAKE_CRED
        write_jsonl(self.transcript, main_records() + [rec('user', msg)])
        self.assertValid(lambda d: d['requests'][0].update(quote='rồi làm tiếp phần bản đồ cho repo không có floorplan nhé'))
        self.assertInvalid(lambda d: d['requests'][0].update(quote=msg), 'Leave the secret out')


class LearnedValues(V2Case):
    """The values a session teaches the validator are credentials, never code or a test fixture."""
    SHAPES = ['password: z.string().min(8),', 'const token = parts[1];', 'secret: process.env.JWT_SECRET,', 'TOKEN=$GITLAB_TOKEN',
              'token=glpat-AAAAAAAAAAAA', 'password=000000000000', 'secret: "************"',
              "token: 'parts[1',", 'secret: `process.env.JWT_SECRET`;', 'password: "z.string().min(8",', 'api_key: user.apiKey,', 'bypass: skip_auth_2024x,']

    def setUp(self):
        super().setUp()
        self.value = 'Qx%s#Lm_%s!' % (secrets.token_hex(3), secrets.token_hex(2))
        self.recs = [rec('user', 'đăng nhập giúp mình\nPass chung: ' + self.value + '\nrồi làm tiếp'),
                     rec('user', 'thử lại với ' + self.value + ' nhé')]
        self.noise = [tool_use('n%d' % i, c) for i, c in enumerate(self.SHAPES)] + [
            rec('assistant', [{'type': 'tool_use', 'id': 'f1', 'name': 'Write', 'input': {'file_path': 'a.ts', 'content': '\n'.join(self.SHAPES)}}])]

    def learn(self, records):
        write_jsonl(self.transcript, main_records() + records)
        transcript.forget()
        transcript.learn(self.transcript)
        return transcript.learned()

    def test_code_shapes_and_fixtures_in_tool_inputs_are_not_learned(self):
        self.assertEqual(self.learn(self.noise), frozenset())

    def test_the_trimmed_form_of_a_code_shape_is_code_too(self):
        for v in ("'parts[1',", '"z.string().min(8",', '`$GITLAB_TOKEN`;', '"process.env.JWT_SECRET")', '000000000000', 'glpat-AAAAAAAAAAAA'):
            self.assertEqual(transcript.secret_values('token: ' + v + ' ;'), set(), v)
        self.assertTrue(transcript.secret_values('token: Abc12345'))  # a bare word with a digit can be a real password

    def test_a_label_inside_a_css_name_is_not_a_label(self):
        for css in ('--mk:32px;--mk-gap:8px', '.mk:hover', 'a{--mk:32px;--mk-gap:8px}', 'x.mk:hover{top:1px}', 'a--mk:32px'):
            self.assertEqual(transcript.secret_values(css), set(), css)
            self.assertFalse(transcript.has_secret(css), css)

    def test_a_label_after_a_space_or_punctuation_still_teaches(self):
        for text, v in (('mk: hunter2xyz', 'hunter2xyz'), ('mật khẩu: hunter2xyz', 'hunter2xyz'), ('password=hunter2xyz', 'hunter2xyz'),
                        ('đổi rồi (mk: hunter2xyz)', 'hunter2xyz'), ('db_password=hunter2xyz', 'hunter2xyz'), ('mysql --password=hunter2xyz', 'hunter2xyz'), ('x\nMK = hunter2xyz', 'hunter2xyz')):
            self.assertIn(v, transcript.secret_values(text), text)

    def test_a_typed_credential_is_learned_among_the_noise_and_a_bare_quote_is_rejected(self):
        self.assertEqual(self.learn(self.recs + self.noise), frozenset({self.value}) | {self.value.strip(transcript.TRIM)})
        self.assertInvalid(lambda d: d['requests'][0].update(quote='thử lại với ' + self.value), 'password, token or key')

    def test_code_in_a_doc_is_not_taken_for_a_password(self):
        self.learn(self.recs + self.noise)
        self.assertValid(lambda d: d['requests'][0].update(result='Đọc process.env.JWT_SECRET và parts[1 ở bước đăng nhập.'))


class LearnedFromEveryText(V2Case):
    """A `transcript` quote can match any message of any role in main and worker files, so the validator learns from all of them."""
    def setUp(self):
        super().setUp()
        self.value = 'Qx%s#Lm_%s!' % (secrets.token_hex(3), secrets.token_hex(2))
        self.worker = os.path.join(self.root, '-fixture', 'sess1', 'subagents', 'agent-abc123.jsonl')

    def only_in(self, records):
        write_jsonl(self.transcript, main_records())
        write_jsonl(self.worker, worker_records() + records)
        transcript.forget()

    def bare_quote_is_rejected(self, text):
        errs, _ = self.validate(lambda d: d['rationale']['chosen'].update(source={'kind': 'transcript', 'transcript': 'agent-abc123', 'quote': text}))
        self.assertTrue([e for e in errs if e.startswith('rationale.chosen') and 'password, token or key' in e], errs)
        self.assertFalse([e for e in errs if 'quote not found' in e], errs)  # the quote was found: only the sweep stops it
        self.assertNotIn(self.value, '\n'.join(errs))

    def test_a_value_only_in_worker_assistant_text_is_learned_and_a_bare_quote_is_rejected(self):
        self.only_in([rec('assistant', [{'type': 'text', 'text': 'Pass chung: %s (đã nhận)' % self.value}], isSidechain=True),
                      rec('assistant', [{'type': 'text', 'text': 'đã đăng nhập bằng %s thành công' % self.value}], isSidechain=True)])
        self.bare_quote_is_rejected('đăng nhập bằng ' + self.value)

    def test_a_value_only_in_tool_result_text_is_learned_and_a_bare_quote_is_rejected(self):
        self.only_in([tool_use('w9', 'cat /tmp/notes.txt'), tool_result('w9', 'ghi chú\nmật khẩu: %s\nhết' % self.value),
                      tool_use('w10', 'cat /tmp/notes2.txt'), tool_result('w10', 'dòng khác chứa %s thôi' % self.value)])
        self.bare_quote_is_rejected('dòng khác chứa ' + self.value)

    def test_a_labelled_value_in_main_assistant_text_is_learned(self):
        write_jsonl(self.transcript, main_records() + [rec('assistant', [{'type': 'text', 'text': 'token: %s đã dùng' % self.value}])])
        transcript.forget()
        transcript.learn(self.transcript)
        self.assertIn(self.value, transcript.learned())

    def test_code_shapes_and_fixtures_in_assistant_and_result_text_are_not_learned(self):
        noise = '\n'.join(LearnedValues.SHAPES)
        self.only_in([rec('assistant', [{'type': 'text', 'text': noise}], isSidechain=True), tool_use('w9', 'ls'), tool_result('w9', noise)])
        write_jsonl(self.transcript, main_records() + [rec('assistant', [{'type': 'text', 'text': noise}]), tool_use('m9', 'ls'), tool_result('m9', noise)])
        transcript.learn(self.transcript)
        self.assertEqual(transcript.learned(), frozenset())


class RationaleReport(V2Case):
    REPORT = 'worker nói cache đã ấm trước khi chạy'

    def setUp(self):
        super().setUp()
        write_jsonl(self.transcript, main_records() + [rec('user', 'Delegated task node:x (y) [completed]:\n' + self.REPORT)])

    def test_a_report_source_grounds_a_rationale_item_and_is_counted(self):
        stats = self.assertValid(lambda d: d['rationale']['chosen'].update(source={'kind': 'report', 'quote': 'cache đã ấm trước khi chạy'}))
        self.assertEqual(stats['reported'], 1)

    def test_a_report_quote_must_exist(self):
        self.assertInvalid(lambda d: d['rationale']['chosen'].update(source={'kind': 'report', 'quote': 'câu chưa ai báo cáo'}), 'quote not found')

    def test_schema_table_lists_report_for_rationale(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'references', 'explain-schema.md'), encoding='utf-8') as fh:
            text = fh.read()
        self.assertRegex(text, r'\| Rationale items \| `source`: transcript, report, code, url; or inferred \|')


class FileRows(V2Case):
    def test_a_node_shows_four_files_largest_first_then_a_count_line(self):
        d = self.good_doc()
        files = [{'path': 'src/f%d.py' % i, 'add': i, 'del': 0} for i in range(1, 8)]
        mods = [{'id': 'src', 'name': 'Src', 'summary': 'x', 'changed': True, 'what_changed': 'Đổi.', 'files': files}]
        d['map'] = {'modules': mods, 'edges': []}
        html = page2.render(d, None, arch=None, validated=False)
        ul = re.search(r'<ul class="files">(.*?)</ul>', html, re.S).group(1)
        rows = re.findall(r'<li[ >].*?</li>', ul, re.S)
        self.assertEqual(len(rows), 5)
        self.assertIn('+3 file', rows[-1])
        self.assertIn('class="more"', rows[-1])
        text = re.sub(r'<[^>]+>|<wbr>', '', ''.join(rows[:4]))
        self.assertEqual([x in text for x in ('f7', 'f6', 'f5', 'f4')], [True] * 4)
        self.assertNotIn('f3.py', text)
        self.assertIn('7 file', html)  # the node's tag keeps the full count

    def test_four_or_fewer_files_have_no_count_line(self):
        d = self.good_doc()
        d['map'] = {'modules': [{'id': 'src', 'name': 'Src', 'summary': 'x', 'changed': True, 'what_changed': 'Đổi.',
                                 'files': [{'path': 'src/f%d.py' % i, 'add': 1, 'del': 0} for i in range(4)]}], 'edges': []}
        html = page2.render(d, None, arch=None, validated=False)
        self.assertNotIn('class="more"', html)


if __name__ == '__main__':
    unittest.main()
