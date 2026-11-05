"""Render an explain-session/1 doc into the swimlane page: one self-contained HTML file (fonts inlined), no code, diff or file:line.

Tier 0 is a strip: the summary with one status segment per theme, what needs the reader, what the agent decided, what left the working copy.
Tier 1 is the journey: one lane per theme, events in (order, list position) order, a side panel with the selected theme's journey.
Tier 2 is a link from a theme's panel to the sibling change page. Sources, commands and quotes never reach the page; every doc string is escaped.
"""
import os
import re

from . import outward
from .i18n2 import STR2, count
from .page2 import UI, _read, esc, font_faces, ic, jdump
from .transcript import redact

KINDS = ('asked', 'decided', 'redirected', 'blocked', 'done', 'outward', 'in_progress')
KIND_ICON = {'asked': 'message', 'decided': 'sparkles', 'redirected': 'redirect', 'blocked': 'ban', 'done': 'circle-check', 'outward': 'upload', 'in_progress': 'circle-dashed'}
STATUSES = ('done', 'done_by_user', 'done_needs_you', 'in_progress', 'not_done')
STATUS_ICON = {'done': 'circle-check', 'done_by_user': 'user', 'done_needs_you': 'triangle-alert', 'in_progress': 'circle-dashed', 'not_done': 'circle-x'}
OUT_ICON = {'repo_created': 'plus', 'push': 'upload', 'force_push': 'triangle-alert', 'history_rewrite': 'history', 'delete': 'trash', 'deploy': 'globe',
            'pr': 'branch', 'message': 'message', 'other': 'circle-help'}


FILE_LINE = re.compile(r'(?<=[\w)\]])(\.[A-Za-z][A-Za-z0-9]{0,5}):\d+(?::\d+)?(?![\w:/])')


def plain(s):
    """A doc string as page text: a credential that got past validation (--no-validate) is hidden, backticks (code marks) and the line number of a
    file:line are dropped: the page shows no code and no file:line."""
    s = redact(str(s if s is not None else ''))
    s = s.replace('`', '')
    return FILE_LINE.sub(r'\1', s)


def txt(s):
    return esc(plain(s))


def _css():
    base = _read(os.path.join(UI, 'page2.css'))
    base = base[:base.index('/* header (floorplan')]  # tokens, reset and helpers only; the v2 layout stays out of this page
    return font_faces() + '\n' + base + '\n' + _read(os.path.join(UI, 'session.css'))


def _sprite():
    s = _read(os.path.join(UI, 'icons.svg'))
    extra = _read(os.path.join(UI, 'session-icons.svg'))
    return s[:s.rindex('</svg>')] + extra + '</svg>'


def shape_problems(doc):
    """What the page cannot do without (used when validation is skipped); the validator is the real check."""
    errs = []

    def need(ok, path):
        if not ok:
            errs.append('%s: missing or wrong type' % path)
    need(doc.get('lang') in ('vi', 'en'), 'lang')
    need(isinstance(doc.get('title'), str) and isinstance(doc.get('summary'), str), 'title, summary')
    th = doc.get('themes')
    need(isinstance(th, list) and bool(th) and all(isinstance(t, dict) and isinstance(t.get('title'), str) and t.get('status') in STATUSES
                                                    and isinstance(t.get('outcome'), str) and isinstance(t.get('events'), list)
                                                    and all(isinstance(e, dict) and e.get('kind') in KINDS and isinstance(e.get('text'), str) for e in t['events'])
                                                    for t in th), 'themes')
    ids = {t.get('id') for t in th} if isinstance(th, list) else set()
    for key in ('needs_you', 'decided'):
        v = doc.get(key, [])
        need(isinstance(v, list) and all(isinstance(x, dict) and isinstance(x.get('text'), str) and x.get('theme') in ids for x in v), key)
    need(all(isinstance(x, dict) and x.get('kind') in outward.KINDS and isinstance(x.get('count'), int) and isinstance(x.get('themes'), list)
             for x in doc.get('outward', [])) if isinstance(doc.get('outward', []), list) else False, 'outward')
    return errs


def change_page_name(change_doc):
    """The file name of the sibling page for a theme's change_doc ("a/b.v2.json" -> "a__b.v2.html"): it sits next to the session page."""
    return change_doc.replace('\\', '/').strip('/').replace('/', '__').rsplit('.json', 1)[0] + '.html'


def render(doc, links=None):
    """The page for a session doc. `links`: {theme index (0-based): relative href of its change page}."""
    return Builder(doc, links or {}).build()


class Builder:
    def __init__(self, doc, links):
        self.doc = doc
        self.t = STR2[doc['lang']]
        self.links = links
        self.themes = doc['themes']
        self.n_of = {t.get('id'): i + 1 for i, t in enumerate(self.themes)}

    # ---- small parts
    def chip_theme(self, tid):
        n = self.n_of[tid]
        title = self.themes[n - 1]['title']
        return '<a class="tchip" href="#theme-%d" data-theme="%d"><span class="num-badge">%d</span><span class="t">%s</span></a>' % (n, n, n, txt(title))

    def status_chip(self, st):
        return '<span class="chip s-%s">%s%s</span>' % (st, ic(STATUS_ICON[st]), esc(self.t['ses_st_' + st]))

    def head(self, icon, name, concl, hid, aside=''):
        return ('<div class="sec-head"><span class="sec-ico">%s</span><span class="sec-name">%s</span><h2 id="%s">%s</h2>%s</div>'
                % (ic(icon), esc(name), hid, esc(concl), ('<div class="aside">%s</div>' % esc(aside)) if aside else ''))

    # ---- tier 0
    def summary(self):
        t = self.t
        segs, counts = [], {}
        for i, th in enumerate(self.themes):
            st = th['status']
            counts[st] = counts.get(st, 0) + 1
            segs.append('<li><a class="st-%s" href="#theme-%d" data-theme="%d"><i></i><span class="tl"><span class="num-badge">%d</span><span class="nm">%s'
                        '<span class="sr"> (%s)</span></span></span></a></li>' % (st, i + 1, i + 1, i + 1, txt(th['title']), esc(t['ses_st_' + st])))
        key = ''.join('<li class="st-%s"><i></i>%s %d</li>' % (st, esc(t['ses_st_' + st]), counts[st]) for st in STATUSES if st in counts)
        return ('<section class="card o1" aria-labelledby="sum"><p class="slogan">%s</p><h1 class="sum" id="sum">%s</h1>'
                '<ul class="tally" aria-label="%s">%s</ul><ul class="skey" aria-label="%s">%s</ul></section>'
                % (esc(t['ses_slogan']), txt(self.doc['summary']), esc(t['ses_status_label']), ''.join(segs), esc(t['ses_status_legend']), key))

    def needs(self):
        t, items = self.t, self.doc.get('needs_you', [])
        concl = count(t, 'ses_needs_h', len(items)) if items else t['ses_needs_none']
        body = ''.join('<article class="need" id="need-%d"><span class="n">%s%s</span><p>%s</p><div>%s</div></article>' % (
            i + 1, ic('triangle-alert'), esc(t['ses_need_n'] % (i + 1)), txt(x['text']), self.chip_theme(x['theme'])) for i, x in enumerate(items))
        return ('<section class="card o2" aria-labelledby="h-needs">%s%s</section>'
                % (self.head('triangle-alert', t['ses_sec_needs'], concl, 'h-needs'), ('<div class="stack">%s</div>' % body) if body else ''))

    def decided(self):
        t, items = self.t, self.doc.get('decided', [])
        irrev = sum(1 for x in items if x.get('reversible') is False)
        concl = t['ses_dec_none'] if not items else count(t, 'ses_dec_h', len(items)) + (t['ses_dec_irrev'] % irrev if irrev else t['ses_dec_allrev'])
        rows = []
        for i, x in enumerate(items):
            chip = ('<span class="chip irrev">%s%s</span>' % (ic('triangle-alert'), esc(t['ses_irrev']))) if x.get('reversible') is False \
                else '<span class="chip rev">%s%s</span>' % (ic('undo'), esc(t['ses_rev']))
            rows.append('<div class="dec" id="dec-%d"><p>%s</p>%s<div class="sub">%s</div></div>' % (i + 1, txt(x['text']), chip, self.chip_theme(x['theme'])))
        return ('<section class="card o3" aria-labelledby="h-dec">%s%s</section>' % (self.head('sparkles', t['ses_sec_decided'], concl, 'h-dec'), ''.join(rows)))

    def outward(self):
        t = self.t
        cards, scratch = [], 0
        by_kind = {o['kind']: o for o in self.doc.get('outward', [])}
        for k in outward.KINDS:
            o = by_kind.get(k)
            if not o:
                continue
            n, sc = o['count'], o.get('scratch') if isinstance(o.get('scratch'), int) and not isinstance(o.get('scratch'), bool) else 0
            scratch += sc
            real = n - sc if k == 'delete' else n
            if real < 1:
                continue
            chips = ''.join(self.chip_theme(x) for x in o['themes'] if x in self.n_of)
            cards.append('<div class="out"><span class="oi">%s</span><div><div class="big">%s</div><div class="chips">%s</div></div></div>'
                         % (ic(OUT_ICON[k]), esc(count(t, 'ses_o_' + k, real)), chips))
        concl = count(t, 'ses_out_h', len(cards)) if cards else t['ses_out_none']
        line = ('<p class="scratch">%s</p>' % esc(count(t, 'ses_scratch', scratch))) if scratch else ''
        body = ('<div class="outs">%s</div>' % ''.join(cards)) if cards else ''
        return ('<section class="card o4" aria-labelledby="h-out">%s%s%s</section>'
                % (self.head('upload', t['ses_sec_out'], concl, 'h-out', t['ses_out_hint'] if cards else ''), body, line))

    # ---- tier 1
    def resolved(self):
        """[[(kind, text, order)]] per theme: events keep their list order; one without an order takes the one before it (the first takes 1)."""
        out = []
        for th in self.themes:
            prev, evs = None, []
            for e in th['events']:
                o = e.get('order') if isinstance(e.get('order'), int) and not isinstance(e.get('order'), bool) else prev
                prev = o if o is not None else prev
                evs.append((e['kind'], e['text'], o))
            first = next((o for _, _, o in evs if o is not None), 1)
            out.append([(k, x, o if o is not None else first) for k, x, o in evs])
        return out

    def stable_order(self, evs):
        """Events in (order, list position) order; the validator keeps `order` from going down, so this only guards a doc that was not validated."""
        return [e for _, e in sorted(enumerate(evs), key=lambda p: (p[1][2], p[0]))]

    def journey(self):
        t = self.t
        res = [self.stable_order(e) for e in self.resolved()]
        n_ev = sum(len(e) for e in res)
        blocked = sum(1 for e in res if any(k == 'blocked' for k, _, _ in e))
        redirected = sum(1 for e in res if any(k == 'redirected' for k, _, _ in e))
        concl = count(t, 'ses_jr_h', len(res)) + ', ' + count(t, 'ses_jr_events', n_ev)
        tail = ([t['ses_jr_blocked'] % blocked] if blocked else []) + ([count(t, 'ses_jr_redirected', redirected)] if redirected else [])
        concl += ('; ' + ', '.join(tail)) if tail else ''
        legend = ''.join('<li class="k-%s"><span class="kdot">%s</span>%s</li>' % (k, ic(KIND_ICON[k]), esc(t['ses_k_' + k])) for k in KINDS)
        lanes, panels, data = [], [], []
        for i, (th, evs) in enumerate(zip(self.themes, res)):
            n = i + 1
            marks = ''.join('<button class="mk k-%s" type="button" data-i="%d" aria-pressed="false" aria-controls="panel" aria-label="%s" title="%s">%s</button>' % (
                k, j, esc('%s: %s' % (t['ses_k_' + k], plain(x))), esc('%s: %s' % (t['ses_k_' + k], plain(x))), ic(KIND_ICON[k]))
                for j, (k, x, _) in enumerate(evs))
            lanes.append('<div class="lane" id="theme-%d" data-id="%d"><button class="lh" type="button" aria-controls="panel"><span class="num-badge">%d</span>'
                         '<span class="nm">%s</span>%s</button><div class="track"><span class="ln"></span>%s</div></div>'
                         % (n, n, n, txt(th['title']), self.status_chip(th['status']), marks))
            panels.append(self.theme_panel(n, th, evs))
            data.append({'id': str(n), 'ev': [{'k': k, 'o': o} for k, _, o in evs]})
        orders = [o for e in res for _, _, o in e]
        self.data = {'themes': data, 'lo': min(orders) if orders else 1, 'hi': max(orders) if orders else 1,
                     't': {'cl': t['ses_cl'], 'cl_note': t['ses_cl_note']}}
        main = ('<div class="main"><section class="card" id="journey" aria-labelledby="h-jr">%s<ul class="keyline" aria-label="%s">%s</ul>'
                '<div class="axis" aria-hidden="true"><span class="ah"></span><div class="ar"><span>%s</span><span>%s</span></div></div>'
                '<div class="lanes" aria-label="%s">%s</div></section>'
                '<aside class="card panel" id="panel" tabindex="-1" aria-label="%s"><div class="empty-panel"><p class="empty">%s</p></div>%s</aside></div>' % (
                    self.head('list', t['ses_sec_journey'], concl, 'h-jr', t['ses_jr_hint']), esc(t['ses_legend_label']), legend, esc(t['ses_axis_from']), esc(t['ses_axis_to']),
                    esc(t['ses_lanes_label']), ''.join(lanes), esc(t['ses_panel']), esc(t['ses_empty']), ''.join(panels)))
        return main

    def theme_panel(self, n, th, evs):
        t = self.t
        items = ''.join('<li data-i="%d" class="k-%s"><span class="kdot">%s</span><div><span class="kind">%s</span><div class="t">%s</div></div></li>' % (
            j, k, ic(KIND_ICON[k]), esc(t['ses_k_' + k]), txt(x)) for j, (k, x, _) in enumerate(evs))
        links = []
        for i, x in enumerate(self.doc.get('needs_you', [])):
            if x['theme'] == th.get('id'):
                links.append('<a class="tchip" href="#need-%d" data-goto="need-%d"><span class="t">%s</span></a>' % (i + 1, i + 1, esc(t['ses_need_n'] % (i + 1))))
        for i, x in enumerate(self.doc.get('decided', [])):
            if x['theme'] == th.get('id'):
                links.append('<a class="tchip" href="#dec-%d" data-goto="dec-%d"><span class="t">%s</span></a>' % (i + 1, i + 1, esc(t['ses_dec_n'] % (i + 1))))
        href = self.links.get(n - 1)
        t2 = ('<div class="t2"><p>%s</p><a class="btn" href="%s">%s%s</a></div>' % (esc(t['ses_t2_text']), esc(href), ic('map'), esc(t['ses_t2_btn']))) if href else ''
        return ('<section class="tp" data-id="%d" aria-labelledby="pt-%d"><div class="p-top"><span class="num-badge">%d</span>%s'
                '<button class="close" type="button" data-close aria-label="%s">%s</button></div><h3 id="pt-%d">%s</h3><p>%s</p>'
                '<div><h4>%s</h4><p class="cl-note" hidden></p><ol class="ev">%s</ol></div>%s%s</section>' % (
                    n, n, n, self.status_chip(th['status']), esc(t['ses_close']), ic('x'), n, txt(th['title']), txt(th['outcome']), esc(t['ses_journey_h']), items,
                    ('<div class="links">%s</div>' % ''.join(links)) if links else '', t2))

    def build(self):
        t = self.t
        top = '<div class="top3"><div class="left">%s%s</div>%s%s</div>' % (self.summary(), self.outward(), self.needs(), self.decided())
        journey = self.journey()
        return '''<!doctype html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title>
<script>document.documentElement.classList.add('js')</script>
<style>
%(css)s
</style>
</head>
<body>
%(sprite)s
<a class="skip" href="#journey">%(skip)s</a>
<div class="page">
<div class="bar"><span class="logo">%(i_spark)s</span><span class="brand-name">explain-change</span><span class="ptitle">%(title)s</span><span class="chip tag">%(i_layout)s%(page)s</span></div>
<main class="page-main" style="display:grid;gap:var(--s4)">
%(top)s
%(journey)s
</main>
</div>
<script type="application/json" id="data">%(data)s</script>
<script>
%(fit)s
%(js)s
</script>
</body>
</html>
''' % {'lang': t['html_lang'], 'title': txt(self.doc['title']), 'css': _css(), 'sprite': _sprite(), 'skip': esc(t['ses_skip']), 'i_spark': ic('sparkles'),
       'i_layout': ic('layout'), 'page': esc(t['ses_page']), 'top': top, 'journey': journey, 'data': jdump(self.data), 'fit': _read(os.path.join(UI, 'fit.js')), 'js': _read(os.path.join(UI, 'session.js'))}
