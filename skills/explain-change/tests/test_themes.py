"""Colour themes of the session page: one [data-theme] block each with no literal colour elsewhere, WCAG AA measured from the tokens, the picker (applies,
persists, survives a blocked localStorage), no flash, `--theme`, and the keyboard and landmark behaviour of the header, the nav and the count bubbles."""
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
from lib import page_session  # noqa: E402
from lib.i18n2 import STR2  # noqa: E402
from test_page_session import RENDER, SAMPLE, busy_doc, chromium, page, sample  # noqa: E402

SKILL = os.path.dirname(HERE)
CSS = os.path.join(SKILL, 'assets', 'ui', 'session.css')
BASE = os.path.join(SKILL, 'assets', 'ui', 'page2.css')
KEY = page_session.THEME_KEY


def read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def blocks():
    """{theme id: {property: value}} from session.css; navy is the :root of page2.css plus the helper tokens of the :root of session.css."""
    css = read(CSS)
    out = {}
    for tid in page_session.THEMES[1:]:
        m = re.search(r'\[data-theme="%s"\]\{(.*?)\n\}' % tid, css, re.S)
        assert m, tid
        out[tid] = dict(re.findall(r'(--[\w-]+|color-scheme):([^;]+);', m.group(1)))
    base = dict(re.findall(r'(--[\w-]+|color-scheme):([^;]+);', re.search(r':root\{(.*?)\n\}', read(BASE), re.S).group(1)))
    base.update(re.findall(r'(--[\w-]+|color-scheme):([^;]+);', re.search(r':root\{--mk(.*?)\}\n', css, re.S).group(0)))
    out['navy'] = {k: v.strip() for k, v in base.items()}
    return {t: {k: v.strip() for k, v in d.items()} for t, d in out.items()}


def rgb(v):
    v = v.strip()
    if v.startswith('#'):
        v = v[1:]
        v = ''.join(c * 2 for c in v) if len(v) == 3 else v
        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4)), 1.0
    m = re.match(r'rgba?\(([^)]*)\)', v)
    p = [float(x) for x in m.group(1).split(',')]
    return tuple(p[:3]), p[3] if len(p) > 3 else 1.0


def over(fg, a, bg):
    return tuple(a * f + (1 - a) * b for f, b in zip(fg, bg))


def lum(c):
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def measure(t):
    """(min text contrast, min ring contrast, min white-on-fill contrast) of a theme, the way design/mockups/themes/NOTES.md measures them: text, text-2, text-3
    on surface-solid, raised, hl and the page ground; the status colours on surface-solid and hl; each status ring (its colour at the ring alpha over surface-solid) against surface-solid."""
    c = lambda k: rgb(t[k])[0]
    grounds = [c('surface-solid'), c('raised'), c('hl')]
    page_ground = [c('bg-0'), c('bg-1'), c('bg-2')]  # the header text sits on the page gradient itself
    text = min(ratio(c(k), g) for k in ('text', 'text-2', 'text-3') for g in grounds + page_ground)
    status = min(ratio(c(k), g) for k in ('accent-text', 'ok', 'warn', 'bad', 'n-ui', 'n-service') for g in (grounds[0], grounds[2]))
    white = min(ratio((255, 255, 255), c(k)) for k in ('accent', 'ok-fill'))
    mk = float(t['mk-ring'].rstrip('%')) / 100 if 'mk-ring' in t else .6
    ring = min(ratio(over(c(k), mk, grounds[0]), grounds[0]) for k in ('ok', 'bad', 'warn', 'n-ui', 'n-service'))
    return min(text, status), ring, white


class ThemeTokens(unittest.TestCase):
    def setUp(self):
        self.css = read(CSS)
        self.t = {k: {n.lstrip('-'): v for n, v in d.items()} for k, d in blocks().items()}

    def test_every_theme_is_one_data_theme_block_and_navy_is_the_default(self):
        self.assertEqual(page_session.THEMES[0], 'navy')
        self.assertEqual(set(self.t), set(page_session.THEMES))
        self.assertNotIn('forest', self.css)
        for tid in page_session.THEMES[1:]:
            self.assertEqual(len(re.findall(r'\[data-theme="%s"\]\{' % tid, self.css)), 1, tid)
        for lang in ('vi', 'en'):
            for tid in page_session.THEMES:
                self.assertIn('ses_theme_' + tid, STR2[lang])

    def test_no_literal_colour_outside_the_root_and_the_theme_blocks(self):
        rules = re.sub(r':root\{--mk:32px.*?\n  --on-fill:[^}]*\}', '', self.css, flags=re.S)
        rules = re.sub(r'\[data-theme="\w+"\]\{.*?\n\}', '', rules, flags=re.S)
        rules = re.sub(r'/\*.*?\*/', '', rules, flags=re.S)
        self.assertEqual(re.findall(r'#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d', rules), [])

    def test_every_theme_sets_every_property_navy_sets(self):
        need = {k for k in self.t['navy'] if k not in ('muted', 'glow', 'shadow-float', 'n-data', 'n-test', 'n-external', 'warn-soft', 'font', 'mono', 'on-fill')
                and not re.match(r'(fs|r|s|t|mk|lane)-?', k) and k not in ('ease', 'mk', 'mk-gap', 'lane-h', 'kdot-ring', 'mk-ring')}
        for tid in page_session.THEMES[1:]:
            self.assertEqual(sorted(need - set(self.t[tid])), [], tid)

    def test_wcag_aa_text_and_rings_in_every_theme(self):
        for tid in page_session.THEMES:
            text, ring, white = measure(self.t[tid])
            self.assertGreaterEqual(text, 4.5, (tid, 'text'))
            self.assertGreaterEqual(white, 4.5, (tid, 'white on fills'))
            self.assertGreaterEqual(ring, 3.0, (tid, 'ring'))


class ThemeFlag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='th-cli-')
        self.addCleanup(self.tmp.cleanup)
        self.doc = os.path.join(self.tmp.name, 'day.session.json')
        shutil.copy(SAMPLE, self.doc)
        shutil.copy(os.path.join(SKILL, 'reference', 'examples', 'password-autofill.v2.json'), os.path.join(self.tmp.name, 'password-autofill.v2.json'))

    def run_render(self, *args):
        return subprocess.run([sys.executable, RENDER, self.doc, '--no-validate', *args], capture_output=True, text=True)

    def test_a_valid_id_sets_the_default_baked_into_the_page(self):
        for tid in page_session.THEMES:
            p = self.run_render('--theme', tid)
            self.assertEqual(p.returncode, 0, p.stderr)
            h = read(os.path.join(self.tmp.name, 'index.html'))
            self.assertIn('<html lang="en" data-theme="%s">' % tid, h)
            self.assertIn('<option value="%s" selected>' % tid, h)
            self.assertEqual(h.count(' selected>'), 1)

    def test_no_flag_keeps_navy(self):
        self.assertEqual(self.run_render().returncode, 0)
        self.assertIn('<html lang="en" data-theme="navy">', read(os.path.join(self.tmp.name, 'index.html')))

    def test_an_unknown_id_exits_1_with_one_line_naming_the_valid_ids(self):
        for bad in ('forest', 'NAVY', '', 'a" onload="x'):
            p = self.run_render('--theme', bad)
            self.assertEqual(p.returncode, 1, (bad, p.stdout, p.stderr))
            self.assertEqual(p.stdout, '')
            lines = p.stderr.strip().splitlines()
            self.assertEqual(len(lines), 1, p.stderr)
            self.assertTrue(lines[0].startswith('error: unknown theme'))
            for tid in page_session.THEMES:
                self.assertIn(tid, lines[0])
            self.assertFalse(os.path.exists(os.path.join(self.tmp.name, 'index.html')))

    def test_the_renderer_refuses_an_unknown_id_too(self):
        with self.assertRaises(ValueError):
            page_session.render(sample(), {}, 'forest')


class Head(unittest.TestCase):
    def test_the_theme_is_set_in_a_head_script_before_the_style_and_the_body(self):
        h = page(sample())
        i, style, body = h.index("setAttribute('data-theme'"), h.index('<style>'), h.index('<body>')
        self.assertLess(h.index('<head>'), i)
        self.assertLess(i, style)
        self.assertLess(style, body)
        self.assertIn('localStorage.getItem', h[:style])
        self.assertIn('catch(e){}', h[:style])  # a blocked storage must not stop the script
        self.assertEqual(h.count("setAttribute('data-theme'"), 2)  # the head script and the picker; nothing else writes it

    def test_the_picker_is_a_labelled_native_select_with_every_theme(self):
        for lang, label in (('en', 'Appearance'), ('vi', 'Giao diện')):
            d = sample()
            d['lang'] = lang
            h = page(d)
            self.assertRegex(h, r'<label class="picker"><span>%s</span><select id="skin"' % label)
            for tid in page_session.THEMES:
                self.assertIn('<option value="%s"' % tid, h)

    def test_english_never_calls_the_colour_scheme_a_theme_and_vietnamese_names_read_as_colours(self):
        en, vi = STR2['en'], STR2['vi']
        self.assertEqual(en['ses_theme_label'], 'Appearance')
        self.assertEqual(vi['ses_theme_label'], 'Giao diện')
        for tid in page_session.THEMES:
            self.assertNotRegex(en['ses_theme_' + tid], r'(?i)theme')
        self.assertNotRegex(en['ses_theme_label'], r'(?i)theme')
        self.assertEqual([vi['ses_theme_' + t] for t in page_session.THEMES], ['Xanh đêm', 'Đại dương', 'Tím mận', 'Than chì', 'Ngọc trai (sáng)'])
        self.assertNotIn('Hải quân', vi.values())

    def test_landmarks_and_the_nav_targets(self):
        h = page(sample())
        self.assertEqual(h.count('<header '), 1)
        self.assertEqual(h.count('<nav '), 1)
        self.assertEqual(h.count('<main '), 1)
        nav = re.search(r'<nav class="jump" aria-label="([^"]+)">(.*?)</nav>', h, re.S)
        self.assertTrue(nav.group(1))
        targets = re.findall(r'href="#([\w-]+)" data-goto="\1"', nav.group(2))
        self.assertEqual(len(targets), 4)
        for t in targets:
            self.assertIn('id="%s"' % t, h)
        self.assertLess(h.index('<header '), h.index('<nav '))
        self.assertLess(h.index('</header>'), h.index('<main '))

    def test_the_panels_default_view_shows_the_decided_and_outward_sections_and_never_collapses_an_irreversible_choice(self):
        d = sample()
        h = page(d)
        panel = h.split('<aside class="card panel"', 1)[1]
        ov = panel.split('<section class="tp"', 1)[0]
        self.assertIn('class="ov ov-dec"', ov)
        self.assertIn('class="ov ov-out"', ov)
        dec = ov.split('class="ov ov-dec"', 1)[1].split('class="ov ov-out"', 1)[0]
        acc = dec.split('<details class="acc">', 1)
        self.assertEqual(len(acc), 2)
        for x in d['decided']:
            self.assertEqual(x['text'] in acc[0], x['reversible'] is False, x['text'])  # an irreversible choice sits outside the accordion
            self.assertEqual(x['text'] in acc[1], x['reversible'] is not False, x['text'])
        self.assertIn('<details class="acc" open>', ov)  # the outward actions are open by default
        d['decided'] = [x for x in d['decided'] if x['reversible'] is False]
        self.assertNotIn('<details class="acc">', page(d))  # nothing reversible, no accordion
        for x in d['decided']:
            d['decided'] = [dict(x, reversible=True)]
        self.assertNotIn('ses_dec_rev', page(d))


PRE_BLOCKED = ("Object.defineProperty(window,'localStorage',{get(){throw new DOMException('blocked','SecurityError')}});"
               "window.__errs=[];addEventListener('error',e=>__errs.push(String(e.message)));")


@unittest.skipUnless(chromium(), 'needs a chromium, chrome or brave binary')
class Dom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='th-', dir='/tmp')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_dom(self, doc, probe, pre='', width=1440, theme=None):
        h = page_session.render(doc, {}, theme or page_session.THEMES[0])
        h = h.replace('<head>', '<head><script>window.__errs=[];addEventListener("error",e=>__errs.push(String(e.message)));%s</script>' % pre, 1)
        h = h.replace('<body>', "<body><script>window.__first=document.documentElement.getAttribute('data-theme')</script>", 1)
        h = h.replace('</body>', '<script>setTimeout(()=>{const $=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];const out={};'
                                 'const fin=()=>{const pre=document.createElement("pre");pre.id="probe";pre.textContent=JSON.stringify(out);document.body.appendChild(pre)};'
                                 'try{%s}catch(e){out.threw=String(e)}if(!out.async)fin()},700)</script></body>' % probe)
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
            "out.attr=document.documentElement.getAttribute('data-theme');out.stored=localStorage.getItem('%s');out.errs=__errs;out.value=s.value;"
            "out.first=window.__first;out.sel=s.tagName;" % KEY)

    def test_the_picker_applies_the_pick_and_stores_it(self):
        r = self.run_dom(sample(), self.PICK)
        self.assertEqual((r['attr'], r['stored'], r['value'], r['sel'], r['errs']), ('plum', 'plum', 'plum', 'SELECT', []))
        self.assertEqual(r['first'], 'navy')  # the baked default until a pick exists

    def test_a_stored_pick_is_applied_before_the_body_and_selected_in_the_picker(self):
        r = self.run_dom(sample(), "out.first=window.__first;out.attr=document.documentElement.getAttribute('data-theme');out.value=$('#skin').value;out.js=document.documentElement.classList.contains('js')",
                         pre="localStorage.setItem('%s','pearl');" % KEY)
        self.assertEqual((r['first'], r['attr'], r['value'], r['js']), ('pearl', 'pearl', 'pearl', True))

    def test_a_stored_value_that_is_not_a_theme_is_ignored(self):
        r = self.run_dom(sample(), "out.first=window.__first;out.value=$('#skin').value", pre="localStorage.setItem('%s','\"><b>');" % KEY, theme='graphite')
        self.assertEqual((r['first'], r['value']), ('graphite', 'graphite'))

    def test_a_blocked_local_storage_falls_back_to_the_default_without_an_error(self):
        r = self.run_dom(sample(), self.PICK.replace("out.stored=localStorage.getItem('%s');" % KEY, ''), pre=PRE_BLOCKED, theme='ocean')
        self.assertEqual(r['first'], 'ocean')  # the baked default, not an exception
        self.assertEqual((r['attr'], r['value']), ('plum', 'plum'))  # the pick still applies for this visit
        self.assertEqual(r['errs'], [])

    def test_the_computed_colours_follow_the_theme(self):
        r = self.run_dom(sample(), "const g=()=>getComputedStyle(document.body).color;out.navy=g();const s=$('#skin');s.value='pearl';s.dispatchEvent(new Event('change'));out.pearl=g();out.scheme=getComputedStyle(document.documentElement).colorScheme")
        self.assertEqual(r['navy'], 'rgb(245, 246, 255)')
        self.assertEqual(r['pearl'], 'rgb(28, 26, 59)')
        self.assertEqual(r['scheme'], 'light')

    def test_a_long_theme_title_wraps_in_its_chip_and_is_never_cut(self):
        d = sample()
        long = 'Xoá mật khẩu bị lộ khỏi lịch sử git và đổi lại mọi khoá đã dùng ở các dịch vụ liên quan'
        d['themes'][d['needs_you'][0]['theme'] and next(i for i, t in enumerate(d['themes']) if t['id'] == d['needs_you'][0]['theme'])]['title'] = long
        probe = ("out.chips=qa('.tchip').map(c=>{const t=c.querySelector('.t'),cs=getComputedStyle(t);return {text:t.textContent.length,sw:c.scrollWidth,cw:c.clientWidth,tsw:t.scrollWidth,tcw:t.clientWidth,"
                 "th:t.getBoundingClientRect().height,lh:parseFloat(cs.lineHeight)||0,over:cs.textOverflow,ws:cs.whiteSpace}})")
        for width in (1440, 800):
            r = self.run_dom(d, probe, width=width)
            long_chips = [c for c in r['chips'] if c['text'] >= 60]
            self.assertTrue(long_chips, 'the fixture has a chip with a 60+ character title')
            for c in long_chips:
                self.assertLessEqual(c['sw'], c['cw'], c)
                self.assertLessEqual(c['tsw'], c['tcw'], c)
                self.assertNotEqual(c['over'], 'ellipsis', c)
                self.assertNotEqual(c['ws'], 'nowrap', c)

    OPEN = ("const cl=$('.mk.cl');cl.focus();cl.click();"
            "const st=()=>({pressed:qa('.mk[aria-pressed=true]').length,focusOn:document.activeElement===cl,clPressed:cl.getAttribute('aria-pressed'),def:!!$('.empty-panel.on'),tp:qa('.tp.on').length});")

    def test_escape_on_an_open_count_bubble_closes_it_and_returns_focus_to_that_bubble(self):
        r = self.run_dom(busy_doc(), self.OPEN + "out.open=st();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));out.after=st();out.connected=cl.isConnected")
        self.assertEqual(r['open']['tp'], 1)
        self.assertFalse(r['open']['def'])
        self.assertTrue(r['after']['focusOn'], r)
        self.assertTrue(r['connected'])
        self.assertEqual((r['after']['tp'], r['after']['def']), (0, True))

    def test_escape_with_focus_inside_the_panel_returns_focus_to_the_bubble(self):
        r = self.run_dom(busy_doc(), self.OPEN + "out.inPanel=document.activeElement===$('#panel');document.querySelector('#panel .close').focus();"
                         "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));out.after=st()")
        self.assertTrue(r['inPanel'])
        self.assertTrue(r['after']['focusOn'], r)

    def test_aria_pressed_is_true_on_the_selected_bubble_only(self):
        r = self.run_dom(busy_doc(), self.OPEN + "out.cl=st();const m=qa('.lane')[1].querySelector('.mk:not([hidden])');m.focus();m.click();out.marker={pressed:qa('.mk[aria-pressed=true]').length,m:m.getAttribute('aria-pressed'),cl:cl.getAttribute('aria-pressed')};"
                         "$('.lh').click();out.head=qa('.mk[aria-pressed=true]').length;")
        self.assertEqual((r['cl']['pressed'], r['cl']['clPressed']), (1, 'true'))
        self.assertEqual(r['marker'], {'pressed': 1, 'm': 'true', 'cl': 'false'})
        self.assertEqual(r['head'], 0)

    def test_a_relayout_keeps_the_open_bubble_pressed_and_focused(self):
        """A relayout rebuilds the count bubbles; the one that opened the panel must be found again, pressed and (if it had focus) focused."""
        r = self.run_dom(busy_doc(), self.OPEN + "cl.focus();const from=cl.dataset.from,to=cl.dataset.to;out.async=1;$('.lanes').style.paddingRight='3px';"
                         "setTimeout(()=>{const p=qa('.mk[aria-pressed=true]');out.n=p.length;out.same=!!p[0]&&p[0].classList.contains('cl')&&p[0].dataset.from===from&&p[0].dataset.to===to;"
                         "out.rebuilt=!cl.isConnected;out.focus=!!p[0]&&document.activeElement===p[0];document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));"
                         "out.back=document.activeElement.classList.contains('cl')&&document.activeElement.dataset.from===from;out.pressedAfter=qa('.mk[aria-pressed=true]').length;fin()},400);")
        self.assertTrue(r['rebuilt'], 'the old bubble should have been replaced')
        self.assertEqual(r['n'], 1)
        self.assertTrue(r['same'], r)
        self.assertTrue(r['focus'], r)
        self.assertTrue(r['back'], r)
        self.assertEqual(r['pressedAfter'], 0)


    def test_a_link_to_a_decided_item_leaves_the_theme_and_opens_the_accordion_that_holds_it(self):
        d = sample()
        rev = next(i for i, x in enumerate(d['decided']) if x['reversible'] is not False) + 1
        r = self.run_dom(d, "$('.lane .lh').click();out.theme=!!$('.tp.on');const a=$('.tp.on .links a[data-goto=\"dec-%d\"]')||$('a[data-goto=\"dec-%d\"]');"
                            "const lane=a.closest('.tp')&&a.closest('.tp').dataset.id;out.found=!!a;$('.lane[data-id=\"'+lane+'\"] .lh').click();"
                            "$('.tp.on a[data-goto=\"dec-%d\"]').click();out.def=!!$('.empty-panel.on');out.tp=qa('.tp.on').length;out.open=$('#dec-%d').closest('details').open;"
                            "out.lanes=qa('.lane.sel').length" % ((rev,) * 4))
        self.assertTrue(r['found'])
        self.assertEqual((r['def'], r['tp'], r['open'], r['lanes']), (True, 0, True, 0), r)

    def test_a_nav_link_leaves_the_theme_and_shows_the_default_view(self):
        r = self.run_dom(sample(), "$('.lane .lh').click();out.theme=!!$('.tp.on');$('.jump a[data-goto=\"sec-out\"]').click();out.def=!!$('.empty-panel.on');out.tp=qa('.tp.on').length;"
                                   "const b=$('#sec-out').getBoundingClientRect();out.visible=b.bottom>0&&b.top<innerHeight")
        self.assertTrue(r['theme'])
        self.assertEqual((r['def'], r['tp'], r['visible']), (True, 0, True), r)

    def test_the_page_opens_on_the_default_view_not_on_a_theme(self):
        r = self.run_dom(sample(), "out.def=!!$('.empty-panel.on');out.tp=qa('.tp.on').length;out.sel=qa('.lane.sel').length;out.hidden=$('#panel').hidden")
        self.assertEqual((r['def'], r['tp'], r['sel'], r['hidden']), (True, 0, 0, False))


    def test_escape_inside_the_theme_picker_does_not_close_the_panel(self):
        r = self.run_dom(sample(), "$('.lane .lh').click();const s=$('#skin');s.focus();s.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));out.tp=qa('.tp.on').length")
        self.assertEqual(r['tp'], 1)


if __name__ == '__main__':
    unittest.main()
