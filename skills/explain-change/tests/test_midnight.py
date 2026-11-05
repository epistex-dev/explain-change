"""The midnight theme (the intro video's colours) on all three page kinds: it is the default when no theme is given, `--theme midnight` renders its tokens in a
real browser, and a stored pick of the reader still wins over the default."""
import html as htmlmod
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
from helpers import SKILL  # noqa: E402,F401  (puts scripts/ on sys.path)
from lib import themes  # noqa: E402
from test_page_session import RENDER, chromium  # noqa: E402

SKILL = os.path.dirname(HERE)
EXAMPLES = os.path.join(SKILL, 'references', 'examples')
DOCS = {'change': 'password-autofill.v2.json', 'session': 'portal-day.session.json', 'flow': 'claim-check.flow.json'}
PROBE = ("<script>addEventListener('load',()=>{const r=getComputedStyle(document.documentElement),b=getComputedStyle(document.body);"
         "const o={attr:document.documentElement.getAttribute('data-theme'),sel:document.querySelector('#skin').value,accent:r.getPropertyValue('--accent-text').trim(),"
         "surface:r.getPropertyValue('--surface').trim(),ring:r.getPropertyValue('--ring').trim(),scheme:r.colorScheme,body:b.backgroundColor,text:b.color,"
         "glows:(b.backgroundImage.match(/radial-gradient/g)||[]).length,panel:getComputedStyle(document.querySelector('.card,.a-panel,.panel')).backgroundImage.slice(0,15)};"
         "const p=document.createElement('pre');p.id='probe';p.textContent=JSON.stringify(o);document.body.appendChild(p)})</script>")


class Midnight(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='midnight-', dir='/tmp')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for f in DOCS.values():
            shutil.copy(os.path.join(EXAMPLES, f), self.tmp)

    def render(self, kind, *args):
        out = os.path.join(self.tmp, kind + '.html')
        p = subprocess.run([sys.executable, RENDER, os.path.join(self.tmp, DOCS[kind]), '--no-validate', '--out', out, *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(out, encoding='utf-8') as fh:
            return fh.read(), out

    def test_it_is_the_first_theme_so_the_default_of_every_renderer(self):
        self.assertEqual(themes.THEMES[0], 'midnight')

    def test_no_theme_given_opens_all_three_page_kinds_in_midnight(self):
        for kind in DOCS:
            h, _ = self.render(kind)
            self.assertIn('data-theme="midnight">', h, kind)
            self.assertIn('<option value="midnight" selected>', h, kind)
            self.assertEqual(h.count(' selected>'), 1, kind)

    def test_a_session_render_with_no_theme_also_writes_its_change_pages_in_midnight(self):
        self.render('session')
        pages = [f for f in os.listdir(self.tmp) if f.endswith('.html') and f != 'session.html']
        self.assertTrue(pages, 'the sample session links a change page')
        for f in pages:
            with open(os.path.join(self.tmp, f), encoding='utf-8') as fh:
                self.assertIn('data-theme="midnight">', fh.read(), f)

    def test_the_other_themes_are_still_offered_and_still_apply(self):
        for kind in DOCS:
            h, _ = self.render(kind, '--theme', 'navy')
            self.assertIn('data-theme="navy">', h, kind)
            for tid in themes.THEMES:
                self.assertIn('<option value="%s"' % tid, h, (kind, tid))

    @unittest.skipUnless(chromium(), 'needs a chromium, chrome or brave binary')
    def test_theme_midnight_renders_the_midnight_tokens_in_a_browser_on_all_three_page_kinds(self):
        for kind in DOCS:
            for args in (('--theme', 'midnight'), ()):
                got = self.look(kind, *args)
                self.assertEqual((got['attr'], got['sel']), ('midnight', 'midnight'), (kind, args))
                self.assertEqual((got['accent'], got['ring'], got['scheme']), ('#f9b6e2', 'rgba(150,166,255,.26)', 'dark'), kind)
                self.assertIn('linear-gradient(180deg,rgba(44,54,130,.62)', got['surface'].replace(' ', ''), kind)  # the glassy surface
                self.assertEqual(got['panel'], 'linear-gradient', kind)  # ... is what the cards and panels paint
                self.assertEqual((got['body'], got['text']), ('rgb(11, 15, 51)', 'rgb(245, 246, 255)'), kind)
                self.assertEqual(got['glows'], 3, kind)  # the dot grid and the two corner glows are background layers of the body, not blurred elements

    @unittest.skipUnless(chromium(), 'needs a chromium, chrome or brave binary')
    def test_a_stored_pick_still_wins_over_the_midnight_default(self):
        for kind in DOCS:
            got = self.look(kind, pre="localStorage.setItem('%s','pearl');" % themes.THEME_KEY)
            self.assertEqual((got['attr'], got['sel'], got['scheme']), ('pearl', 'pearl', 'light'), kind)

    def look(self, kind, *args, pre=''):
        h, out = self.render(kind, *[a for a in args])
        h = h.replace('<head>', '<head><script>%s</script>' % pre, 1).replace('</body>', PROBE + '</body>', 1)
        f = os.path.join(self.tmp, 'probe-%s.html' % kind)
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(h)
        prof = tempfile.mkdtemp(dir=self.tmp)
        p = subprocess.run([chromium(), '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--user-data-dir=' + prof, '--hide-scrollbars',
                            '--window-size=1440,900', '--virtual-time-budget=5000', '--dump-dom', 'file://' + f], capture_output=True, text=True, timeout=120)
        m = re.search(r'<pre id="probe">(.*?)</pre>', p.stdout, re.S)
        self.assertTrue(m, 'no probe output: ' + p.stderr[-300:])
        return json.loads(htmlmod.unescape(m.group(1)))


if __name__ == '__main__':
    unittest.main()
