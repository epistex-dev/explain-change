"""Doc-supplied strings never reach git as options, and validate.py accepts only what render.py can draw."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import SKILL, RepoCase
from lib import check, page

VALIDATE = os.path.join(SKILL, 'scripts', 'validate.py')
RENDER = os.path.join(SKILL, 'scripts', 'render.py')


def cli(script, *args):
    return subprocess.run([sys.executable, script, *args], capture_output=True, text=True)


class RangeInjection(RepoCase):
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
                r = cli(script, p, '--repo', self.repo)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('range.%s' % key, r.stdout)
                self.assertNotIn('Traceback', r.stderr)
                self.assertFalse(os.path.exists(v))
            self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))

    def test_page_resolves_before_calling_git_even_if_validation_is_skipped(self):
        v = self.victim()
        d = self.doc(lambda d: d['range'].update(base='--output=' + v))
        with self.assertRaises(Exception):
            page.render(d, self.repo, with_mermaid=False)
        self.assertFalse(os.path.exists(v))

    def test_normal_sha_and_symbolic_revs_still_work(self):
        self.assertValid()
        self.assertValid(lambda d: d['range'].update(base='HEAD~1', head='HEAD'))
        self.assertValid(lambda d: d['range'].update(base=self.base[:10], head=self.head[:10]))

    def test_page_accepts_symbolic_revs_by_resolving_them(self):
        out = page.render(self.doc(lambda d: d['range'].update(base='HEAD~1', head='HEAD')), self.repo, with_mermaid=False)
        self.assertIn('Svc', out)

    def test_file_path_that_looks_like_an_option_is_only_a_path(self):
        v = self.victim()
        for f in ('--output=' + v, '-h', '--help'):
            errs, _ = self.validate(lambda d: d['why']['refs'][0].update(file=f))
            self.assertTrue(any('why.refs[0]' in e for e in errs), errs)
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


LINE = __import__('re').compile(r'^[\w$.\[\]]+: \S.*')


class ValidatorMatchesRenderer(RepoCase):
    """validate never raises and always prints `path: reason`; whatever it accepts, render draws."""

    def check_doc(self, doc, what):
        try:
            errs, _ = check.validate(doc, self.repo)
        except Exception as e:  # noqa: BLE001
            self.bad.append('validate raised %r for %s' % (e, what))
            return []
        for e in errs:
            if not LINE.match(e):
                self.bad.append('malformed error %r for %s' % (e, what))
        if not errs:
            try:
                page.render(doc, self.repo, with_mermaid=False)
            except Exception as e:  # noqa: BLE001
                self.bad.append('validate accepted but render raised %r for %s' % (e, what))
        return errs

    def setUp(self):
        super().setUp()
        self.bad = []
        # the repo never changes during a fuzz run: memoise the two slow, pure git readers
        from unittest import mock
        from lib import funcs, gitio
        for mod, name in ((gitio, 'changed_files'), (funcs, 'changed_functions')):
            real, memo = getattr(mod, name), {}

            def cached(*a, _real=real, _memo=memo):
                key = repr(a)
                if key not in _memo:
                    _memo[key] = _real(*a)
                return _memo[key]
            pat = mock.patch.object(mod, name, cached)
            pat.start()
            self.addCleanup(pat.stop)

    def tearDown(self):
        self.assertEqual(self.bad[:15], [], '%d problems' % len(self.bad))

    def test_missing_ids_are_validation_errors(self):
        self.assertInvalid(lambda d: d['logic']['items'][0].pop('id'), 'logic.items[0].id')
        self.assertInvalid(lambda d: d['flows']['items'][0]['actors'][0].pop('id'), 'flows.items[0].actors[0].id')
        self.assertInvalid(lambda d: d['changes']['items'][0].pop('id'), 'changes.items[0].id')

    def flowchart_doc(self):
        d = self.good_doc()
        it = d['logic']['items'][0]
        r = it['refs'][0]
        it.pop('trace')
        it['kind'] = 'flowchart'
        it['change'] = 'c1'
        it['flow'] = {'nodes': [{'id': 's', 'label': 'start', 'type': 'start', 'changed': True}, {'id': 'q', 'label': 'skip?', 'type': 'decision'},
                                {'id': 'e', 'label': 'end', 'type': 'end'}, {'id': 'z', 'label': 'other', 'type': 'end'}],
                      'edges': [{'from': 's', 'to': 'q', 'ref': r}, {'from': 'q', 'to': 'e', 'label': 'yes', 'ref': r},
                                {'from': 'q', 'to': 'e', 'label': 'no', 'ref': r}, {'from': 'q', 'to': 'z', 'label': 'other', 'ref': r}]}
        return d

    def bases(self):
        fc = self.flowchart_doc()
        self.assertEqual(check.validate(fc, self.repo)[0], [])
        sk = self.good_doc()
        sk['logic']['skipped'] = [{'file': 'app/Svc.php', 'function': 'other', 'reason': 'tầm thường'}]
        return [self.good_doc(), fc, sk]

    def test_deleting_any_key_in_turn(self):
        n = 0
        for base in self.bases():
            for p in paths(base):
                if not p or not isinstance(p[-1], str):
                    continue
                doc = copy.deepcopy(base)
                del at(doc, p[:-1])[p[-1]]
                n += 1
                self.check_doc(doc, 'deleted %s' % '/'.join(map(str, p)))
        self.assertGreater(n, 200)

    def test_wrong_types_anywhere(self):
        n = 0
        for base in self.bases():
            for p in paths(base):
                if not p:
                    continue
                for bad in ([], {}, ['x'], 7, None, 'x'):
                    doc = copy.deepcopy(base)
                    at(doc, p[:-1])[p[-1]] = bad
                    n += 1
                    self.check_doc(doc, 'set %s = %r' % ('/'.join(map(str, p)), bad))
        self.assertGreater(n, 2000)
