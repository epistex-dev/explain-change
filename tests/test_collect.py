import json
import os
import subprocess
import sys
import time
import unittest

from helpers import SKILL, RepoCase, run
from lib import collect, gitio

COLLECT = os.path.join(SKILL, 'scripts', 'collect.py')


def collect_cli(repo, *args):
    return subprocess.run([sys.executable, COLLECT, '--repo', repo, *args], capture_output=True, text=True)


class RangeSelection(RepoCase):
    def test_clean_tree_defaults_to_last_commit(self):
        r = gitio.resolve_range(self.repo)
        self.assertEqual((r['mode'], r['base'], r['head']), ('commit', self.base, self.head))

    def test_uncommitted_changes_win_over_last_commit(self):
        self.write('app/Svc.php', 'changed\n')
        r = gitio.resolve_range(self.repo)
        self.assertEqual((r['mode'], r['base']), ('worktree', self.head))
        files = gitio.changed_files(self.repo, r['base'], r['head'])
        self.assertEqual([f['path'] for f in files], ['app/Svc.php'])

    def test_untracked_files_count_as_uncommitted(self):
        self.write('new/file.txt', 'hello\n')
        r = gitio.resolve_range(self.repo)
        self.assertEqual([f['path'] for f in gitio.changed_files(self.repo, r['base'], r['head'])], ['new/file.txt'])

    def test_worktree_snapshot_leaves_the_repo_untouched(self):
        self.write('new/file.txt', 'hello\n')
        before = run(self.repo, 'git', 'status', '--porcelain')
        gitio.resolve_range(self.repo)
        self.assertEqual(run(self.repo, 'git', 'status', '--porcelain'), before)
        self.assertEqual(self.rev('HEAD'), self.head)

    def test_explicit_range_and_single_commit(self):
        r = gitio.resolve_range(self.repo, '%s..%s' % (self.base, self.head))
        self.assertEqual((r['base'], r['head']), (self.base, self.head))
        r = gitio.resolve_range(self.repo, self.head)
        self.assertEqual(r['base'], self.base)

    def test_root_commit_diffs_against_the_empty_tree(self):
        r = gitio.resolve_range(self.repo, self.base)
        self.assertEqual(r['base'], gitio.EMPTY_TREE)
        self.assertEqual(len(gitio.changed_files(self.repo, r['base'], r['head'])), 2)

    def test_unknown_revision_is_a_clear_error(self):
        with self.assertRaises(gitio.ExplainError):
            gitio.resolve_range(self.repo, 'nope..HEAD')


class Collect(RepoCase):
    def test_summary_lists_files_binary_and_unicode_paths(self):
        r = collect_cli(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('tài-liệu/ghi-chú.md', r.stdout)
        self.assertIn('binary', r.stdout)
        self.assertIn('Svc.php:4  run  branches=', r.stdout.replace('app/', ''))
        run_dir = r.stdout.split('RUN_DIR=')[1].strip()
        with open(os.path.join(run_dir, 'summary.json'), encoding='utf-8') as fh:
            s = json.load(fh)
        self.assertEqual(s['totals']['files'], 5)
        self.assertEqual(s['totals']['binary'], 1)
        self.assertTrue(os.path.exists(os.path.join(run_dir, 'diff.patch')))

    def test_exclude_line_added_once_and_dir_is_untracked(self):
        collect_cli(self.repo)
        collect_cli(self.repo)
        with open(os.path.join(self.repo, '.git/info/exclude')) as fh:
            ex = fh.read().split('\n')
        self.assertEqual(ex.count('.explain/'), 1)
        self.assertEqual(run(self.repo, 'git', 'status', '--porcelain'), '')

    def test_empty_range_gives_a_message_and_no_directory(self):
        r = collect_cli(self.repo, 'HEAD..HEAD')
        self.assertEqual(r.returncode, 3)
        self.assertIn('Không có thay đổi', r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.repo, '.explain')))

    def test_empty_commit_gives_a_message_and_no_directory(self):
        run(self.repo, 'git', 'commit', '-q', '--allow-empty', '-m', 'empty')
        r = collect_cli(self.repo)
        self.assertEqual(r.returncode, 3)
        self.assertFalse(os.path.exists(os.path.join(self.repo, '.explain')))

    def test_not_a_repo_is_a_clear_error(self):
        r = collect_cli('/tmp')
        self.assertEqual(r.returncode, 2)
        self.assertIn('not a git repository', r.stderr)

    def test_slug_folds_vietnamese(self):
        self.assertEqual(collect.slugify('Đổi giới hạn: theo module!'), 'doi-gioi-han-theo-module')
        self.assertEqual(collect.slugify('???'), 'change')


class HugeDiff(RepoCase):
    def test_huge_diff_summary_stays_usable(self):
        self.write('big/data.php', '<?php\n' + ''.join('$v%d = %d;\n' % (i, i) for i in range(6500)))
        for i in range(60):
            self.write('big/part%02d.txt' % i, 'x\n' * 20)
        t0 = time.time()
        r = collect_cli(self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('huge diff', r.stdout)
        self.assertLess(len(r.stdout.splitlines()), 600)
        run_dir = r.stdout.split('RUN_DIR=')[1].strip()
        with open(os.path.join(run_dir, 'summary.json'), encoding='utf-8') as fh:
            s = json.load(fh)
        self.assertGreater(s['totals']['patch_lines'], 5000)
        self.assertLess(time.time() - t0, 30)


class FunctionDetection(RepoCase):
    def test_branches_are_counted_and_tests_flagged(self):
        files = gitio.changed_files(self.repo, self.base, self.head)
        from lib import funcs
        fs = funcs.changed_functions(self.repo, self.base, self.head, files)
        run_fn = [f for f in fs if f['name'] == 'run'][0]
        self.assertGreaterEqual(run_fn['branches'], 3)
        self.assertFalse(run_fn['test'])
        self.assertTrue([f for f in fs if f['name'] == 'test_run_stops_at_limit'][0]['test'])


if __name__ == '__main__':
    unittest.main()
