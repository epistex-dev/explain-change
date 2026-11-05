"""Render an explain-flow/1 doc into the flow page: one self-contained HTML file (fonts inlined), no code, diff or file:line.

Layout A of the mockups: the question and summary, the counts, the numbered route, the system map (parts inside or outside the system, each carrying the numbers
of its steps), and one panel for the selected step. Every step's panel is in the HTML, so print and a browser without JS show the whole flow in order; flow.js
collapses the panel to one step. `sources`, `commit` (but for a short form in the footer) and `excerpt` never reach the page.
"""
import os
import re

from .i18n2 import STR2, count
from .page2 import UI, _read, esc, font_faces, ic, jdump
from .page_session import _sprite, txt
from .themes import THEME_KEY, THEMES, head_script, picker

END = 'end'
PROBLEMS = 'problems'
OUT_ICON, IN_ICON = 'globe', 'file-code'
IN_KINDS = ('service', 'data', 'ui', 'test')  # a decorative tint per part inside the system; the doc carries no kind


def _css():
    return font_faces() + '\n' + _read(os.path.join(UI, 'page2.css')) + '\n' + _read(os.path.join(UI, 'flow.css'))


def shape_problems(doc):
    """What the page cannot do without (used when validation is skipped); the validator is the real check."""
    errs = []

    def need(ok, path):
        if not ok:
            errs.append('%s: missing or wrong type' % path)
    need(doc.get('lang', 'vi') in ('vi', 'en'), 'lang')
    need(all(isinstance(doc.get(k), str) for k in ('title', 'question', 'summary')), 'title, question, summary')
    parts, steps = doc.get('parts'), doc.get('steps')
    need(isinstance(parts, list) and bool(parts) and all(isinstance(p, dict) and all(isinstance(p.get(k), str) for k in ('id', 'name', 'role')) and p.get('where') in ('inside', 'outside') for p in parts), 'parts')
    ids = {p['id'] for p in parts if isinstance(p, dict) and isinstance(p.get('id'), str)} if isinstance(parts, list) else set()
    need(isinstance(steps, list) and bool(steps) and all(
        isinstance(s, dict) and all(isinstance(s.get(k), str) for k in ('id', 'name', 'takes_in', 'gives_back')) and s.get('part') in ids
        and isinstance(s.get('branches', []), list) and all(isinstance(b, dict) and isinstance(b.get('when'), str) and isinstance(b.get('to'), str) for b in s.get('branches', []))
        and isinstance(s.get('errors', []), list) and all(isinstance(e, dict) and isinstance(e.get('name'), str) and isinstance(e.get('result'), str) for e in s.get('errors', []))
        for s in steps), 'steps')
    return errs


def render(doc, theme=THEMES[0], commit=None, commit_date=None):
    """The page for a flow doc. `theme`: the colour theme baked in as the default. `commit` (the full SHA) and `commit_date` feed the footer line;
    `commit` None leaves the line out."""
    if theme not in THEMES:
        raise ValueError('unknown theme %r; valid: %s' % (theme, ', '.join(THEMES)))
    return Builder(doc, theme, commit, commit_date).build()


class Builder:
    def __init__(self, doc, theme, commit, commit_date):
        self.doc, self.theme, self.commit, self.date = doc, theme, commit, commit_date
        self.t = STR2[doc.get('lang', 'vi')]
        self.parts = doc['parts']
        self.steps = doc['steps']
        self.num = {s['id']: i + 1 for i, s in enumerate(self.steps)}
        self.part = {p['id']: p for p in self.parts}
        self.kind = {}
        for p in self.parts:
            self.kind[p['id']] = 'external' if p['where'] == 'outside' else IN_KINDS[sum(1 for q in self.kind.values() if q != 'external') % len(IN_KINDS)]
        self.of_part = {}
        for i, s in enumerate(self.steps):
            self.of_part.setdefault(s['part'], []).append(i + 1)
        self.err_n = 0

    # ---- the facts, once each
    def targets(self, i):
        s = self.steps[i]
        if s.get('branches'):
            return [b['to'] for b in s['branches']]
        return [self.steps[i + 1]['id']] if i + 1 < len(self.steps) else [END]

    def edges(self):
        """[from, to, [step numbers], bad]: the hand-offs between parts, from the order of the steps and their branches; the ends are drawn as two terminals."""
        out = {}
        for i, s in enumerate(self.steps):
            for to in self.targets(i):
                if to in self.num:
                    dest, nums = self.steps[self.num[to] - 1]['part'], [i + 1, self.num[to]]
                    if dest == s['part']:
                        continue
                else:
                    dest, nums = to, [i + 1]
                e = out.setdefault((s['part'], dest), [s['part'], dest, [], to == PROBLEMS])
                e[2] += [n for n in nums if n not in e[2]]
        return list(out.values())

    def ends(self):
        used = {to for i in range(len(self.steps)) for to in self.targets(i)}
        return [k for k in (PROBLEMS, END) if k in used]

    # ---- parts
    def pills(self, p):
        nums = self.of_part.get(p['id'], [])
        if not nums:
            return ''
        t = self.t
        btn = ''.join('<button type="button" data-step="%d" aria-label="%s">%d</button>' % (n, esc(t['fl_step_aria'] % (n, plain_name(self.steps[n - 1]))), n) for n in nums)
        return '<div class="f-pills" role="group" aria-label="%s">%s</div>' % (esc(t['fl_steps_in'] % plain_name(p)), btn)

    def node(self, p, i):
        k = self.kind[p['id']]
        out = p['where'] == 'outside'
        return ('<div class="node f-node k-%s%s" data-mod="%s"%s style="--i:%d"><h3>%s%s</h3><p class="n-sum">%s</p>%s</div>' % (
            k, ' out' if out else '', esc(p['id']), ' data-has' if p['id'] in self.of_part else '', i, ic(OUT_ICON if out else IN_ICON), txt(p['name']), txt(p['role']), self.pills(p)))

    def zone(self, label, icon, parts, cls, start):
        if not parts:
            return ''
        nodes = ''.join(self.node(p, start + j) for j, p in enumerate(parts))
        body = '<div class="a-sys">%s</div>' % nodes if cls == 'sys' else nodes
        return '<section class="zone %s" aria-label="%s"><p class="zone-label">%s%s</p>%s</section>' % (cls, esc(label), ic(icon), esc(label), body)

    def stage(self):
        t = self.t
        inside = [p for p in self.parts if p['where'] == 'inside']
        outside = [p for p in self.parts if p['where'] == 'outside']
        half = (len(outside) + 1) // 2
        left, right = outside[:half], outside[half:]
        zones = [(left, 'ext'), (inside, 'sys'), (right, 'ext')]
        zones = [(ps, c) for ps, c in zones if ps]
        cols = ' '.join('minmax(0,%s)' % ('2fr' if c == 'sys' else '.8fr') for _, c in zones)
        html, n = '', 0
        for ps, c in zones:
            html += self.zone(t['zone_system'] if c == 'sys' else t['zone_out'], IN_ICON if c == 'sys' else OUT_ICON, ps, c, n)
            n += len(ps)
        ends = self.ends()
        terms = ''.join('<span class="f-term %s" data-mod="%s">%s%s</span>' % (
            'bad' if k == PROBLEMS else 'ok', k, ic('triangle-alert' if k == PROBLEMS else 'circle-check'), esc(t['fl_problems'] if k == PROBLEMS else t['fl_ok'])) for k in ends)
        svg = ('<svg class="a-edges" id="edges" aria-hidden="true"><defs>'
               '<marker id="fl-ah" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto"><path d="M1 1.5 9 5 1 8.5z"/></marker>'
               '<marker id="fl-ahb" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto"><path d="M1 1.5 9 5 1 8.5z"/></marker>'
               '</defs></svg>')
        return '<div class="a-stage" id="stage" style="--cols:%s">%s%s%s</div>' % (cols, html, ('<div class="a-ends">%s</div>' % terms) if terms else '', svg)

    def legend(self):
        t = self.t
        items = [('<span class="sw"></span>', t['fl_lg_sel']), ('<span class="sw un"></span>', t['fl_lg_other']), ('<span class="sw ex"></span>', t['zone_out']),
                 ('<span class="ln"></span>', t['fl_lg_pass'])]
        if PROBLEMS in self.ends():
            items.append(('<span class="ln bad"></span>', t['fl_problems']))
        return '<ul class="a-legend">%s</ul>' % ''.join('<li>%s%s</li>' % (a, esc(b)) for a, b in items)

    # ---- route and counts
    def route(self):
        t = self.t
        lis = ''.join('<li><button type="button" data-step="%d"%s><span class="f-num">%d</span>%s</button></li>' % (
            i + 1, ' aria-current="step"' if i == 0 else '', i + 1, txt(s['name'])) for i, s in enumerate(self.steps))
        return '<nav aria-label="%s"><ol class="a-route">%s</ol></nav>' % (esc(t['fl_route_label']), lis)

    def stats(self):
        t, d = self.t, self.doc
        n_err = sum(len(s.get('errors', [])) for s in self.steps)
        n_br = sum(1 for s in self.steps if s.get('branches'))
        items = [('', 'fl_steps', len(self.steps)), ('', 'fl_branches_n', n_br), ('bad', 'fl_errors_n', n_err), ('', 'fl_parts', len(self.parts))]
        lis = ''.join('<li%s>%s</li>' % (' class="%s"' % c if c else '', esc(count(t, k, n)).replace(str(n), '<b>%d</b>' % n, 1)) for c, k, n in items)
        return '<ul class="f-stats" aria-label="%s">%s</ul>' % (esc(t['fl_counts']), lis)

    def summary(self):
        s = plain_text(self.doc['summary'])
        m = re.search(r'(?<=[.!?])\s+', s)
        head, rest = (s[:m.start()], s[m.end():]) if m else (s, '')
        return '<p class="f-sum"><b>%s</b>%s</p>' % (esc(head), (' ' + esc(rest)) if rest else '')

    # ---- the panel: one article per step
    def link(self, to):
        t = self.t
        if to in self.num:
            n = self.num[to]
            return ('<a href="#step-%d" data-step="%d">%s</a>' % (n, n, esc(t['fl_step_n'] % n))), 'arrow-right', ''
        return None, 'triangle-alert' if to == PROBLEMS else 'circle-check', 'bad' if to == PROBLEMS else 'ok'

    def go(self, to):
        t = self.t
        a, icon, cls = self.link(to)
        text = (esc(t['fl_go_step']).replace('%s', a)) if a else esc(t['fl_go_problems'] if to == PROBLEMS else t['fl_go_end'])
        return icon, cls, text

    def branches(self, i):
        t, s = self.t, self.steps[i]
        rows = ''
        if s.get('branches'):
            for b in s['branches']:
                icon, cls, go = self.go(b['to'])
                rows += '<li>%s<span><b>%s</b>, %s.</span></li>' % (ic('branch' if icon == 'arrow-right' else icon, cls), txt(b['when']), go)
            head = t['fl_branch_h']
        else:
            to = self.targets(i)[0]
            a, icon, cls = self.link(to)
            word = esc(t['fl_then_step']).replace('%s', a) if a else esc(t['fl_then_end'])
            rows = '<li>%s<span>%s.</span></li>' % (ic(icon, cls), word)
            head = t['fl_next']
        return '<p class="sec">%s</p><ul class="f-br">%s</ul>' % (esc(head), rows)

    def errors(self, s):
        t = self.t
        if not s.get('errors'):
            return '<p class="sec">%s</p><p class="f-none">%s</p>' % (esc(t['fl_wrong']), esc(t['fl_no_err']))
        cards = ''
        for e in s['errors']:
            self.err_n += 1
            cards += '<div class="f-err"><h3 class="f-eh"><span class="f-code">E%d</span>%s</h3><p>%s</p></div>' % (self.err_n, txt(e['name']), txt(e['result']))
        return '<p class="sec">%s</p><div class="list">%s</div>' % (esc(t['fl_wrong']), cards)

    def article(self, i):
        t, s = self.t, self.steps[i]
        p = self.part[s['part']]
        chip = '<span class="f-mod k-%s">%s%s</span>' % (self.kind[p['id']], ic(OUT_ICON if p['where'] == 'outside' else IN_ICON), txt(p['name']))
        return ('<article id="step-%d" aria-labelledby="st-%d"><p class="f-kick">%s</p><h2 id="st-%d">%s</h2>%s'
                '<div class="f-in"><div class="f-twin"><div><span class="f-lbl">%s</span><p class="f-txt">%s</p></div><div><span class="f-lbl">%s</span><p class="f-txt">%s</p></div></div></div>'
                '%s%s</article>') % (i + 1, i + 1, esc(t['fl_step_of'] % (i + 1, len(self.steps))), i + 1, txt(s['name']), chip,
                                     esc(t['fl_takes']), txt(s['takes_in']), esc(t['fl_gives']), txt(s['gives_back']), self.branches(i), self.errors(s))

    def panel(self):
        t = self.t
        arrows = ('<div><button class="iconbtn" id="prev" type="button" aria-label="%s">%s</button>'
                  '<button class="iconbtn" id="next" type="button" aria-label="%s">%s</button></div>') % (
            esc(t['fl_prev']), ic('arrow-right', 'flip'), esc(t['fl_next_btn']), ic('arrow-right'))
        return ('<aside class="a-panel" aria-label="%s"><div class="a-ph"><strong id="pcount" aria-live="polite">%s</strong>%s</div><div class="a-pb">%s</div></aside>' % (
            esc(t['fl_panel']), esc(t['fl_step_of'] % (1, len(self.steps))), arrows, ''.join(self.article(i) for i in range(len(self.steps)))))

    def footer(self):
        t = self.t
        if not self.commit:
            return ''
        sha = self.commit[:7]
        return '<footer class="f-foot">%s</footer>' % esc(t['fl_foot'] % (sha, self.date) if self.date else t['fl_foot_nd'] % sha)

    def build(self):
        t, d = self.t, self.doc
        mods = [self.steps[i]['part'] for i in range(len(self.steps))]
        data = {'mod': mods, 'edges': self.edges(), 'key': THEME_KEY, 't': {'of': t['fl_step_of']}}
        panel = self.panel()  # before the map: it numbers the error exits
        main = ('<main class="a-grid" id="main"><div class="a-main"><p class="f-q"><b>%s</b>%s</p>%s%s'
                '<h2 class="f-h2">%s</h2>%s<h2 class="f-h2" id="map-h">%s</h2><p class="f-hint">%s</p>%s%s</div>%s</main>') % (
            esc(t['fl_asked']), txt(d['question']), self.summary(), self.stats(), esc(t['fl_route_h']), self.route(), esc(t['fl_map_h']), esc(t['fl_map_hint']),
            self.stage(), self.legend(), panel)
        return '''<!doctype html>
<html lang="%(lang)s" data-theme="%(theme)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title>
%(head_js)s
<style>
%(css)s
</style>
</head>
<body>
%(sprite)s
<a class="skip" href="#map-h">%(skip)s</a>
<header class="top"><div class="brand">%(i_map)s</div><div class="title"><h1>%(title)s</h1><p>%(kind)s</p></div>%(picker)s</header>
%(main)s
%(footer)s
<script type="application/json" id="data">%(data)s</script>
<script>
%(js)s
</script>
</body>
</html>
''' % {'lang': t['html_lang'], 'theme': self.theme, 'title': txt(d['title']), 'head_js': head_script(), 'css': _css(), 'sprite': _sprite(), 'skip': esc(t['fl_skip']),
       'i_map': ic('map'), 'kind': esc(t['fl_kind']), 'picker': picker(t, self.theme), 'main': main, 'footer': self.footer(), 'data': jdump(data), 'js': _read(os.path.join(UI, 'flow.js'))}


def plain_text(s):
    from .page_session import plain
    return plain(s)


def plain_name(obj):
    return plain_text(obj['name'])
