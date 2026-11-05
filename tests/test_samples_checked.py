"""The bundled change and session samples are checked against their synthetic transcripts, through the real path: the readers take a transcript only
inside the harness's own folder, so the files are copied to $HOME/.claude/projects/<slug>/ in a throwaway HOME (tests/sample_env.py). No guard is loosened.
Each claim has a test that goes red when its data is broken, and a control that breaks the transcript and expects the refusal."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sample_env as env  # noqa: E402
from helpers import SKILL  # noqa: E402,F401  (puts scripts/ on sys.path)
from lib import transcript  # noqa: E402

UNCHECKED = re.compile(r'not checked|chưa kiểm|unverified', re.I)


class Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='samples-checked-', dir='/tmp')
        cls.repo = os.path.join(cls.tmp, 'repo')
        cls.home = os.path.join(cls.tmp, 'home')
        cls.base, cls.head = env.build_repo(cls.repo)
        cls.folder = env.build_home(cls.home)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def t(self, name):
        return os.path.join(self.folder, name)

    def validate_change(self, *extra, home=None):
        return env.script('validate.py', env.CHANGE, '--repo', self.repo, *extra, home=home or self.home)

    def validate_session(self, *extra, home=None):
        return env.script('validate.py', env.SESSION, *extra, home=home or self.home)

    def broken_home(self, name, old, new):
        """A second HOME whose copy of transcript `name` has `old` replaced by `new` (once, and `old` must be there)."""
        home = tempfile.mkdtemp(prefix='broken-home-', dir=self.tmp)
        folder = env.build_home(home)
        path = os.path.join(folder, name)
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        self.assertEqual(text.count(old), 1, old)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text.replace(old, new))
        return home


class Validates(Case):
    def test_the_change_sample_validates_ok_with_its_transcript(self):
        p = self.validate_change('--transcript', self.t('password-autofill.v2.transcript.jsonl'))
        self.assertEqual((p.returncode, p.stdout.splitlines()[0]), (0, 'ok'), p.stdout + p.stderr)
        self.assertIn('unverified 0', p.stdout)
        self.assertNotIn('warning', p.stdout + p.stderr)

    def test_the_change_sample_finds_its_transcript_through_its_own_field(self):
        p = self.validate_change()
        self.assertEqual((p.returncode, p.stdout.splitlines()[0]), (0, 'ok'), p.stdout + p.stderr)

    def test_the_session_sample_validates_ok_with_its_transcript(self):
        p = self.validate_session('--transcript', self.t('portal-day.session.transcript.jsonl'))
        self.assertEqual((p.returncode, p.stdout.splitlines()[0]), (0, 'ok'), p.stdout + p.stderr)
        self.assertIn('transcript checked', p.stdout)
        self.assertIn('not compared 0', p.stdout)
        self.assertNotIn('warning', p.stdout + p.stderr)

    def test_the_samples_carry_no_reason_for_a_missing_transcript(self):
        for path in (env.CHANGE, env.SESSION):
            with open(path, encoding='utf-8') as fh:
                doc = json.load(fh)
            self.assertNotIn('transcript_unavailable', doc, path)
            self.assertTrue(doc['transcript'].startswith('~/.claude/projects/'), path)

    def test_the_change_sample_range_is_the_one_of_the_synthetic_repo(self):
        with open(env.CHANGE, encoding='utf-8') as fh:
            rng = json.load(fh)['range']
        self.assertEqual((rng['base'], rng['head']), (self.base, self.head))


class Pages(Case):
    def render(self, kind):
        out = os.path.join(self.tmp, 'pages-' + kind)
        os.makedirs(out, exist_ok=True)
        doc = env.CHANGE if kind == 'change' else env.SESSION
        p = env.script('render.py', doc, '--repo', self.repo, '--out', os.path.join(out, 'index.html'), '--text', home=self.home)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return sorted(os.path.join(out, f) for f in os.listdir(out) if f.endswith(('.html', '.txt')))

    def test_the_rendered_change_page_does_not_say_it_is_not_checked(self):
        files = self.render('change')
        self.assertEqual(len(files), 2)
        for f in files:
            with open(f, encoding='utf-8') as fh:
                self.assertIsNone(UNCHECKED.search(fh.read()), f)

    def test_the_rendered_session_page_and_its_change_page_do_not_say_it_is_not_checked(self):
        files = self.render('session')
        self.assertEqual(len(files), 4)  # the session page, the change page it links, and the text of each
        for f in files:
            with open(f, encoding='utf-8') as fh:
                self.assertIsNone(UNCHECKED.search(fh.read()), f)

    def test_the_session_page_does_not_call_the_outward_counts_the_agents_own(self):
        txt = [f for f in self.render('session') if f.endswith('index.html.txt')][0]
        with open(txt, encoding='utf-8') as fh:
            text = fh.read()
        self.assertNotIn("agent's own", text)


class Controls(Case):
    """The same samples against a transcript with one fact broken are refused, so the passes above are not vacuous."""

    def test_a_changed_user_request_is_refused(self):
        home = self.broken_home('password-autofill.v2.transcript.jsonl', 'check this bug where the browser overwrites my saved password',
                                'check this bug where the browser overwrites my saved login')
        p = self.validate_change(home=home)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('requests[0].quote', p.stdout)

    def test_a_missing_tool_output_is_refused(self):
        home = self.broken_home('password-autofill.v2.transcript.jsonl', 'Tests  3 passed (3)', 'Tests  2 passed (2)')
        p = self.validate_change(home=home)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('result excerpt is not in the result', p.stdout)

    def test_a_changed_session_request_is_refused(self):
        home = self.broken_home('portal-day.session.transcript.jsonl', 'i ran chmod +x on it', 'i ran chmod 755 on it')
        p = self.validate_session(home=home)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('quote not found', p.stdout)

    def test_a_push_missing_from_the_session_breaks_the_outward_counts(self):
        home = self.broken_home('portal-day.session.transcript.jsonl', 'gh repo create portal-lib --private --source . --remote origin', 'echo portal-lib')
        p = self.validate_session(home=home)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('repo_created', p.stdout)

    def test_the_folder_limit_still_holds_for_the_files_beside_the_samples(self):
        p = self.validate_session('--transcript', os.path.join(env.EXAMPLES, 'portal-day.session.transcript.jsonl'))
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('transcript must be under', p.stdout)


class Transcripts(unittest.TestCase):
    def files(self):
        return [os.path.join(env.EXAMPLES, n) for n in env.TRANSCRIPTS]

    def test_every_line_is_a_json_record_of_a_claude_code_session(self):
        for f in self.files():
            with open(f, encoding='utf-8') as fh:
                rows = [json.loads(line) for line in fh]
            self.assertGreater(len(rows), 10, f)
            for r in rows:
                self.assertIn(r['type'], ('user', 'assistant'), f)
                self.assertFalse(r['isSidechain'])

    def test_they_hold_only_made_up_content(self):
        for f in self.files():
            with open(f, encoding='utf-8') as fh:
                text = fh.read()
            for bad in ('/home/', '/Users/', 'C:\\\\', 'sk-', 'ghp_', 'BEGIN '):
                self.assertNotIn(bad, text, (f, bad))
            for line in text.splitlines():
                self.assertFalse(transcript.has_secret(line), (f, line[:80]))
            self.assertIsNone(re.search(r'[\w.]+@(?!example\.test)[\w.]+\.\w+', text), f)


if __name__ == '__main__':
    unittest.main()
