"""Colour themes on the change page (explain-change/2): the same six themes, ids, picker and localStorage key as the session page, applied before first paint,
`render.py --theme` on a change doc, and the before/after logic (no Mermaid on this page) following the theme."""
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
from lib import page2, page_session, themes  # noqa: E402
from lib.i18n2 import STR2  # noqa: E402
from test_page_session import CHANGE, RENDER, SAMPLE, chromium  # noqa: E402

SKILL = os.path.join(os.path.dirname(HERE), 'skills', 'explain-change')
UI = os.path.join(SKILL, 'assets', 'ui')
KEY = themes.THEME_KEY
PRE_BLOCKED = ("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('blocked','SecurityError')}});"
               "window.__errs=[];addEventListener('error',e=>__errs.push(String(e.message)));")


def doc():
    with open(CHANGE, encoding='utf-8') as fh:
        return json.load(fh)


def change(theme=themes.THEMES[0], d=None):
    return page2.render(d or doc(), None, validated=False, session_checked=True, theme=theme)


class Markup(unittest.TestCase):
    def test_the_theme_is_applied_in_a_head_script_before_the_style_and_the_body(self):
        h = change()
        i, style, body = h.index("setAttribute('data-theme'"), h.index('<style>'), h.index('<body>')
        self.assertLess(h.index('<head>'), i)
        self.assertLess(i, style)
        self.assertLess(style, body)
        self.assertIn('localStorage.getItem', h[:style])
        self.assertIn('catch(e){}', h[:style])  # a blocked storage must not stop the script
        self.assertIn('<html lang="en" data-panel="open" data-theme="midnight">', h)

    def test_the_picker_is_a_labelled_native_select_in_the_header_with_every_theme(self):
        for lang, label in (('en', 'Appearance'), ('vi', 'Giao diện')):
            d = doc()
            d['lang'] = lang
            h = change(d=d)
            head = h[h.index('<header class="top">'):h.index('</header>')]
            self.assertRegex(head, r'<label class="picker"><span>%s</span><select id="skin"' % label)
            for tid in themes.THEMES:
                self.assertIn('<option value="%s"' % tid, head)
            self.assertEqual(head.count(' selected>'), 1)

    def test_the_default_is_midnight_and_the_renderer_bakes_the_requested_theme(self):
        self.assertEqual(themes.THEMES, ('midnight', 'navy', 'ocean', 'plum', 'graphite', 'pearl'))
        for tid in themes.THEMES:
            h = change(tid)
            self.assertIn('data-theme="%s">' % tid, h)
            self.assertIn('<option value="%s" selected>' % tid, h)
        self.assertIn('data-theme="midnight">', page2.render(doc(), None, validated=False))

    def test_the_renderer_refuses_an_unknown_theme(self):
        for bad in ('forest', 'NAVY', '', 'a" onload="x'):
            with self.assertRaises(ValueError):
                change(bad)

    def test_both_pages_share_one_list_and_one_storage_key(self):
        self.assertIs(page_session.THEMES, themes.THEMES)
        self.assertEqual(page_session.THEME_KEY, KEY)
        self.assertEqual(KEY, 'explain-change-theme')
        for name in ('page2.js', 'session.js'):  # the pickers store under that key
            with open(os.path.join(UI, name), encoding='utf-8') as fh:
                self.assertIn("localStorage.setItem('%s'," % KEY, fh.read(), name)
        for tid in themes.THEMES:
            self.assertIn('ses_theme_' + tid, STR2['en'])
            self.assertIn('ses_theme_' + tid, STR2['vi'])

    def test_the_change_page_has_no_mermaid_so_its_diagrams_are_html_that_the_tokens_colour(self):
        h = change()
        self.assertNotIn('mermaid', h.lower())
        self.assertIn('class="ba before', h)
        self.assertIn('class="ba after', h)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='th-chg-')
        self.addCleanup(self.tmp.cleanup)
        shutil.copy(CHANGE, os.path.join(self.tmp.name, 'password-autofill.v2.json'))
        shutil.copy(SAMPLE, os.path.join(self.tmp.name, 'day.session.json'))
        self.out = os.path.join(self.tmp.name, 'out.html')

    def run_render(self, name, *args):
        return subprocess.run([sys.executable, RENDER, os.path.join(self.tmp.name, name), '--no-validate', *args], capture_output=True, text=True)

    def test_theme_sets_the_default_of_a_change_doc(self):
        for tid in themes.THEMES:
            p = self.run_render('password-autofill.v2.json', '--theme', tid, '--out', self.out)
            self.assertEqual(p.returncode, 0, p.stderr)
            with open(self.out, encoding='utf-8') as fh:
                h = fh.read()
            self.assertIn('data-theme="%s">' % tid, h)
            self.assertIn('<option value="%s" selected>' % tid, h)

    def test_no_flag_opens_a_change_doc_in_midnight(self):
        self.assertEqual(self.run_render('password-autofill.v2.json', '--out', self.out).returncode, 0)
        with open(self.out, encoding='utf-8') as fh:
            self.assertIn('data-theme="midnight">', fh.read())

    def test_an_unknown_id_exits_1_with_one_line_and_writes_no_change_page(self):
        p = self.run_render('password-autofill.v2.json', '--theme', 'forest', '--out', self.out)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len(p.stderr.strip().splitlines()), 1)
        self.assertFalse(os.path.exists(self.out))

    def test_a_session_render_gives_its_linked_change_page_the_same_theme(self):
        with open(os.path.join(self.tmp.name, 'day.session.json'), encoding='utf-8') as fh:
            d = json.load(fh)
        linked = [t['change_doc'] for t in d['themes'] if t.get('change_doc')]
        self.assertTrue(linked, 'the sample session links a change page')
        p = self.run_render('day.session.json', '--theme', 'pearl')
        self.assertEqual(p.returncode, 0, p.stderr)
        page = os.path.join(self.tmp.name, page_session.change_page_name(linked[0]))
        with open(page, encoding='utf-8') as fh:
            self.assertIn('data-theme="pearl">', fh.read())


@unittest.skipUnless(chromium(), 'needs a chromium, chrome or brave binary')
class Dom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='th-chg-dom-', dir='/tmp')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_dom(self, probe, pre='', width=1440, theme=None, page_html=None):
        h = page_html or change(theme or themes.THEMES[0])
        h = h.replace('<head>', '<head><script>window.__errs=[];addEventListener("error",e=>__errs.push(String(e.message)));%s</script>' % pre, 1)
        h = h.replace('<body>', "<body><script>window.__first=document.documentElement.getAttribute('data-theme')</script>", 1)
        h = h.replace('</body>', '<script>setTimeout(()=>{const $=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];const out={};'
                                 'try{%s}catch(e){out.threw=String(e)}const pre=document.createElement("pre");pre.id="probe";pre.textContent=JSON.stringify(out);document.body.appendChild(pre)},700)</script></body>' % probe)
        f = os.path.join(self.tmp, 'p.html')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(h)
        prof = tempfile.mkdtemp(dir=self.tmp)
        p = subprocess.run([chromium(), '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--user-data-dir=' + prof, '--hide-scrollbars',
                            '--window-size=%d,900' % width, '--virtual-time-budget=5000', '--dump-dom', 'file://' + f], capture_output=True, text=True, timeout=120)
        m = re.search(r'<pre id="probe">(.*?)</pre>', p.stdout, re.S)
        self.assertTrue(m, 'no probe output: ' + p.stderr[-400:])
        out = json.loads(htmlmod.unescape(m.group(1)))
        self.assertNotIn('threw', out)
        return out

    PICK = ("const s=$('#skin');s.value='plum';s.dispatchEvent(new Event('change',{bubbles:true}));"
            "out.attr=document.documentElement.getAttribute('data-theme');out.stored=localStorage.getItem('%s');out.errs=__errs;out.value=s.value;out.first=window.__first;" % KEY)

    def test_the_picker_applies_the_pick_and_stores_it(self):
        r = self.run_dom(self.PICK)
        self.assertEqual((r['attr'], r['stored'], r['value'], r['errs'], r['first']), ('plum', 'plum', 'plum', [], 'midnight'))

    def test_a_stored_pick_is_applied_before_the_body_and_selected(self):
        r = self.run_dom("out.first=window.__first;out.attr=document.documentElement.getAttribute('data-theme');out.value=$('#skin').value", pre="localStorage.setItem('%s','pearl');" % KEY)
        self.assertEqual((r['first'], r['attr'], r['value']), ('pearl', 'pearl', 'pearl'))  # first is read at the top of <body>: no flash of the default

    def test_the_pick_made_on_the_session_page_opens_the_change_page_in_that_theme_and_back(self):
        """One storage key: the same stored pick sets both pages (a pick made on one page is read by the head script of the other)."""
        with open(SAMPLE, encoding='utf-8') as fh:
            sess = page_session.render(json.load(fh), {}, 'midnight')
        pre = "localStorage.setItem('%s','graphite');" % KEY
        for page_html in (sess, change()):
            r = self.run_dom("out.first=window.__first;out.value=$('#skin').value", pre=pre, page_html=page_html)
            self.assertEqual((r['first'], r['value']), ('graphite', 'graphite'))
        r = self.run_dom("const s=$('#skin');s.value='ocean';s.dispatchEvent(new Event('change',{bubbles:true}));out.stored=localStorage.getItem('%s')" % KEY)
        self.assertEqual(r['stored'], 'ocean')  # the key a session page reads

    def test_a_stored_value_that_is_not_a_theme_is_ignored(self):
        r = self.run_dom("out.first=window.__first;out.value=$('#skin').value", pre="localStorage.setItem('%s','\"><b>');" % KEY, theme='graphite')
        self.assertEqual((r['first'], r['value']), ('graphite', 'graphite'))

    def test_a_blocked_local_storage_falls_back_to_the_default_without_an_error(self):
        r = self.run_dom(self.PICK.replace("out.stored=localStorage.getItem('%s');" % KEY, ''), pre=PRE_BLOCKED, theme='ocean')
        self.assertEqual(r['first'], 'ocean')
        self.assertEqual((r['attr'], r['value'], r['errs']), ('plum', 'plum', []))

    def test_escape_in_the_picker_does_not_clear_the_selected_node(self):
        r = self.run_dom("const b=qa('.node .hit')[0];b.click();out.before=!!$('.node.sel');const s=$('#skin');s.focus();s.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));"
                         "out.after=!!$('.node.sel');document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));out.cleared=!$('.node.sel')")
        self.assertEqual((r['before'], r['after'], r['cleared']), (True, True, True))

    LOOK = ("document.head.insertAdjacentHTML('beforeend','<style>*,*::before{transition:none!important;animation:none!important}</style>');"  # a transition would still hold the old colour
            "const cs=(s,p)=>getComputedStyle($(s))[p];const look=()=>({body:cs('body','color'),scheme:cs('html','colorScheme'),node:cs('.node','backgroundColor'),after:cs('.ba.after','backgroundColor'),"
            "before:cs('.ba.before','backgroundColor'),step:cs('.ba.after .step p','color'),label:cs('.ba.before .stp .s-label','color'),mf:cs('.mf','backgroundColor'),"
            "mfrow:cs('.mf-row','backgroundColor'),dlg:cs('.dlg','backgroundColor'),dlgic:cs('.dlg .ic','color'),arrow:cs('.stp+.stp','--text-3')+'|'+getComputedStyle($('.stp+.stp'),'::before').backgroundColor,"
            "edge:getComputedStyle($('.e')||$('.node')).stroke,cap:cs('.ba-h .chip','backgroundColor')});"
            "const set=t=>{const s=$('#skin');s.value=t;s.dispatchEvent(new Event('change',{bubbles:true}))};")

    def test_the_logic_diagrams_follow_the_theme(self):
        """The before/after blocks are HTML, not Mermaid: fills, text, rings and arrows come from the tokens, so switching to pearl changes each of them."""
        r = self.run_dom(self.LOOK + "out.navy=look();set('pearl');out.pearl=look();set('midnight');out.back=look()")
        n, p = r['navy'], r['pearl']
        self.assertEqual(r['back'], n)
        self.assertEqual((n['body'], p['body'], p['scheme']), ('rgb(245, 246, 255)', 'rgb(28, 26, 59)', 'light'))
        for k in ('node', 'after', 'step', 'label', 'dlg', 'mfrow', 'cap'):
            self.assertNotEqual(n[k], p[k], k)
        self.assertEqual(p['after'], 'rgb(232, 225, 251)')  # pearl --hl: the "after" block fill
        self.assertEqual(p['step'], 'rgb(28, 26, 59)')

    def test_every_theme_changes_the_page_and_none_leaves_a_dark_fill_on_pearl(self):
        r = self.run_dom(self.LOOK + "out.t={};for(const t of ['midnight','navy','ocean','plum','graphite','pearl']){set(t);out.t[t]=look()}")
        fills = {t: v['node'] + v['after'] for t, v in r['t'].items()}
        self.assertEqual(len(set(fills.values())), 6)
        self.assertEqual(r['t']['pearl']['node'], 'rgba(255, 255, 255, 0.55)')  # the outside node: surface over the light ground


if __name__ == '__main__':
    unittest.main()
