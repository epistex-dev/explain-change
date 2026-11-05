"""Session digest polish: a delete under /tmp/ or $TMPDIR is scratch (counted, never listed as an outward action), and a worktree made by
`git worktree add` in the transcript counts as its repo. Both read command text only: no git runs and no path is looked at."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from helpers2 import rec, tool_result, write_jsonl  # noqa: E402
from helpers2 import tool_use as _tool_use  # noqa: E402
from lib import check_session, outward, session, transcript  # noqa: E402

SKILL = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL, 'scripts', 'collect.py')


def tool_use(tid, cmd, cwd=None):
    r = _tool_use(tid, cmd)
    if cwd:
        r['cwd'] = cwd
    return r


def scratch(cmd, cwd=None):
    return [a.scratch for a in outward.classify(cmd, cwd) if a[0] == 'delete']


class ScratchDelete(unittest.TestCase):
    def test_a_delete_under_tmp_is_scratch_and_one_elsewhere_is_real(self):
        self.assertEqual(scratch('rm -rf /tmp/build-1'), [True])
        self.assertEqual(scratch('rm -rf /home/u/proj/dist'), [False])
        self.assertEqual(scratch('rmdir /tmp/a/b'), [True])
        self.assertEqual(scratch('find /tmp/x -name "*.o" -delete'), [True])
        self.assertEqual(scratch('find . -name "*.o" -delete', '/home/u'), [False])
        self.assertEqual(scratch('git worktree remove /tmp/wt1'), [True])
        self.assertEqual(scratch('git worktree remove /home/u/wt1'), [False])

    def test_the_kind_stays_delete_and_the_tuple_shape_is_kept(self):
        (kind, label), = outward.classify('rm -rf /tmp/a')
        self.assertEqual((kind, label), ('delete', 'rm -r'))

    def test_every_target_must_be_scratch(self):
        self.assertEqual(scratch('rm -rf /tmp/a /home/u/real'), [False])
        self.assertEqual(scratch('rm -rf /tmp/a /tmp/b'), [True])

    def test_hostile_targets_count_as_real(self):
        for cmd in ('rm -rf /tmp', 'rm -rf /tmp/', 'rm -rf /tmp/../home/u', 'rm -rf /tmpfoo/x', 'rm -rf ~/tmp/x', 'rm -rf /tmp/$X', 'rm -rf /tmp/`pwd`',
                    'rm -rf $HOME/x', 'rm -rf', 'rm -rf -- '):
            self.assertNotIn(True, scratch(cmd), cmd)

    def test_quoted_paths_with_spaces(self):
        self.assertEqual(scratch('rm -rf "/tmp/a b/c d"'), [True])
        self.assertEqual(scratch("rm -rf '/home/u/a b'"), [False])

    def test_tmpdir_forms(self):
        self.assertEqual(scratch('rm -rf $TMPDIR/x'), [True])
        self.assertEqual(scratch('rm -rf ${TMPDIR}/x'), [True])
        self.assertEqual(scratch('rm -rf $TMPDIR/../x'), [False])
        old = os.environ.get('TMPDIR')
        os.environ['TMPDIR'] = '/var/scratch-root/'
        try:
            self.assertEqual(scratch('rm -rf /var/scratch-root/job1'), [True])
            self.assertEqual(scratch('rm -rf /var/scratch-root'), [False])
        finally:
            if old is None:
                os.environ.pop('TMPDIR')
            else:
                os.environ['TMPDIR'] = old

    def test_a_relative_target_is_read_against_cd_or_the_calls_directory(self):
        self.assertEqual(scratch('cd /tmp/job && rm -rf out'), [True])
        self.assertEqual(scratch('rm -rf out', '/tmp/job'), [True])
        self.assertEqual(scratch('rm -rf out', '/home/u'), [False])
        self.assertEqual(scratch('rm -rf out'), [False])  # no directory known: the doubt goes to the real side
        self.assertEqual(scratch('cd /tmp/job && cd .. && rm -rf out', '/home/u'), [True])  # /tmp/out
        self.assertEqual(scratch('cd /tmp/job && cd ../../home && rm -rf out'), [False])
        self.assertEqual(scratch('cd $WORK && rm -rf out', '/tmp/job'), [False])


class WorktreeAdds(unittest.TestCase):
    def test_path_and_repo_come_from_the_command_text(self):
        self.assertEqual(outward.worktree_adds('git -C /r worktree add /tmp/w1 -b feat main'), [('/r', '/tmp/w1')])
        self.assertEqual(outward.worktree_adds('cd /r && git worktree add ../w2 HEAD'), [('/r', '/w2')])
        self.assertEqual(outward.worktree_adds('git worktree add /tmp/w3', '/r'), [('/r', '/tmp/w3')])
        self.assertEqual(outward.worktree_adds('git -C /r worktree add --detach -- /tmp/w4'), [('/r', '/tmp/w4')])

    def test_flags_that_take_a_value_do_not_swallow_the_path(self):
        self.assertEqual(outward.worktree_adds('git -C /r worktree add -b topic /tmp/w5'), [('/r', '/tmp/w5')])
        self.assertEqual(outward.worktree_adds('git -C /r worktree add -B topic --reason why /tmp/w6'), [('/r', '/tmp/w6')])

    def test_missing_path_argument_is_ignored(self):
        for cmd in ('git -C /r worktree add', 'git -C /r worktree add -b', 'git -C /r worktree add -b topic', 'git -C /r worktree add --', 'git worktree add'):
            self.assertEqual(outward.worktree_adds(cmd, '/r' if cmd == 'git worktree add' else None), [], cmd)

    def test_quoted_paths_with_spaces(self):
        self.assertEqual(outward.worktree_adds('git -C "/my repo" worktree add "/tmp/a b/wt" HEAD'), [('/my repo', '/tmp/a b/wt')])
        self.assertEqual(outward.worktree_adds("git -C /r worktree add '/tmp/it s/wt'"), [('/r', '/tmp/it s/wt')])

    def test_a_path_or_repo_that_cannot_be_named_is_ignored(self):
        self.assertEqual(outward.worktree_adds('git -C /r worktree add $X/wt'), [])
        self.assertEqual(outward.worktree_adds('git -C $R worktree add /tmp/w'), [])
        self.assertEqual(outward.worktree_adds('git -C /r worktree add /r'), [])  # the repo itself

    def test_other_worktree_commands_and_mentions_are_not_adds(self):
        for cmd in ('git -C /r worktree list', 'git -C /r worktree remove /tmp/w', "echo 'git -C /r worktree add /tmp/w'", 'git -C /r status'):
            self.assertEqual(outward.worktree_adds(cmd), [], cmd)

    def test_repo_paths_still_name_the_directories(self):
        self.assertEqual(outward.repo_paths('cd /a && git status && git -C ../b log'), ['/a', '/b'])
        self.assertEqual(outward.repo_paths('gh -R o/n pr list'), ['o/n'])


class Case(unittest.TestCase):
    def setUp(self):
        transcript.forget()
        self.addCleanup(transcript.forget)
        self.tmp = tempfile.TemporaryDirectory(prefix='explain-digest-')
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        os.environ['EXPLAIN_PROJECTS_DIR'] = self.root
        self.addCleanup(os.environ.pop, 'EXPLAIN_PROJECTS_DIR', None)
        self.transcript = os.path.join(self.root, '-fixture', 'sess.jsonl')

    def write(self, calls):
        """calls: [(command, result, cwd)] after one user turn."""
        recs = [rec('user', 'tidy up and publish')]
        for i, (cmd, res, cwd) in enumerate(calls):
            recs += [tool_use('c%d' % i, cmd, cwd), tool_result('c%d' % i, res)]
        write_jsonl(self.transcript, recs)

    def digest(self):
        p = subprocess.run([sys.executable, SCRIPT, '--session', '--transcript', self.transcript], capture_output=True, text=True,
                           env={**os.environ, 'EXPLAIN_PROJECTS_DIR': self.root})
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout


class Digest(Case):
    def test_scratch_deletes_are_one_line_and_still_counted(self):
        self.write([('rm -rf /tmp/w%d' % i, 'removed', '/r') for i in range(5)] + [('rm -rf /home/u/dist', 'removed', '/r')])
        out = self.digest()
        self.assertIn('+ 5 scratch delete(s)', out)
        self.assertIn('totals: delete 6', out)
        self.assertIn('delete 6 = 1 real + 5 scratch: write {"kind": "delete", "count": 6, "scratch": 5', out)
        self.assertEqual(out.count('delete  rm -r'), 1)  # only the real one is listed

    def test_no_scratch_means_no_scratch_lines(self):
        self.write([('rm -rf /home/u/dist', 'removed', '/r')])
        out = self.digest()
        self.assertNotIn('scratch delete', out)
        self.assertNotIn('+ ', out.split('Outward actions', 1)[1])
        self.assertIn('totals: delete 1', out)

    def test_a_worktree_counts_as_its_repo(self):
        self.write([('git -C /r worktree add /tmp/w1 -b x', 'Preparing worktree', None), ('git -C /tmp/w1 status', 'clean', None),
                    ('git -C /tmp/w1/sub log', 'abc', None), ('git -C /r log', 'abc', None), ('git -C /other status', 'clean', None)])
        out = self.digest()
        repos = out.split('Repos touched', 1)[1].split('Outward actions', 1)[0]
        self.assertIn('/r  u1..u1  4', repos)  # its own two calls plus the worktree's two
        self.assertIn('/other  u1..u1  1', repos)
        self.assertNotIn('/tmp/w1', repos.split('\n', 1)[1])
        self.assertIn('(2: ', repos)
        self.assertIn('2 path(s) folded', repos)

    def test_the_path_need_not_exist_and_nothing_runs(self):
        self.write([('git -C /no/such/repo worktree add /no/such/wt', 'fatal: not a git repository', None), ('git -C /no/such/wt log', 'x', None)])
        out = self.digest()
        repos = out.split('Repos touched', 1)[1].split('Outward actions', 1)[0]
        self.assertIn('/no/such/repo  u1..u1  2', repos)
        self.assertNotIn('/no/such/wt ', repos)

    def test_a_missing_path_argument_changes_nothing(self):
        self.write([('git -C /r worktree add', 'usage: git worktree add', None), ('git -C /tmp/w status', 'x', None)])
        out = self.digest()
        self.assertIn('/tmp/w  u1..u1  1', out)
        self.assertIn('0 path(s) folded', out)

    def test_a_quoted_path_with_spaces_maps(self):
        self.write([('git -C "/my repo" worktree add "/tmp/a b/wt" HEAD', 'ok', None), ('git -C "/tmp/a b/wt" status', 'x', None)])
        repos = self.digest().split('Repos touched', 1)[1].split('Outward actions', 1)[0]
        self.assertIn('/my repo  u1..u1  2', repos)
        self.assertNotIn('/tmp/a b/wt', repos)

    def test_a_worktree_of_a_worktree_reaches_the_main_repo_and_a_cycle_stops(self):
        self.write([('git -C /r worktree add /tmp/a', 'ok', None), ('git -C /tmp/a worktree add /tmp/b', 'ok', None), ('git -C /tmp/b status', 'x', None),
                    ('git -C /c1 worktree add /c2', 'ok', None), ('git -C /c2 worktree add /c1', 'ok', None), ('git -C /c1 status', 'x', None)])
        sc = session.scan(self.transcript)
        self.assertEqual(sc.main_repo('/tmp/b'), '/r')
        self.assertIn(sc.main_repo('/c1'), ('/c1', '/c2'))  # terminates

    def test_a_sibling_directory_with_the_same_prefix_is_not_a_worktree(self):
        self.write([('git -C /r worktree add /tmp/w1', 'ok', None), ('git -C /tmp/w10 status', 'x', None)])
        sc = session.scan(self.transcript)
        self.assertEqual(sc.main_repo('/tmp/w10'), '/tmp/w10')
        self.assertEqual(sc.main_repo('/tmp/w1/x'), '/r')

    def test_a_history_rewrite_is_only_filter_repo_or_filter_branch(self):
        self.write([('git -C /r filter-repo --path x --invert-paths', 'Parsed 3 commits', None), ('git -C /r push --force origin main', 'forced update', None),
                    ('git -C /r commit --amend -m x', 'ok', None), ('git -C /r rebase main', 'ok', None)])
        out = self.digest()
        self.assertIn('totals: force_push 1, history_rewrite 1', out)


class Doc(Case):
    def doc(self, delete):
        return {'schema': 'explain-session/1', 'lang': 'en', 'title': 't', 'summary': 's', 'themes': [
            {'id': 'a', 'title': 'A', 'status': 'done', 'outcome': 'o', 'events': [
                {'kind': 'outward', 'text': 'x', 'source': {'kind': 'tool_call', 'command': 'rm -rf /tmp/w0', 'excerpt': 'removed'}}]}],
            'needs_you': [], 'decided': [], 'outward': [{'kind': 'delete', 'count': 3, 'themes': ['a'], **delete,
                                                          'evidence': [{'kind': 'tool_call', 'command': 'rm -rf /tmp/w0', 'excerpt': 'removed'}]}]}

    def check(self, delete):
        self.write([('rm -rf /tmp/w0', 'removed', '/r'), ('rm -rf /tmp/w1', 'removed', '/r'), ('rm -rf /home/u/dist', 'removed', '/r')])
        return check_session.validate(self.doc(delete), self.transcript)[0]

    def test_the_doc_says_how_many_deletes_are_scratch(self):
        self.assertEqual(self.check({'scratch': 2}), [])

    def test_a_wrong_scratch_count_fails(self):
        errs = self.check({'scratch': 3})
        self.assertTrue(any('scratch 3' in e and 'shows 2' in e for e in errs), errs)

    def test_a_missing_scratch_count_fails_when_the_session_has_scratch_deletes(self):
        errs = self.check({})
        self.assertTrue(any('scratch 0' in e and 'shows 2' in e for e in errs), errs)

    def test_scratch_is_a_whole_number_within_count(self):
        for bad in (-1, 4, 1.5, True, '2'):
            errs = self.check({'scratch': bad})
            self.assertTrue(any('outward[0].scratch' in e for e in errs), (bad, errs))

    def test_only_a_delete_entry_has_scratch(self):
        d = self.doc({'scratch': 1})
        d['outward'][0]['kind'] = 'push'
        d['outward'][0]['evidence'][0]['command'] = 'git push'
        errs = check_session.validate(d, None)[0]
        self.assertTrue(any('outward[0].scratch' in e and 'only a delete' in e for e in errs), errs)


if __name__ == '__main__':
    unittest.main()
