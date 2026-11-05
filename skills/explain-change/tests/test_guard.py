"""Doc-supplied strings never reach git as options."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import SKILL, RepoCase
from helpers2 import V2Case

VALIDATE = os.path.join(SKILL, 'scripts', 'validate.py')
RENDER = os.path.join(SKILL, 'scripts', 'render.py')


def cli(script, *args):
    return subprocess.run([sys.executable, script, *args], capture_output=True, text=True)


class RangeInjection(V2Case):
    def victim(self):
        d = tempfile.mkdtemp(prefix='explain-victim-')
        self.addCleanup(lambda: __import__('shutil').rmtree(d, ignore_errors=True))
        return os.path.join(d, 'x')

    def write_doc(self, mutate):
        doc = self.doc(mutate)
        p = os.path.join(self.repo, 'explain.json')
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh)
        return p

    def test_option_as_base_or_head_is_a_validation_error_and_writes_nothing(self):
        for key in ('base', 'head'):
            for tmpl in ('--output=%s', '--output=%s^{commit}'):
                v = self.victim()
                errs, _ = self.validate(lambda d: d['range'].update({key: tmpl % v}))
                self.assertTrue(any(e.startswith('range.%s:' % key) for e in errs), errs)
                self.assertFalse(os.path.exists(v), 'git wrote %s' % v)

    def test_cli_validate_and_render_refuse_and_write_nothing(self):
        for key in ('base', 'head'):
            v = self.victim()
            p = self.write_doc(lambda d: d['range'].update({key: '--output=' + v}))
            for script in (VALIDATE, RENDER):
                r = cli(script, p, '--repo', self.repo, '--transcript', self.transcript)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('range.%s' % key, r.stdout)
                self.assertNotIn('Traceback', r.stderr)
                self.assertFalse(os.path.exists(v))
            self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))

    def test_normal_sha_and_symbolic_revs_still_work(self):
        self.assertValid()
        self.assertValid(lambda d: d['range'].update(base='HEAD~1', head='HEAD'))
        self.assertValid(lambda d: d['range'].update(base=self.base[:10], head=self.head[:10]))

    def test_file_path_that_looks_like_an_option_is_only_a_path(self):
        v = self.victim()
        for f in ('--output=' + v, '-h', '--help'):
            errs, _ = self.validate(lambda d: d['logic']['after'][0]['refs'][0].update(file=f))
            self.assertTrue(any('logic.after[0]' in e for e in errs), errs)
            self.assertFalse(os.path.exists(v))
            self.assertNotIn('usage', ' '.join(errs))


class LowLevelGitCalls(RepoCase):
    """Each git helper refuses a non-id revision itself, so no caller can forget to resolve."""
    victim = RangeInjection.victim

    def test_changed_files_refuses_option(self):
        from lib import gitio
        v = self.victim()
        with self.assertRaises(gitio.ExplainError):
            gitio.changed_files(self.repo, '--output=' + v, self.head)
        self.assertFalse(os.path.exists(v))

    def test_changed_ranges_refuses_option(self):
        from lib import funcs, gitio
        v = self.victim()
        with self.assertRaises(gitio.ExplainError):
            funcs.changed_ranges(self.repo, '--output=' + v, self.head, 'app/Svc.php')
        self.assertFalse(os.path.exists(v))

    def test_read_version_needs_an_object_id(self):
        from lib import gitio
        with self.assertRaises(gitio.ExplainError):
            gitio.read_version(self.repo, 'HEAD', 'app/Svc.php')
        self.assertIsNotNone(gitio.read_version(self.repo, self.head, 'app/Svc.php'))



def paths(node, prefix=()):
    """Every path (tuple of keys/indexes) in a JSON-like value, containers first."""
    yield prefix
    if isinstance(node, dict):
        for k, v in node.items():
            yield from paths(v, prefix + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from paths(v, prefix + (i,))


def at(doc, path):
    for k in path:
        doc = doc[k]
    return doc


if __name__ == '__main__':
    unittest.main()
