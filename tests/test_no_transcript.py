"""A doc with no readable transcript (an unsupported harness, a deleted file, no agent session at all) validates and renders in both page kinds.
One test per seam: the pairing rule, the checks that still run, the secret rules, the page note and the hostile values of the reason."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from helpers2 import V2Case  # noqa: E402
from lib import check, check_session, page2, page_session, transcript  # noqa: E402
from test_session import good_doc  # noqa: E402

SKILL = os.path.join(os.path.dirname(HERE), 'skills', 'explain-change')
REASON = 'Windsurf keeps no readable session log'
MAX_REASON = 200  # the longest reason a page shows
CRED = 'Zq9!fakeCred7x'  # synthetic, only for these tests


def off(reason=REASON):
    def m(d):
        d['transcript_unavailable'] = reason
    return m


def text_of(html):
    return page2.page_text(html)


class Pairing(V2Case):
    """No --transcript needs a reason; a transcript and a reason together are refused. Both page kinds, library and CLI."""

    def test_v2_without_transcript_needs_a_reason(self):
        errs = self.assertInvalid(None, 'transcript: required', transcript=None)
        self.assertEqual(len([e for e in errs if e.startswith('transcript')]), 1)

    def test_v2_with_a_transcript_refuses_a_reason(self):
        self.assertInvalid(off(), 'transcript_unavailable: not allowed together with a transcript')

    def test_v2_doc_transcript_field_plus_a_reason_is_refused(self):
        self.assertInvalid(lambda d: d.update(transcript=self.transcript, transcript_unavailable=REASON), 'transcript_unavailable: not allowed together', transcript=None)

    def test_v2_reason_alone_is_accepted(self):
        errs, stats = self.validate(off(), transcript=None)
        self.assertEqual(errs, [])
        self.assertFalse(stats['transcript'])

    def test_session_without_transcript_needs_a_reason(self):
        errs, _ = check_session.validate(good_doc(), None)
        self.assertTrue(any(e.startswith('transcript: required') for e in errs), errs)

    def test_session_with_a_transcript_refuses_a_reason(self):
        from test_session import Case as SC

        class C(SC):
            def runTest(self):
                pass
        c = C()
        c.setUp()
        try:
            errs, _ = c.validate(lambda d: d.update(transcript_unavailable=REASON))
            self.assertTrue(any('transcript_unavailable: not allowed together with a transcript' in e for e in errs), errs)
        finally:
            c.doCleanups()

    def test_session_reason_alone_is_accepted(self):
        d = good_doc()
        d['transcript_unavailable'] = REASON
        errs, stats = check_session.validate(d, None)
        self.assertEqual(errs, [])
        self.assertFalse(stats['transcript'])

    def run_cli(self, script, doc, *args):
        path = os.path.join(self.repo, 'doc.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False)
        return subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', script), path, *args], capture_output=True, text=True,
                              env={**os.environ, 'EXPLAIN_PROJECTS_DIR': self.root})

    def test_cli_both_directions_for_validate(self):
        p = self.run_cli('validate.py', self.doc())
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(p.stdout.strip().splitlines()), 1, p.stdout)
        self.assertTrue(p.stdout.startswith('transcript: required'), p.stdout)
        self.assertIn('transcript_unavailable', p.stdout)
        p = self.run_cli('validate.py', self.doc(off()), '--transcript', self.transcript)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('not allowed together', p.stdout)
        p = self.run_cli('validate.py', self.doc(off()))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('transcript unavailable', p.stdout)

    def test_cli_render_refuses_the_same_pairs(self):
        p = self.run_cli('render.py', self.doc())
        self.assertEqual(p.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.repo, 'index.html')))
        p = self.run_cli('render.py', self.doc(off()), '--transcript', self.transcript)
        self.assertEqual(p.returncode, 1)
        self.assertIn('not allowed together', p.stdout)


class ChecksStillRun(V2Case):
    """Everything git can answer is still asked with no transcript."""

    def test_unknown_revision(self):
        self.assertInvalid(lambda d: (off()(d), d['range'].update(head='deadbeef' * 5)), 'range.head: unknown revision', transcript=None)

    def test_counts_differ_from_git(self):
        self.assertInvalid(lambda d: (off()(d), d['map']['modules'][1]['files'][0].update(add=99)), 'counts differ from git', transcript=None)

    def test_snippet_not_in_the_code(self):
        self.assertInvalid(lambda d: (off()(d), d['logic']['after'][0]['refs'][0].update(snippet='code that is not there')), 'snippet not found', transcript=None)

    def test_a_changed_file_left_out_of_the_map(self):
        self.assertInvalid(lambda d: (off()(d), d['map']['modules'].pop(4)), 'changed file not assigned', transcript=None)

    def test_a_source_kind_the_field_does_not_accept(self):
        self.assertInvalid(lambda d: (off()(d), d['rationale']['chosen'].update(source={'kind': 'tool_call', 'command': 'x y', 'excerpt': 'z w'})), 'source', transcript=None)

    def test_quotes_are_listed_as_not_compared(self):
        errs, stats = self.validate(off(), transcript=None)
        self.assertEqual(errs, [])
        self.assertEqual(stats['unverified'], 9)
        self.assertTrue(any('NOT checked' in w for w in stats['warnings']))

    def test_session_schema_and_theme_checks_still_run(self):
        d = good_doc()
        d['transcript_unavailable'] = REASON
        d['themes'][0]['status'] = 'finished'
        d['needs_you'][0]['theme'] = 'nope'
        errs, _ = check_session.validate(d, None)
        self.assertTrue(any('themes[0].status' in e for e in errs), errs)
        self.assertTrue(any('needs_you[0].theme' in e for e in errs), errs)


class Secrets(V2Case):
    def test_labelled_secret_in_a_quote_is_refused(self):
        self.assertInvalid(lambda d: (off()(d), d['requests'][0].update(quote='giới hạn pass: %s' % CRED)), 'requests[0].quote: contains', transcript=None)

    def test_a_value_the_user_quoted_is_hidden_wherever_it_appears(self):
        def m(d):
            off()(d)
            d['requests'][0].update(quote='giới hạn pass: %s' % CRED, result='Đã đặt %s cho nó.' % CRED)
        errs = self.assertInvalid(m, 'requests[0].result: contains a password, token or key that the session shows', transcript=None)
        self.assertFalse([e for e in errs if CRED in e])

    def test_session_doc_learns_from_its_own_quotes(self):
        d = good_doc()
        d['transcript_unavailable'] = REASON
        d['needs_you'][0]['source'] = {'kind': 'user_reported', 'quote': 'change it, pass: %s' % CRED}
        d['themes'][0]['outcome'] = 'The key %s is rotated.' % CRED
        errs, _ = check_session.validate(d, None)
        self.assertTrue(any(e.startswith('themes[0].outcome') and 'that the session shows' in e for e in errs), errs)

    def test_secret_in_the_reason_is_refused(self):
        self.assertInvalid(off('log gone, token: %s' % CRED), 'transcript_unavailable: contains what looks like', transcript=None)
        d = good_doc()
        d['transcript_unavailable'] = 'gone, glpat-' + 'Ab3dEf9hIjKl'
        errs, _ = check_session.validate(d, None)
        self.assertTrue(any(e.startswith('transcript_unavailable') for e in errs), errs)


class UnvalidatedRender(V2Case):
    """--no-validate still keeps a credential the doc's own quotes show out of the page."""

    def render_cli(self, doc, name):
        with tempfile.TemporaryDirectory(prefix='nt-unval-') as tmp:
            path = os.path.join(tmp, name)
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(doc, fh, ensure_ascii=False)
            p = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'render.py'), path, '--no-validate'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            with open(os.path.join(tmp, 'index.html'), encoding='utf-8') as fh:
                return fh.read()

    def test_change_page(self):
        d = self.doc(lambda d: (off()(d), d['requests'][0].update(quote='giới hạn pass: %s' % CRED, result='Đã đặt %s cho nó.' % CRED)))
        self.assertNotIn(CRED, self.render_cli(d, 'doc.json'))

    def test_session_page(self):
        d = good_doc()
        d['transcript_unavailable'] = REASON
        d['needs_you'][0]['source'] = {'kind': 'user_reported', 'quote': 'change it, pass: %s' % CRED}
        d['themes'][0]['outcome'] = 'The key %s is rotated.' % CRED
        self.assertNotIn(CRED, self.render_cli(d, 'session.json'))


class Docs(unittest.TestCase):
    def test_skill_md_has_the_no_transcript_path_for_each_harness_without_a_reader(self):
        with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn('### No transcript', text)
        body = text.split('### No transcript', 1)[1].split('\n## ', 1)[0]
        for h in ('Windsurf', 'Cline', 'Roo', 'Kiro', 'Aider', 'transcript_unavailable', 'Not checked against the session', "agent's own"):
            self.assertIn(h, body, h)


class HostileReason(V2Case):
    BAD = [('empty', ''), ('spaces only', '   \t '), ('newline', 'one\ntwo'), ('huge', 'x' * 5000), ('just over', 'x' * (MAX_REASON + 1)),
           ('integer', 5), ('boolean', True), ('list', ['gone']), ('object', {'why': 'gone'})]

    def test_v2_rejects_each_bad_value(self):
        for name, v in self.BAD:
            errs, _ = self.validate(off(v), transcript=None)
            self.assertTrue(errs, name)
            self.assertTrue(all(len(e) < 400 for e in errs), name)

    def test_session_rejects_each_bad_value(self):
        for name, v in self.BAD:
            d = good_doc()
            d['transcript_unavailable'] = v
            errs, _ = check_session.validate(d, None)
            self.assertTrue(errs, name)

    def test_the_longest_allowed_reason_passes(self):
        errs, _ = self.validate(off('x' * MAX_REASON), transcript=None)
        self.assertEqual(errs, [])

    def test_html_in_the_reason_is_escaped_on_both_pages(self):
        evil = '<script>alert(1)</script><img src=x onerror=y>'
        html = page2.render(self.doc(off(evil)), self.repo)
        self.assertNotIn('<script>alert(1)', html)
        self.assertNotIn('<img src=x', html)
        self.assertIn('&lt;script&gt;alert(1)', html)
        d = good_doc()
        d['transcript_unavailable'] = evil
        s = page_session.render(d, {})
        self.assertNotIn('<script>alert(1)', s)
        self.assertNotIn('<img src=x', s)
        self.assertIn('&lt;script&gt;alert(1)', s)

    def test_a_credential_in_the_reason_of_an_unvalidated_page_is_hidden(self):
        html = page2.render(self.doc(off('gone, token: %s' % CRED)), self.repo, validated=False)
        self.assertNotIn(CRED, html)
        d = good_doc()
        d['transcript_unavailable'] = 'gone, token: %s' % CRED
        self.assertNotIn(CRED, page_session.render(d, {}))

    def test_a_credential_cut_by_the_length_cap_leaves_no_piece(self):
        transcript.learn_quotes({'quote': 'pass: %s' % CRED})
        reason = 'x' * (MAX_REASON - 6) + CRED
        self.assertNotIn(CRED[:4], page2.render(self.doc(off(reason)), self.repo, validated=False))
        d = good_doc()
        d['transcript_unavailable'] = reason
        self.assertNotIn(CRED[:4], page_session.render(d, {}))

    def test_a_page_rendered_without_validation_still_caps_the_reason(self):
        html = page2.render(self.doc(off('y' * 5000)), self.repo, validated=False)
        self.assertLessEqual(html.count('y' * 50), 4)
        self.assertLess(len(html), 600000)
        d = good_doc()
        d['transcript_unavailable'] = 'y' * 5000
        self.assertLessEqual(page_session.render(d, {}).count('y' * 50), 4)


class ChangePageNote(V2Case):
    def render(self, lang, reason=REASON):
        return page2.render(self.doc(lambda d: (off(reason)(d), d.update(lang=lang))), self.repo)

    def test_vi_note_has_the_reason(self):
        t = text_of(self.render('vi'))
        self.assertIn('Chưa đối chiếu với phiên làm việc', t)
        self.assertNotIn('Chưa đối chiếu với phiên làm việc: ', t)  # the badge is the short form; the reason is its own line in the Evidence tab
        self.assertIn('Không có phiên làm việc để đối chiếu: ' + REASON, t)

    def test_en_note_has_the_reason(self):
        t = text_of(self.render('en'))
        self.assertIn('Not checked against the session', t)
        self.assertNotIn('Not checked against the session: ', t)
        self.assertIn('No session to compare with: ' + REASON, t)

    def test_a_checked_page_has_no_note(self):
        html = page2.render(self.doc(), self.repo, session_checked=True)
        self.assertNotIn('Chưa đối chiếu', html)
        self.assertNotIn('own account', html)

    def test_claims_that_need_the_session_say_they_are_the_agents_account(self):
        html = self.render('en')
        t = text_of(html)
        self.assertIn("From the agent's own account", t)
        self.assertEqual(len(re.findall(r'class="chip mut"[^>]*>(?:<svg.*?</svg>)?[^<]*own account', html)), 4)  # PHPUnit, lint, the worker's call, the user's own run
        vi = text_of(self.render('vi'))
        self.assertIn('Lời kể của agent', vi)

    def test_a_workers_report_keeps_its_own_label(self):
        d = self.doc(lambda d: (off()(d), d['evidence']['ran'][2].update(source={'kind': 'report', 'quote': 'five passed in the worker run'})))
        t = text_of(page2.render(d, self.repo))
        self.assertIn('Lời báo cáo của worker', t)

    def test_the_note_shows_no_code_or_file_line(self):
        t = text_of(self.render('en'))
        self.assertNotRegex(t, r'\.php:\d+')


class SessionPage(unittest.TestCase):
    def doc(self, lang='en', reason=REASON):
        d = good_doc()
        d['lang'] = lang
        d['transcript_unavailable'] = reason
        return d

    def test_all_tiers_render(self):
        h = page_session.render(self.doc(), {})
        for needle in ('id="sec-needs"', 'id="sec-dec"', 'id="sec-out"', 'id="journey"', 'Private repo created'):
            self.assertIn(needle, h)

    def test_the_note_has_the_reason_in_both_languages(self):
        self.assertIn('Not checked against the session: ' + REASON, text_of(page_session.render(self.doc('en'), {})))
        self.assertIn('Chưa đối chiếu với phiên làm việc: ' + REASON, text_of(page_session.render(self.doc('vi'), {})))

    def test_outward_counts_are_the_agents_own_and_it_says_so_once(self):
        for lang, phrase in (('en', "agent's own count"), ('vi', 'số đếm của agent')):
            t = text_of(page_session.render(self.doc(lang), {}))
            self.assertEqual(t.lower().count(phrase), 1, (lang, t.lower().count(phrase)))

    def test_a_checked_session_page_has_neither(self):
        h = page_session.render(self.doc(), {}, session_checked=True)
        self.assertNotIn('Not checked', h)
        self.assertNotIn("own count", h)
        self.assertNotIn('.nt{', h)
        self.assertIn('Counts only', h)
        self.assertIn('.nt{', page_session.render(self.doc(), {}))

    def test_no_code_or_file_line_on_the_page(self):
        t = text_of(page_session.render(self.doc(), {}))
        self.assertNotRegex(t, r'\w\.\w+:\d+')

    def test_cli_renders_a_session_doc_without_a_transcript(self):
        with tempfile.TemporaryDirectory(prefix='nt-sess-') as tmp:
            path = os.path.join(tmp, 'session.json')
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(self.doc(), fh)
            for script, args in (('validate.py', []), ('render.py', ['--text'])):
                p = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', script), path, *args], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertIn('Not checked against the session: ' + REASON, open(os.path.join(tmp, 'index.html.txt'), encoding='utf-8').read())

    def test_cli_session_without_the_pair_exits_1(self):
        with tempfile.TemporaryDirectory(prefix='nt-sess-') as tmp:
            path = os.path.join(tmp, 'session.json')
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(good_doc(), fh)
            p = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'validate.py'), path], capture_output=True, text=True)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(len(p.stdout.strip().splitlines()), 1, p.stdout)


class CollectWithoutTranscript(unittest.TestCase):
    def test_session_listing_points_to_the_no_transcript_path(self):
        with tempfile.TemporaryDirectory(prefix='nt-home-') as home:
            p = subprocess.run([sys.executable, os.path.join(SKILL, 'scripts', 'collect.py'), '--session', '--repo', home], capture_output=True, text=True,
                               env={**os.environ, 'HOME': home, 'EXPLAIN_PROJECTS_DIR': os.path.join(home, 'none')}, cwd=home)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('none found', p.stdout)
        self.assertIn('transcript_unavailable', p.stdout)


if __name__ == '__main__':
    unittest.main()
