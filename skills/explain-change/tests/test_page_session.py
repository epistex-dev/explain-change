"""The explain-session/1 page: tiers, copy in both languages, marker size and spacing, clusters beyond a lane's capacity, the panel's keyboard
behaviour, the change-page link, and the content rules (no code or file:line, no labels of doubt, one name per concept).
Lane geometry is tested twice: the pure fit (assets/ui/fit.js) under node over many widths, and the real DOM in headless chromium (skipped without one)."""
import copy
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from helpers import SKILL  # noqa: E402,F401  (puts scripts/ on sys.path)
from lib import outward, page2, page_session  # noqa: E402
from lib.i18n2 import STR2, count  # noqa: E402

SKILL = os.path.dirname(HERE)
SAMPLE = os.path.join(SKILL, 'references', 'examples', 'portal-day.session.json')
CHANGE = os.path.join(SKILL, 'references', 'examples', 'password-autofill.v2.json')
RENDER = os.path.join(SKILL, 'scripts', 'render.py')
DRIVER = os.path.join(HERE, 'fit_driver.js')
MK, GAP = 32, 8
DOUBT = ('unverified', 'not verified', 'unchecked', 'not checked', 'inferred', 'chưa kiểm', 'chưa xác', 'suy luận', 'chua kiem')


def sample():
    with open(SAMPLE, encoding='utf-8') as fh:
        return json.load(fh)


def fit_all(jobs):
    p = subprocess.run([shutil.which('node') or 'node', DRIVER], input=json.dumps(jobs), capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


def busy_doc(n=40):
    """The sample plus one theme with n crowded events, so its lane overflows at every width the page is tested at."""
    d = sample()
    d['themes'].append({'id': 'busy', 'title': 'Crowded theme', 'status': 'done', 'outcome': 'Many small steps.', 'events': [
        {'kind': ['asked', 'decided', 'done', 'redirected', 'blocked'][i % 5], 'text': 'Step number %d' % (i + 1), 'order': 1 + i // 6, 'source': {'inferred': True}}
        for i in range(n)]})
    return d


def page(doc, links=None, checked=True):
    """A page as the reader of a checked session sees it; the sample declares no session, and test_no_transcript.py covers the page that says so."""
    return page_session.render(doc, links or {}, session_checked=checked)


def words(html):
    return page2.page_text(html)


class Tiers(unittest.TestCase):
    def setUp(self):
        self.doc = sample()
        self.html = page(self.doc, {3: 'password-autofill.v2.html'})

    def test_tier_zero_has_the_four_blocks(self):
        for needle in ('class="band"', 'class="card b-sum"', 'class="card b-need"', 'class="ov ov-dec"', 'class="ov ov-out"', 'id="sum"'):
            self.assertIn(needle, self.html)
        self.assertEqual(self.html.count('class="need"'), len(self.doc['needs_you']))
        self.assertEqual(self.html.count('class="dec"'), len(self.doc['decided']))

    def test_summary_counts_the_themes_of_each_status(self):
        key = self.html.split('class="skey"', 1)[1].split('</ul>', 1)[0]
        for st in {t['status'] for t in self.doc['themes']}:
            n = sum(1 for t in self.doc['themes'] if t['status'] == st)
            self.assertIn('<li class="st-%s">' % st, key)
            self.assertRegex(key, r'<li class="st-%s">.*?<b class="cnt">%d</b>' % (st, n))
        self.assertEqual(sum(int(n) for n in re.findall(r'<b class="cnt">(\d+)</b>', key)), len(self.doc['themes']))

    def test_every_decision_is_marked_reversible_or_not(self):
        n = len(self.doc['decided'])
        irrev = sum(1 for x in self.doc['decided'] if not x['reversible'])
        self.assertEqual(self.html.count('class="chip rev"'), n - irrev)
        self.assertEqual(self.html.count('class="chip irrev"'), irrev)

    def test_tier_one_has_a_lane_per_theme_a_legend_and_a_panel(self):
        self.assertEqual(self.html.count('class="lane"'), len(self.doc['themes']))
        self.assertEqual(self.html.count('class="tp"'), len(self.doc['themes']))
        legend = self.html.split('class="keyline"', 1)[1].split('</ul>', 1)[0]
        for k in page_session.KINDS:
            self.assertIn('class="k-%s"' % k, legend)
        self.assertIn('id="panel"', self.html)

    def test_markers_are_buttons_in_order_and_one_per_event(self):
        n = sum(len(t['events']) for t in self.doc['themes'])
        self.assertEqual(len(re.findall(r'<button class="mk k-', self.html)), n)
        lane = self.html.split('id="theme-2"', 1)[1].split('class="lane"', 1)[0]
        kinds = re.findall(r'class="mk k-(\w+)"', lane)
        self.assertEqual(kinds, [e['kind'] for e in self.doc['themes'][1]['events']])

    def test_events_are_laid_out_by_order_then_list_position(self):
        d = sample()
        d['themes'][0]['events'] = [{'kind': 'done', 'text': 'Later one', 'order': 5, 'source': {'inferred': True}},
                                    {'kind': 'asked', 'text': 'First by order', 'order': 2, 'source': {'inferred': True}},
                                    {'kind': 'decided', 'text': 'Tie, listed second', 'order': 2, 'source': {'inferred': True}}]
        lane = page(d).split('id="theme-1"', 1)[1].split('class="lane"', 1)[0]
        self.assertEqual(re.findall(r'class="mk k-(\w+)"', lane), ['asked', 'decided', 'done'])

    def test_tier_two_link_only_on_a_theme_with_a_change_doc(self):
        self.assertEqual(self.html.count('class="btn"'), 1)
        self.assertIn('href="password-autofill.v2.html"', self.html)
        self.assertNotIn('class="btn"', page(self.doc))

    def test_each_section_opens_with_its_conclusion(self):
        for hid in ('h-needs', 'h-dec', 'h-out', 'h-jr'):
            self.assertRegex(self.html, r'<h2 id="%s">[^<]{8,}</h2>' % hid)
        self.assertIn('<h2 id="h-needs">3 things only you can do</h2>', self.html)
        self.assertIn('6 choices made for you, 1 cannot be undone', self.html)
        self.assertIn('8 themes, 28 events; 3 hit a blocker, 2 were redirected', self.html)

    def test_page_is_one_file_under_the_limit(self):
        self.assertLess(len(self.html.encode('utf-8')), page2.MAX_BYTES)
        self.assertNotRegex(self.html, r'(?:src|href)="https?://')
        self.assertIn('data:font/woff2;base64,', self.html)
        self.assertLess(len(page(busy_doc(200)).encode('utf-8')), page2.MAX_BYTES)


class SectionCounts(unittest.TestCase):
    """Rubric item 8: the sections together cover every item of the doc, and each fact is in full in one section."""

    def test_every_item_of_the_doc_is_on_the_page(self):
        d = sample()
        html = page(d)
        text = words(html)
        outside = words(html.split('<aside class="card panel"', 1)[0])  # everything but the panel: the strip, the lanes
        for t in d['themes']:
            self.assertIn(t['title'], text)
            self.assertIn(t['outcome'], text)
            for e in t['events']:
                self.assertIn(e['text'], text)
                self.assertNotIn(e['text'], outside, e['text'])  # an event is told in full in the panel only; its lane marker carries a label
        for x in d['needs_you'] + d['decided']:
            self.assertEqual(text.count(x['text']), 1, x['text'])
        self.assertEqual(text.count(d['summary']), 1)

    def test_outward_kinds_are_counted_once_each(self):
        d = sample()
        html = page(d)
        self.assertEqual(html.count('class="out"'), len(d['outward']))

    def test_theme_panels_link_to_needs_you_and_decided_instead_of_repeating_them(self):
        d = sample()
        html = page(d)
        panels = html.split('<section class="tp"', 1)[1]  # the theme panels; the panel's default view holds the decided items in full
        for x in d['needs_you'] + d['decided']:
            self.assertNotIn(x['text'], panels)
        self.assertEqual(panels.count('data-goto="need-'), len(d['needs_you']))
        self.assertEqual(panels.count('data-goto="dec-'), len(d['decided']))


class Outward(unittest.TestCase):
    def doc(self, count_, scratch):
        d = sample()
        for o in d['outward']:
            if o['kind'] == 'delete':
                o['count'] = count_
                if scratch is None:
                    o.pop('scratch', None)
                else:
                    o['scratch'] = scratch
        return d

    def test_real_deletes_are_an_outward_card_and_scratch_is_one_count_line(self):
        t = words(page(self.doc(60, 47)))
        self.assertIn('13 deletes', t)
        self.assertIn('Also 47 cleanups of temp folders (scratch), not listed', t)
        self.assertEqual(t.count('scratch'), 1)

    def test_a_delete_entry_of_scratch_only_has_no_card(self):
        html = page(self.doc(5, 5))
        self.assertNotIn('deletes</div>', html)
        self.assertNotIn('1 delete', words(html))
        self.assertIn('Also 5 cleanups of temp folders (scratch), not listed', words(html))
        self.assertIn('4 kinds of action left your working copy', html)

    def test_without_a_scratch_count_all_deletes_are_real(self):
        t = words(page(self.doc(3, None)))
        self.assertIn('3 deletes', t)
        self.assertNotIn('scratch', t)

    def test_nothing_outward(self):
        d = sample()
        d['outward'] = []
        t = words(page(d))
        self.assertIn('Nothing left your working copy', t)

    def test_every_kind_has_copy_and_an_icon(self):
        for lang in ('en', 'vi'):
            for k in outward.KINDS:
                self.assertIn('ses_o_' + k, STR2[lang])
                self.assertIn(k, page_session.OUT_ICON)


class Copy(unittest.TestCase):
    def test_vi_and_en_pages_use_their_own_copy(self):
        d = sample()
        en = words(page(d))
        d['lang'] = 'vi'
        vi_html = page(d)
        vi = words(vi_html)
        self.assertIn('<html lang="vi" data-theme="midnight">', vi_html)
        for key in ('ses_sec_needs', 'ses_sec_decided', 'ses_sec_out', 'ses_sec_journey', 'ses_k_blocked', 'ses_rev', 'ses_irrev', 'ses_t2_btn'):
            self.assertIn(STR2['vi'][key], vi if key != 'ses_t2_btn' else page(dict(d), {3: 'x.html'}))
            self.assertIn(STR2['en'][key], en if key != 'ses_t2_btn' else page(sample(), {3: 'x.html'}))
        self.assertNotIn(STR2['en']['ses_sec_needs'], vi)
        self.assertNotIn(STR2['vi']['ses_sec_needs'], en)

    def test_both_languages_define_the_same_session_keys(self):
        vi = {k for k in STR2['vi'] if k.startswith('ses_')}
        en = {k for k in STR2['en'] if k.startswith('ses_') and not k.endswith('_1')}
        self.assertEqual(vi, en)

    def test_every_session_key_is_used(self):
        with open(os.path.join(SKILL, 'scripts', 'lib', 'page_session.py'), encoding='utf-8') as fh:
            src = fh.read()
        for rel in (('assets', 'ui', 'session.js'), ('scripts', 'lib', 'themes.py')):
            with open(os.path.join(SKILL, *rel), encoding='utf-8') as fh:
                src += fh.read()
        families = ('ses_st_', 'ses_k_', 'ses_o_', 'ses_theme_')  # looked up as 'ses_st_' + status, and so on
        for k in (k for k in STR2['en'] if k.startswith('ses_') and not k.endswith('_1')):
            self.assertTrue("'%s'" % k in src or k.startswith(families) and any("'%s'" % f in src for f in families if k.startswith(f)), k)

    def test_count_uses_the_plural_helper(self):
        d = sample()
        d['needs_you'] = d['needs_you'][:1]
        self.assertIn('1 thing only you can do', page(d))
        d['needs_you'] = []
        self.assertIn('Nothing waits on you', page(d))
        self.assertEqual(count(STR2['en'], 'ses_o_push', 1), '1 push')
        self.assertEqual(count(STR2['en'], 'ses_o_push', 2), '2 pushes')
        self.assertEqual(count(STR2['vi'], 'ses_o_push', 1), '1 lần push')
        d = sample()
        d['themes'] = d['themes'][:1]
        d['needs_you'], d['decided'], d['outward'] = [], [], []
        self.assertIn('1 theme, 4 events', page(d))

    def test_a_vietnamese_page_keeps_tone_marks_in_inlined_fonts(self):
        d = sample()
        d['lang'] = 'vi'
        html = page(d)
        self.assertIn('Bản đồ phiên làm việc', html)
        self.assertIn('U+1EA0-1EF9', html)  # the Vietnamese subset of Inter is inlined


class ContentRules(unittest.TestCase):
    def test_no_code_diff_or_file_line(self):
        d = sample()
        d['themes'][0]['events'][0]['text'] = 'Fixed `x = f(y)` in app/main.py:42 and lib/a.js:7:3'
        d['themes'][0]['outcome'] = 'Edited `render()` (scripts/render.py:12).'
        html = page(d)
        t = words(html)
        self.assertNotIn('`', html.split('<script type="application/json"', 1)[0])
        self.assertNotRegex(t, r'\w\.[A-Za-z]{1,5}:\d+')
        self.assertIn('app/main.py', t)
        for needle in ('@@ ', '--- a/', '+++ b/', 'diff --git'):
            self.assertNotIn(needle, t)
        self.assertNotRegex(t, r'(?m)^[+-]\s?\S')

    def test_no_source_command_or_quote_reaches_the_page(self):
        d = sample()
        t = page(d)
        for th in d['themes']:
            for e in th['events']:
                srcs = e['source'] if isinstance(e['source'], list) else [e['source']]
                for s in srcs:
                    for f in ('command', 'excerpt', 'quote'):
                        if len(s.get(f) or '') >= 8:
                            self.assertNotIn(s[f], words(t), s[f])

    def test_no_label_of_doubt_in_either_language(self):
        for lang in ('en', 'vi'):
            d = sample()
            d['lang'] = lang
            low = page(d, {3: 'x.html'}).split('<script type="application/json"', 1)[0].lower()
            low = re.sub(r'<style>.*?</style>', '', low, flags=re.S)
            for w in DOUBT:
                self.assertNotIn(w, low, (lang, w))
            self.assertFalse([k for k, v in STR2[lang].items() if k.startswith('ses_') and any(w in v.lower() for w in DOUBT)])

    def test_a_credential_that_got_past_validation_is_hidden(self):
        from lib import transcript
        d = sample()
        d['themes'][0]['outcome'] = 'The token is ' + 'ghp' + '_AbCdEfGh1234567890AbCdEfGh1234567890 for now.'
        html = page(d)
        self.assertNotIn('ghp' + '_AbCdEfGh', html)
        self.assertIn(transcript.MASK, html)

    def test_doc_text_is_escaped(self):
        d = sample()
        d['themes'][0]['title'] = '<img src=x onerror=alert(1)>'
        d['themes'][0]['events'][0]['text'] = '"><script>alert(2)</script>'
        html = page(d)
        self.assertNotIn('<img src=x', html)
        self.assertEqual(html.count('<script>alert(2)'), 0)

    def test_one_name_per_concept(self):
        t = words(page(sample())).lower()
        for banned in ('group ', 'swimlane', 'task list'):
            self.assertNotIn(banned, t)
        self.assertEqual(STR2['en']['ses_sec_needs'], 'Needs you')
        self.assertEqual(STR2['en']['ses_sec_decided'], 'Agent decided for you')


class Fit(unittest.TestCase):
    """The lane fit under node: markers are MK wide and never closer than GAP; a lane with more events than fit shows count items."""

    def test_spacing_and_bounds_hold_for_random_lanes(self):
        rnd = random.Random(7)
        jobs = []
        for _ in range(300):
            n = rnd.randint(1, 60)
            hi = rnd.randint(1, 40)
            jobs.append({'orders': sorted(rnd.randint(1, hi) for _ in range(n)), 'W': rnd.randint(MK, 900), 'mk': MK, 'gap': GAP, 'lo': 1, 'hi': hi})
        for j, r in zip(jobs, fit_all(jobs)):
            xs = [it['x'] for it in r['items']]
            self.assertLessEqual(len(xs), r['cap'], j)
            self.assertGreaterEqual(xs[0], 0)
            self.assertLessEqual(xs[-1] + MK, max(j['W'], MK), j)
            for a, b in zip(xs, xs[1:]):
                self.assertGreaterEqual(b - (a + MK), GAP, (j, xs))
            self.assertEqual(sorted(i for it in r['items'] for i in it['i']), list(range(len(j['orders']))))

    def test_a_lane_that_fits_has_no_cluster_and_one_that_overflows_has(self):
        fits = {'orders': [1, 2, 3, 4], 'W': 400, 'mk': MK, 'gap': GAP, 'lo': 1, 'hi': 4}
        over = {'orders': list(range(1, 31)), 'W': 400, 'mk': MK, 'gap': GAP, 'lo': 1, 'hi': 30}
        a, b = fit_all([fits, over])
        self.assertEqual(a['cap'], 10)
        self.assertTrue(all(len(it['i']) == 1 for it in a['items']))
        self.assertEqual(len(b['items']), b['cap'])
        self.assertTrue(any(len(it['i']) > 1 for it in b['items']))
        self.assertEqual(sum(len(it['i']) for it in b['items']), 30)

    def test_clusters_are_contiguous_runs(self):
        r, = fit_all([{'orders': [1] * 25 + [9] * 5, 'W': 300, 'mk': MK, 'gap': GAP, 'lo': 1, 'hi': 9}])
        for it in r['items']:
            self.assertEqual(it['i'], list(range(it['i'][0], it['i'][-1] + 1)))

    def test_the_crowded_part_is_what_gets_grouped(self):
        r, = fit_all([{'orders': [1, 2, 3] + [6] * 10 + [9, 10], 'W': 500, 'mk': MK, 'gap': GAP, 'lo': 1, 'hi': 10}])
        self.assertEqual(r['cap'], 12)
        grouped = [it['i'] for it in r['items'] if len(it['i']) > 1]
        self.assertTrue(grouped and all(set(g) <= set(range(3, 13)) for g in grouped), r['items'])  # only the events piled on one order
        self.assertEqual([it['i'] for it in r['items'][:3]], [[0], [1], [2]])
        self.assertEqual([it['i'] for it in r['items'][-2:]], [[13], [14]])

    def test_narrow_and_degenerate_widths(self):
        for W in (0, 1, MK - 1, MK, MK + GAP, 2 * MK + GAP - 1):
            r, = fit_all([{'orders': [1, 2, 3], 'W': W, 'mk': MK, 'gap': GAP, 'lo': 1, 'hi': 3}])
            self.assertGreaterEqual(r['cap'], 1)
            self.assertLessEqual(len(r['items']), r['cap'])
        r, = fit_all([{'orders': [4, 4, 4], 'W': 400, 'mk': MK, 'gap': GAP, 'lo': 4, 'hi': 4}])
        self.assertEqual([it['x'] for it in r['items']], [0, 40, 80])  # one order: markers start at the left and keep their spacing


def chromium():
    for name in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable', 'brave'):
        p = shutil.which(name)
        if p:
            return p
    return None


PROBE = r'''
<script>
setTimeout(() => {
  const out = {lanes: [], w: innerWidth}, $ = s => document.querySelector(s), qa = s => [...document.querySelectorAll(s)];
  for (const lane of qa('.lane')) {
    const track = lane.querySelector('.track').getBoundingClientRect();
    const vis = [...lane.querySelectorAll('.mk')].filter(b => !b.hidden).map(b => ({r: b.getBoundingClientRect(), tag: b.tagName, cl: b.classList.contains('cl'), n: +b.textContent || 1}));
    vis.sort((a, b) => a.r.left - b.r.left);
    const gaps = vis.slice(1).map((b, i) => b.r.left - vis[i].r.right);
    out.lanes.push({id: lane.dataset.id, cap: +lane.dataset.cap, items: vis.length, tags: [...new Set(vis.map(v => v.tag))], clusters: vis.filter(v => v.cl).length,
      events: vis.reduce((s, v) => s + v.n, 0), minW: Math.min(...vis.map(v => v.r.width)), minH: Math.min(...vis.map(v => v.r.height)),
      minGap: gaps.length ? Math.min(...gaps) : null, left: vis[0].r.left - track.left, right: track.right - vis[vis.length - 1].r.right, overflowX: document.documentElement.scrollWidth - innerWidth});
  }
  const mk = qa('.lane')[1].querySelector('.mk:not([hidden])');
  mk.focus(); mk.click();
  out.afterClick = {open: !$('#panel').hidden, on: !!$('.tp.on'), pressed: mk.getAttribute('aria-pressed'), focusInPanel: document.activeElement === $('#panel'), lane: qa('.lane.sel').length};
  document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  out.afterEscape = {focusOnMarker: document.activeElement === mk, tp: qa('.tp.on').length, sel: qa('.lane.sel').length, pressed: mk.getAttribute('aria-pressed')};
  const cl = $('.mk.cl');
  if (cl) {
    cl.focus(); cl.click();
    out.cluster = {hits: qa('.tp.on .ev li.hit').length, from: +cl.dataset.from, to: +cl.dataset.to, note: !$('.tp.on .cl-note').hidden, pressed: cl.getAttribute('aria-pressed')};
    document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    out.cluster.back = document.activeElement === cl;
  }
  const pre = document.createElement('pre'); pre.id = 'probe'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
}, 600);
</script>'''


@unittest.skipUnless(chromium(), 'needs a chromium, chrome or brave binary')
class Dom(unittest.TestCase):
    """The page in a real headless browser: computed marker sizes and gaps, clusters, and the panel's keyboard behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='sp-', dir='/tmp')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def probe(self, doc, width, height=900):
        html = page(doc).replace('</body>', PROBE + '</body>')
        f = os.path.join(self.tmp, 'p%d.html' % width)
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(html)
        prof = tempfile.mkdtemp(dir=self.tmp)
        p = subprocess.run([chromium(), '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--user-data-dir=' + prof, '--hide-scrollbars',
                            '--window-size=%d,%d' % (width, height), '--virtual-time-budget=4000', '--dump-dom', 'file://' + f],
                           capture_output=True, text=True, timeout=120, env={**os.environ, 'TMPDIR': '/tmp'})
        m = re.search(r'<pre id="probe">(.*?)</pre>', p.stdout, re.S)
        self.assertTrue(m, 'no probe output: ' + p.stderr[-400:])
        import html as h
        return json.loads(h.unescape(m.group(1)))

    def check(self, width):
        r = self.probe(busy_doc(), width)
        self.assertEqual(r['w'], width)
        for lane in r['lanes']:
            self.assertEqual(lane['tags'], ['BUTTON'], lane)
            self.assertGreaterEqual(lane['minW'], MK, lane)
            self.assertGreaterEqual(lane['minH'], MK, lane)
            if lane['minGap'] is not None:
                self.assertGreaterEqual(lane['minGap'], GAP, lane)
            self.assertLessEqual(lane['items'], lane['cap'], lane)
            self.assertGreaterEqual(lane['left'], -0.5, lane)
            self.assertGreaterEqual(lane['right'], -0.5, lane)
            self.assertEqual(lane['overflowX'], 0, lane)
        crowded = r['lanes'][-1]
        self.assertGreater(crowded['clusters'], 0, crowded)
        self.assertEqual(crowded['events'], 40)
        self.assertTrue(all(l['clusters'] == 0 for l in r['lanes'][:-1]), 'the sample lanes fit without clusters')
        return r

    def test_1440_sizes_gaps_clusters_and_keyboard(self):
        r = self.check(1440)
        self.assertEqual(r['afterClick'], {'open': True, 'on': True, 'pressed': 'true', 'focusInPanel': True, 'lane': 1})
        self.assertEqual(r['afterEscape'], {'focusOnMarker': True, 'tp': 0, 'sel': 0, 'pressed': 'false'})
        c = r['cluster']
        self.assertEqual(c['hits'], c['to'] - c['from'] + 1)
        self.assertTrue(c['note'] and c['back'])
        self.assertEqual(c['pressed'], 'true')

    def test_800_sizes_gaps_clusters_and_keyboard(self):
        r = self.check(800)
        self.assertEqual(r['afterClick']['pressed'], 'true')
        self.assertTrue(r['afterClick']['open'] and r['afterClick']['focusInPanel'])
        self.assertTrue(r['afterEscape']['focusOnMarker'])
        self.assertTrue(r['cluster']['back'])


SIZES = r"""
<script>
setTimeout(() => {
  const r = s => document.querySelector(s).getBoundingClientRect();
  const marks = [...document.querySelectorAll('.lane')].map(l => [...l.querySelectorAll('.mk')].filter(b => !b.hidden).map(b => b.getBoundingClientRect().bottom));
  const out = {lanes: marks.length, lastBottom: marks.length ? Math.max(...marks[marks.length - 1]) : null,
               header: document.querySelector('header.top') ? r('header.top').height : null, overflowX: document.documentElement.scrollWidth - innerWidth};
  const pre = document.createElement('pre'); pre.id = 'probe'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
}, 600);
</script>"""
LONG = 'a long reason that explains in some detail why this harness keeps no log the skill can read, ' * 3


def measure(tmp, html, width, height=900):
    """Open a page headless at width x height and return the SIZES probe."""
    f = os.path.join(tmp, 'm%d.html' % width)
    with open(f, 'w', encoding='utf-8') as fh:
        fh.write(html.replace('</body>', SIZES + '</body>'))
    prof = tempfile.mkdtemp(dir=tmp)
    p = subprocess.run([chromium(), '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', '--user-data-dir=' + prof, '--hide-scrollbars',
                        '--window-size=%d,%d' % (width, height), '--virtual-time-budget=4000', '--dump-dom', 'file://' + f],
                       capture_output=True, text=True, timeout=120, env={**os.environ, 'TMPDIR': '/tmp'})
    m = re.search(r'<pre id="probe">(.*?)</pre>', p.stdout, re.S)
    assert m, 'no probe output: ' + p.stderr[-400:]
    import html as h
    return json.loads(h.unescape(m.group(1)))


@unittest.skipUnless(chromium(), 'needs a chromium, chrome or brave binary')
class NoSessionLayout(unittest.TestCase):
    """The note on a page with no session must not cost the first screen anything."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='ns-', dir='/tmp')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def change(self, reason, width, lang='en'):
        d = json.load(open(CHANGE, encoding='utf-8'))
        d['lang'] = lang
        if reason is None:
            d.pop('transcript_unavailable', None)
        else:
            d['transcript_unavailable'] = reason
        return measure(self.tmp, page2.render(d, validated=False, session_checked=False), width)

    def test_session_page_with_the_note_keeps_every_lane_on_a_1440_x_900_screen(self):
        d = sample()
        self.assertTrue(d['transcript_unavailable'])
        r = measure(self.tmp, page_session.render(d, {}, session_checked=False), 1440)
        self.assertEqual(r['lanes'], len(d['themes']))
        self.assertLessEqual(r['lastBottom'], 900, r)
        checked = measure(self.tmp, page_session.render(d, {}, session_checked=True), 1440)
        self.assertLessEqual(r['lastBottom'], checked['lastBottom'] + 1, (r, checked))  # the note adds no height at all

    def test_a_200_character_reason_never_changes_the_change_page_header(self):
        for width in (1440, 800):
            base = self.change(None, width)['header']
            self.assertEqual(self.change('x' * 200, width)['header'], base, width)
            self.assertEqual(self.change(LONG[:200], width)['header'], base, width)
            self.assertEqual(self.change(LONG[:200], width, 'vi')['header'], self.change(None, width, 'vi')['header'], width)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sp-cli-')
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name
        shutil.copy(SAMPLE, os.path.join(self.dir, 'day.session.json'))
        shutil.copy(CHANGE, os.path.join(self.dir, 'password-autofill.v2.json'))

    def run_render(self, *args):
        return subprocess.run([sys.executable, RENDER, os.path.join(self.dir, 'day.session.json'), *args], capture_output=True, text=True)

    def test_renders_the_session_page_and_the_sibling_change_page(self):
        p = self.run_render('--no-validate', '--text')
        self.assertEqual(p.returncode, 0, p.stderr)
        out = os.path.join(self.dir, 'index.html')
        self.assertEqual(p.stdout.strip().splitlines()[-1], out)
        with open(out, encoding='utf-8') as fh:
            html = fh.read()
        href = re.search(r'class="btn" href="([^"]+)"', html).group(1)
        self.assertEqual(href, 'password-autofill.v2.html')
        sib = os.path.join(self.dir, href)  # a relative link that resolves next to the session page
        self.assertTrue(os.path.isfile(sib))
        with open(sib, encoding='utf-8') as fh:
            self.assertTrue(fh.read().startswith('<!doctype html>'))
        self.assertTrue(os.path.isfile(out + '.txt'))
        self.assertLess(os.path.getsize(out), page2.MAX_BYTES)

    def test_a_relative_out_dir_keeps_the_link_relative(self):
        sub = os.path.join(self.dir, 'site')
        os.mkdir(sub)
        p = self.run_render('--no-validate', '--out', os.path.join(sub, 'index.html'))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.isfile(os.path.join(sub, 'password-autofill.v2.html')))
        self.assertIn('href="password-autofill.v2.html"', open(os.path.join(sub, 'index.html'), encoding='utf-8').read())

    def test_an_invalid_doc_writes_nothing(self):
        path = os.path.join(self.dir, 'day.session.json')
        d = sample()
        d['themes'][0]['status'] = 'finished'
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(d, fh)
        p = self.run_render()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('themes[0].status', p.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'index.html')))
        p = self.run_render('--no-validate')
        self.assertEqual(p.returncode, 1)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'index.html')))

    def test_a_credential_in_the_doc_is_refused(self):
        path = os.path.join(self.dir, 'day.session.json')
        d = sample()
        d['themes'][0]['outcome'] = 'The password: Hunter2xyz9 was shared.'
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(d, fh)
        p = self.run_render()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertNotIn('Hunter2xyz9', p.stdout + p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'index.html')))

    def test_a_change_doc_that_cannot_be_rendered_stops_the_run(self):
        os.remove(os.path.join(self.dir, 'password-autofill.v2.json'))
        p = self.run_render('--no-validate')
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn('cannot render the change page of theme 4', p.stderr)
        self.assertNotIn('Traceback', p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'index.html')))

    def test_v1_and_v2_docs_still_render_as_before(self):
        v2 = subprocess.run([sys.executable, RENDER, os.path.join(self.dir, 'password-autofill.v2.json'), '--no-validate'], capture_output=True, text=True)
        self.assertEqual(v2.returncode, 0, v2.stderr)


if __name__ == '__main__':
    unittest.main()
