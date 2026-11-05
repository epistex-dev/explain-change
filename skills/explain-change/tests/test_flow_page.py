"""explain-flow/1 page: render.py dispatches by `kind`, the page shows no source, every step and error is in the HTML without JS, a branch target is a link,
the theme allowlist holds, both languages have every string, and the change and session pages stay byte-identical."""
import hashlib
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
from test_flow import FlowCase, src  # noqa: E402  (puts scripts/ on sys.path)
from lib import page_flow, themes  # noqa: E402
from lib.i18n2 import STR2  # noqa: E402

SKILL = os.path.dirname(HERE)
RENDER = os.path.join(SKILL, 'scripts', 'render.py')
EXAMPLES = os.path.join(SKILL, 'reference', 'examples')
EXCERPT = 'text = open(path).read()'


class PageCase(FlowCase):
    def flow(self, lang='en'):
        d = self.good()
        d['lang'] = lang
        d['question'] = 'How does a doc get checked? (see app.py:12)'
        d['steps'][1]['branches'] = [{'when': 'The text is empty', 'to': 'problems'}, {'when': 'The text has content', 'to': 's3'}]
        d['steps'][2]['branches'] = [{'when': 'It is shown', 'to': 'end'}]
        d['steps'][0]['errors'] = [{'id': 'e0', 'name': 'Path unreadable', 'result': 'The load stops with an error.', 'sources': [src('src/app.py', (1, 3), EXCERPT)]}]
        return d

    def render(self, doc, *extra):
        path = os.path.join(self._docs.name, 'doc.flow.json')
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh)
        out = os.path.join(self._docs.name, 'index.html')
        if os.path.exists(out):
            os.remove(out)
        p = subprocess.run([sys.executable, RENDER, path, '--repo', self.repo, *extra], capture_output=True, text=True)
        if not os.path.exists(out):
            return p, None
        with open(out, encoding='utf-8') as fh:
            return p, fh.read()

    def page(self, lang='en', *extra):
        p, h = self.render(self.flow(lang), *extra)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return h


class WrongTypes(PageCase):
    """A wrongly typed field is a list of lines and exit 1 from render.py too, and no page is written."""

    def test_nothing_is_written_for_a_wrongly_typed_field(self):
        for name, mutate in (('part is a list', lambda d: d['steps'][0].update(part=['x'])), ('part is a dict', lambda d: d['steps'][0].update(part={'a': 1})),
                             ('branch to is a list', lambda d: d['steps'][1]['branches'][0].update(to=['a'])),
                             ('branch to is a dict', lambda d: d['steps'][1]['branches'][0].update(to={'a': 1})),
                             ('lone surrogate in a title', lambda d: d.update(title='bad \ud800 title')),
                             ('lone surrogate in a source path', lambda d: d['steps'][0]['sources'][0].update(path='a\ud800b'))):
            with self.subTest(name):
                d = self.flow()
                mutate(d)
                p, h = self.render(d)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIsNone(h)
                self.assertNotIn('Traceback', p.stderr)
                self.assertTrue(p.stdout.strip(), 'one line per problem on stdout')

    def test_the_unvalidated_path_does_not_crash_either(self):
        d = self.flow()
        d['steps'][0]['part'] = ['x']
        p, h = self.render(d, '--no-validate')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertNotIn('Traceback', p.stderr)


class Map(PageCase):
    def builder(self, mutate=None):
        d = self.flow()
        if mutate:
            mutate(d)
        return page_flow.Builder(d, 'pearl', None, None)

    def test_a_part_shows_its_own_icon_and_falls_back_to_the_generic_one(self):
        h = self.page_of(lambda d: d['parts'][1].update(icon='shield-check'))
        self.assertIn('data-mod="checker"', h)
        node = h[h.index('data-mod="checker"'):]
        self.assertIn('href="#i-shield-check"', node[:node.index('</h3>')])
        node = h[h.index('data-mod="caller"'):]
        self.assertIn('href="#i-globe"', node[:node.index('</h3>')])  # no icon given: the generic one of its zone
        self.assertEqual(h.count('<symbol id="i-file-search"'), 1)

    def page_of(self, mutate):
        d = self.flow()
        mutate(d)
        p, h = self.render(d)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return h

    def test_consecutive_steps_in_different_parts_make_a_connector(self):
        e = {(a, b): (n, bi) for a, b, n, _, bi in self.builder().edges()}
        self.assertEqual(e[('checker', 'caller')], ([2, 3], 0))
        self.assertEqual(e[('checker', 'problems')], ([2], 0))

    def test_a_part_the_step_reads_from_gets_a_connector_to_it(self):
        before = {(a, b): n for a, b, n, *_ in self.builder().edges()}
        self.assertNotIn(('log', 'checker'), before)

        def reads(d):
            d['parts'].append({'id': 'log', 'name': 'Log', 'where': 'outside', 'role': 'The record.', 'sources': []})
            d['steps'][1].update(reads=['log'])
        after = {(a, b): n for a, b, n, *_ in self.builder(reads).edges()}
        self.assertEqual(after[('log', 'checker')], [2])

    def test_two_parts_that_hand_over_to_each_other_share_one_two_headed_line(self):
        def back(d):
            d['steps'][2]['branches'] = [{'when': 'It is shown', 'to': 's1'}, {'when': 'Done', 'to': 'end'}]
        e = {(a, b): bi for a, b, _, _, bi in self.builder(back).edges()}
        self.assertEqual(e[('checker', 'caller')], 1)
        self.assertNotIn(('caller', 'checker'), e)

    def test_each_card_says_where_it_hands_over_for_screens_without_lines(self):
        h = self.page_of(lambda d: None)
        self.assertIn('<p class="f-next" aria-label="Hands over to Caller, Problem list">', h)  # on the Checker card
        with open(os.path.join(SKILL, 'assets', 'ui', 'flow.css'), encoding='utf-8') as fh:
            css = fh.read()
        self.assertRegex(css, r'@media \(max-width:1100px\)\{[^@]*\.f-next\{display:flex\}')

    def test_the_lines_are_routed_by_the_script_not_drawn_straight(self):
        with open(os.path.join(SKILL, 'assets', 'ui', 'flow.js'), encoding='utf-8') as fh:
            js = fh.read()
        self.assertIn('function route(', js)
        self.assertIn('rounded(', js)


class Dispatch(PageCase):
    def test_a_flow_doc_renders_by_its_kind(self):
        p, h = self.render(self.flow())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn('Traceback', p.stderr)
        self.assertIn('<main', h)
        self.assertIn('How a document is checked', h)

    def test_an_unknown_kind_exits_with_one_line(self):
        d = self.flow()
        d['kind'] = 'explain-flow/9'
        p, h = self.render(d)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIsNone(h)
        lines = p.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, p.stderr)
        self.assertIn('explain-flow/9', lines[0])
        self.assertIn('explain-flow/1', lines[0])


class Leaks(PageCase):
    def test_no_source_excerpt_or_file_line_reaches_the_page(self):
        h = self.page()
        for bad in ('src/app.py', EXCERPT, 'excerpt', 'sources', 'app.py:12', self.sha):
            self.assertNotIn(bad, h)
        self.assertIsNone(re.search(r'\w\.\w{1,5}:\d+', re.sub(r'(?s)<(style|script).*?</\1>', '', h)))


class NoScript(PageCase):
    def test_every_step_and_error_is_in_the_html_without_js(self):
        d = self.flow()
        p, h = self.render(d)
        self.assertEqual(h.count('<article '), len(d['steps']))
        self.assertNotIn(' hidden', ''.join(re.findall(r'<article [^>]*>', h)))
        for s in d['steps']:
            for v in (s['name'], s['takes_in'], s['gives_back']):
                self.assertIn(v.split(' (')[0], h)
            for e in s['errors']:
                self.assertIn(e['name'], h)
                self.assertIn(e['result'], h)
        self.assertEqual(h.count('class="f-err"'), 2)


class Links(PageCase):
    def test_a_branch_target_is_a_link_to_that_step(self):
        h = self.page()
        art = re.search(r'<article id="step-2".*?</article>', h, re.S).group(0)
        self.assertRegex(art, r'<a href="#step-3" data-step="3">')
        self.assertIn('id="step-3"', h)
        self.assertNotRegex(art, r'href="#(problems|end)"')


class Themes(PageCase):
    def test_the_theme_allowlist_holds(self):
        h = self.page()
        self.assertIn(json.dumps(list(themes.THEMES)), h)
        self.assertIn(themes.THEME_KEY, h)
        self.assertEqual(re.findall(r'<option value="(\w+)"', h), list(themes.THEMES))
        self.assertLess(h.index("setAttribute('data-theme'"), h.index('<style>'))
        for tid in themes.THEMES:
            self.assertIn('<html lang="en" data-theme="%s">' % tid, self.page('en', '--theme', tid))
        with self.assertRaises(ValueError):
            page_flow.render(self.flow(), 'forest')
        p, out = self.render(self.flow(), '--theme', 'forest')
        self.assertEqual(p.returncode, 1)
        self.assertIsNone(out)
        self.assertEqual(len(p.stderr.strip().splitlines()), 1)


class Language(PageCase):
    def test_both_languages_have_every_key_and_the_page_shows_none_raw(self):
        flow = {k for k in STR2['en'] if k.startswith('fl_') and not k.endswith('_1')}
        self.assertTrue(flow)
        for lang in ('en', 'vi'):
            self.assertEqual({k for k in STR2[lang] if k.startswith('fl_') and not k.endswith('_1')}, flow, lang)
            h = self.page(lang)
            self.assertIn('<html lang="%s"' % lang, h)
            text = re.sub(r'(?s)<(style|script|svg).*?</\1>', '', h)
            self.assertNotRegex(text, r'fl_\w+|%[sd]|\{n\}')
        self.assertRegex(self.page('vi'), r'<span>Giao diện</span>')
        self.assertRegex(self.page('en'), r'<span>Appearance</span>')


class Landmarks(PageCase):
    def test_landmarks_and_the_current_step(self):
        h = self.page()
        for tag in ('<header', '<nav', '<main', '<footer'):
            self.assertIn(tag, h)
        route = re.search(r'<nav.*?</nav>', h, re.S).group(0)
        self.assertEqual(route.count('aria-current="step"'), 1)
        self.assertRegex(route, r'<button type="button" data-step="1" aria-current="step">')
        self.assertIn('Checked against the code at commit %s, ' % self.sha[:7], h)


class Contract(unittest.TestCase):
    """The change page and the session page render the same bytes as before the flow page was added (sha256 of the example renders)."""
    PINS = {'password-autofill.v2.json': '65988d14730573cd55bea79dc3bab8a36aeec30760453faba6e3b309d1ace128',
            'portal-day.session.json': 'f06d14be7905cd127ff6603d1c267837e836a5abadaefb5e421a9cf253a5db6d'}

    def test_existing_pages_render_byte_identical_html(self):
        for name, pin in self.PINS.items():
            with tempfile.TemporaryDirectory(prefix='flow-contract-') as tmp:
                for f in ('password-autofill.v2.json', 'portal-day.session.json'):
                    shutil.copy(os.path.join(EXAMPLES, f), tmp)
                out = os.path.join(tmp, 'out.html')
                p = subprocess.run([sys.executable, RENDER, os.path.join(tmp, name), '--no-validate', '--out', out], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                with open(out, 'rb') as fh:
                    self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), pin, name)


if __name__ == '__main__':
    unittest.main()
