"""A doc with version 1 or none is refused by validate.py and render.py with one line and exit 1."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from helpers import SKILL

LINE = 'error: explain-change v1 docs are no longer supported; write version 2 (references/explain-schema.md)\n'
DOCS = {'schema v1': {'schema': 'explain-change/1', 'version': 1, 'title': 't'}, 'no version': {'title': 't'}, 'schema v1, no version': {'schema': 'explain-change/1'}}


class V1Refused(unittest.TestCase):
    def run_script(self, script, doc):
        with tempfile.TemporaryDirectory(prefix='explain-v1-') as d:  # not a git repo: the refusal comes before any git call
            p = os.path.join(d, 'explain.json')
            with open(p, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh)
            r = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', script), p], capture_output=True, text=True)
            return r, os.path.exists(os.path.join(d, 'index.html'))

    def check_script(self, script):
        for what, doc in DOCS.items():
            r, wrote = self.run_script(script, doc)
            self.assertEqual((r.returncode, r.stderr, r.stdout, wrote), (1, LINE, '', False), what)

    def test_validate_refuses_a_v1_doc(self):
        self.check_script('validate.py')

    def test_render_refuses_a_v1_doc(self):
        self.check_script('render.py')

    def test_render_with_no_validate_still_refuses_a_v1_doc(self):
        with tempfile.TemporaryDirectory(prefix='explain-v1-') as d:
            p = os.path.join(d, 'explain.json')
            with open(p, 'w', encoding='utf-8') as fh:
                json.dump(DOCS['schema v1'], fh)
            r = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'render.py'), p, '--no-validate'], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stderr), (1, LINE))

    def test_an_unknown_version_is_named(self):
        r, _ = self.run_script('validate.py', {'version': 3})
        self.assertEqual((r.returncode, r.stderr), (1, "error: unknown version 3; write version 2 (references/explain-schema.md)\n"))


if __name__ == '__main__':
    unittest.main()
