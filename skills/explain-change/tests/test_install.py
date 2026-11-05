"""Tests of install.sh (repo root): every run uses a temp HOME and XDG_CONFIG_HOME, never the real ones."""
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
INSTALL = os.path.join(REPO, 'install.sh')
VALID = 'agents claude codex gemini copilot cursor opencode goose amp kiro windsurf cline roo'
# harness -> user-level skills dir relative to HOME
USER_DIRS = {
    'agents': '.agents/skills', 'codex': '.agents/skills', 'gemini': '.agents/skills', 'copilot': '.agents/skills',
    'cursor': '.agents/skills', 'opencode': '.agents/skills', 'goose': '.agents/skills', 'amp': '.agents/skills',
    'claude': '.claude/skills', 'claude-code': '.claude/skills', 'kiro': '.kiro/skills',
    'windsurf': '.codeium/windsurf/skills', 'cline': '.cline/skills', 'roo': '.roo/skills',
}
DEFAULT_DIRS = ['.agents/skills', '.claude/skills', '.kiro/skills', '.codeium/windsurf/skills', '.cline/skills', '.roo/skills']
MARKER = '.installed-by-explain-change'


def stage_repo(root):
    """A small stand-in for the repo: install.sh next to skills/explain-change (with a stale __pycache__)."""
    skill = os.path.join(root, 'skills', 'explain-change')
    os.makedirs(os.path.join(skill, 'scripts', '__pycache__'))
    for rel, body in (('SKILL.md', '---\nname: explain-change\ndescription: x\n---\n'), ('scripts/run.py', 'print(1)\n'),
                      ('scripts/__pycache__/run.pyc', 'junk')):
        with open(os.path.join(skill, rel), 'w', encoding='utf-8') as fh:
            fh.write(body)
    shutil.copy(INSTALL, os.path.join(root, 'install.sh'))
    return os.path.join(root, 'install.sh'), skill


class Base(unittest.TestCase):
    home_name = 'home'

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='install-test-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, 'repo')
        os.makedirs(self.repo)
        self.script, self.skill = stage_repo(self.repo)
        self.home = os.path.join(self.tmp, self.home_name)
        self.xdg = os.path.join(self.home, 'xdg config')
        os.makedirs(self.xdg)
        self.cwd = os.path.join(self.tmp, 'project')
        os.makedirs(self.cwd)

    def run_sh(self, *args, cwd=None):
        env = {'PATH': os.environ['PATH'], 'HOME': self.home, 'XDG_CONFIG_HOME': self.xdg, 'LC_ALL': 'C.UTF-8'}
        p = subprocess.run(['sh', self.script, *args], env=env, cwd=cwd or self.cwd, capture_output=True, text=True)
        return p.returncode, p.stdout, p.stderr

    def dest(self, rel, base=None):
        return os.path.join(base or self.home, rel, 'explain-change')

    def tree(self, base):
        out = []
        for d, dirs, files in os.walk(base):
            out += [os.path.relpath(os.path.join(d, n), base) for n in dirs + files]
        return sorted(out)


class Install(Base):
    def test_default_creates_every_harness_path_as_a_symlink_to_the_skill(self):
        rc, out, _ = self.run_sh()
        self.assertEqual(rc, 0, out)
        for rel in DEFAULT_DIRS:
            d = self.dest(rel)
            self.assertTrue(os.path.islink(d), d)
            self.assertEqual(os.readlink(d), self.skill)
            self.assertTrue(os.path.isfile(os.path.join(d, 'SKILL.md')))
            self.assertIn(d, out, 'every path touched is printed')

    def test_each_harness_name_installs_to_its_documented_path_and_only_there(self):
        for name, rel in USER_DIRS.items():
            with self.subTest(harness=name):
                shutil.rmtree(self.home)
                os.makedirs(self.xdg)
                rc, out, err = self.run_sh('--harness', name)
                self.assertEqual(rc, 0, err)
                self.assertTrue(os.path.islink(self.dest(rel)))
                self.assertEqual(sum(1 for p in self.tree(self.home) if p.endswith('explain-change')), 1)

    def test_harness_list_and_repeats_install_each_target_once(self):
        rc, out, _ = self.run_sh('--harness', 'codex,gemini', '--harness=claude')
        self.assertEqual(rc, 0)
        self.assertEqual(out.count(self.dest('.agents/skills')), 1, out)
        self.assertTrue(os.path.islink(self.dest('.agents/skills')))
        self.assertTrue(os.path.islink(self.dest('.claude/skills')))
        self.assertFalse(os.path.exists(self.dest('.kiro/skills')))

    def test_nothing_is_written_outside_the_skill_dirs(self):
        self.run_sh()
        expected = {'xdg config'}
        for rel in DEFAULT_DIRS:
            parts = rel.split('/')
            for i in range(1, len(parts) + 1):
                expected.add('/'.join(parts[:i]))
            expected.add(rel + '/explain-change')
        self.assertEqual(set(self.tree(self.home)), expected)

    def test_copy_makes_a_real_folder_with_a_marker_and_no_pycache(self):
        rc, out, _ = self.run_sh('--copy', '--harness', 'claude')
        self.assertEqual(rc, 0, out)
        d = self.dest('.claude/skills')
        self.assertFalse(os.path.islink(d))
        self.assertTrue(os.path.isfile(os.path.join(d, 'SKILL.md')))
        self.assertTrue(os.path.isfile(os.path.join(d, MARKER)))
        self.assertFalse(os.path.exists(os.path.join(d, 'scripts', '__pycache__')))

    def test_rerun_is_idempotent_in_both_modes(self):
        for args in ([], ['--copy']):
            with self.subTest(args=args):
                shutil.rmtree(self.home)
                os.makedirs(self.xdg)
                self.assertEqual(self.run_sh(*args)[0], 0)
                before = self.tree(self.home)
                rc, out, _ = self.run_sh(*args)
                self.assertEqual(rc, 0, out)
                self.assertEqual(self.tree(self.home), before)
        shutil.rmtree(self.home)
        os.makedirs(self.xdg)
        self.run_sh()
        again = self.run_sh()[1]
        self.assertEqual(again.count('already linked'), len(DEFAULT_DIRS))
        self.assertNotIn('replace', again)

    def test_an_existing_real_dir_is_refused_without_force(self):
        d = self.dest('.claude/skills')
        os.makedirs(d)
        with open(os.path.join(d, 'mine.txt'), 'w') as fh:
            fh.write('keep')
        rc, out, _ = self.run_sh('--harness', 'claude,kiro')
        self.assertEqual(rc, 1)
        self.assertIn('refuse', out)
        self.assertEqual(os.listdir(d), ['mine.txt'])
        self.assertTrue(os.path.islink(self.dest('.kiro/skills')), 'the other targets still install')

    def test_a_live_symlink_to_something_else_is_refused_without_force(self):
        d = self.dest('.agents/skills')
        os.makedirs(os.path.dirname(d))
        os.symlink(self.tmp, d)
        rc, out, _ = self.run_sh('--harness', 'agents')
        self.assertEqual(rc, 1, out)
        self.assertEqual(os.readlink(d), self.tmp)
        self.assertEqual(self.run_sh('--harness', 'agents', '--force')[0], 0)
        self.assertEqual(os.readlink(d), self.skill)

    def test_force_replaces_an_existing_real_dir(self):
        d = self.dest('.claude/skills')
        os.makedirs(d)
        rc, _, _ = self.run_sh('--harness', 'claude', '--force')
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.islink(d))

    def test_a_broken_symlink_is_replaced(self):
        d = self.dest('.agents/skills')
        os.makedirs(os.path.dirname(d))
        os.symlink(os.path.join(self.tmp, 'gone'), d)
        rc, out, _ = self.run_sh('--harness', 'agents')
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.readlink(d), self.skill)

    def test_a_checkout_inside_the_target_is_never_deleted_even_with_force(self):
        clone = self.dest('.claude/skills')
        os.makedirs(clone)
        script, skill = stage_repo(clone)
        self.script = script
        rc, out, _ = self.run_sh('--harness', 'claude', '--force')
        self.assertEqual(rc, 1, out)
        self.assertTrue(os.path.isfile(os.path.join(skill, 'SKILL.md')))

    def test_dry_run_prints_the_paths_and_changes_nothing(self):
        rc, out, _ = self.run_sh('--dry-run')
        self.assertEqual(rc, 0)
        self.assertEqual(self.tree(self.home), ['xdg config'])
        for rel in DEFAULT_DIRS:
            self.assertIn(self.dest(rel), out)
        self.run_sh()
        before = self.tree(self.home)
        self.run_sh('--uninstall', '--dry-run')
        self.assertEqual(self.tree(self.home), before)


class Project(Base):
    def test_project_installs_under_the_current_directory_not_home(self):
        rc, out, _ = self.run_sh('--project', '--copy')
        self.assertEqual(rc, 0, out)
        for rel in ('.agents/skills', '.claude/skills', '.kiro/skills'):
            self.assertTrue(os.path.isfile(os.path.join(self.cwd, rel, 'explain-change', 'SKILL.md')), rel)
        self.assertEqual(self.tree(self.home), ['xdg config'])

    def test_project_skips_a_harness_with_no_project_path_and_says_so(self):
        rc, out, _ = self.run_sh('--project', '--harness', 'roo,agents')
        self.assertEqual(rc, 0)
        self.assertIn('skip', out)
        self.assertIn('roo', out)
        self.assertEqual(self.tree(self.cwd), ['.agents', '.agents/skills', '.agents/skills/explain-change'])


class Uninstall(Base):
    def test_uninstall_removes_what_install_created_in_both_modes(self):
        for args in ([], ['--copy']):
            with self.subTest(args=args):
                self.run_sh(*args)
                rc, out, _ = self.run_sh('--uninstall')
                self.assertEqual(rc, 0, out)
                for rel in DEFAULT_DIRS:
                    self.assertFalse(os.path.lexists(self.dest(rel)), rel)

    def test_uninstall_leaves_everything_it_did_not_create(self):
        sibling = os.path.join(self.home, '.claude/skills/other-skill')
        os.makedirs(sibling)
        real = self.dest('.kiro/skills')  # a real folder of the user's, no marker
        os.makedirs(real)
        elsewhere = self.dest('.cline/skills')  # a symlink to something else
        os.makedirs(os.path.dirname(elsewhere))
        os.symlink(self.tmp, elsewhere)
        self.run_sh('--harness', 'claude,agents')
        rc, out, _ = self.run_sh('--uninstall')
        self.assertEqual(rc, 0, out)
        self.assertTrue(os.path.isdir(sibling))
        self.assertTrue(os.path.isdir(real))
        self.assertEqual(os.readlink(elsewhere), self.tmp)
        self.assertFalse(os.path.lexists(self.dest('.claude/skills')))
        self.assertFalse(os.path.lexists(self.dest('.agents/skills')))
        self.assertIn('not installed by this script', out)

    def test_uninstall_on_a_clean_home_is_a_no_op(self):
        rc, out, _ = self.run_sh('--uninstall')
        self.assertEqual(rc, 0)
        self.assertEqual(self.tree(self.home), ['xdg config'])


class Usage(Base):
    def test_unknown_harness_exits_nonzero_listing_the_valid_names_and_writes_nothing(self):
        rc, out, err = self.run_sh('--harness', 'codex,vscode')
        self.assertEqual(rc, 2)
        self.assertIn('vscode', err)
        self.assertIn(VALID, err)
        self.assertEqual(self.tree(self.home), ['xdg config'])

    def test_unknown_option_exits_nonzero(self):
        self.assertEqual(self.run_sh('--nope')[0], 2)

    def test_help_exits_zero(self):
        rc, out, _ = self.run_sh('--help')
        self.assertEqual(rc, 0)
        self.assertIn('--uninstall', out)


class Paths(Base):
    home_name = 'hôme dir ünïcode ✓'

    def test_a_home_with_spaces_and_non_ascii_works_for_link_copy_and_uninstall(self):
        self.assertEqual(self.run_sh()[0], 0)
        for rel in DEFAULT_DIRS:
            self.assertTrue(os.path.islink(self.dest(rel)))
        self.assertEqual(self.run_sh('--uninstall')[0], 0)
        self.assertEqual(self.run_sh('--copy')[0], 0)
        self.assertTrue(os.path.isfile(os.path.join(self.dest('.claude/skills'), 'SKILL.md')))
        self.assertEqual(self.run_sh('--uninstall')[0], 0)
        self.assertFalse(os.path.lexists(self.dest('.claude/skills')))

    def test_a_checkout_in_a_path_with_spaces_works(self):
        other = os.path.join(self.tmp, 'clone dir é')
        os.makedirs(other)
        self.script, self.skill = stage_repo(other)
        self.assertEqual(self.run_sh('--harness', 'agents')[0], 0)
        self.assertEqual(os.readlink(self.dest('.agents/skills')), self.skill)
        self.assertEqual(self.run_sh('--uninstall', '--harness', 'agents')[0], 0)


if __name__ == '__main__':
    unittest.main()
