"""Render a validated explain.json into one self-contained HTML page."""
import datetime
import html
import json
import os
import re

from . import gitio, mm
from .i18n import STR
from .refs import Verifier

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'assets')
FILES_COLLAPSE_OVER = 12


def esc(s):
    return html.escape(str(s), quote=True)


def rich(s):
    """Escape, then turn `code` into <code>. Escaping first keeps markup in the text inert."""
    return re.sub(r'`([^`]+)`', r'<code>\1</code>', esc(s))


class Page:
    def __init__(self, doc, repo, with_mermaid=True):
        self.d, self.repo, self.with_mermaid = doc, repo, with_mermaid
        self.t = STR[doc.get('lang', 'vi')]
        rng = doc['range']
        base, head = gitio.resolve_rev(repo, rng['base']), gitio.resolve_rev(repo, rng['head'])
        self.files = gitio.changed_files(repo, base, head)
        self.ver = Verifier(repo, base, head, deleted=[f['path'] for f in self.files if f['status'] == 'D'])
        self.diagrams = 0

    # ---- evidence
    def cite(self, r):
        status, _ = self.ver.check(r)
        t = self.t
        side = r.get('side') or ('base' if r.get('file') in self.ver.deleted else 'head')
        badge = '<span class="badge %s">%s</span>' % ('ok' if status == 'verified' else 'warn', esc(t[status]))
        if side == 'base':
            badge += '<span class="badge old">%s</span>' % esc(t['old_version'])
        body = ('<pre><code>%s</code></pre>' % esc(r['snippet'])) if status == 'verified' else '<p class="note">%s</p>' % esc(t['inferred_note'])
        if status == 'inferred' and r.get('snippet'):
            body += '<pre><code>%s</code></pre>' % esc(r['snippet'])
        return '<details class="cite %s"><summary><code>%s:%s</code>%s</summary>%s</details>' % (
            status, esc(r['file']), esc(r['line']), badge, body)

    def cites(self, refs, label=True):
        if not refs:
            return ''
        return '<div class="cites" role="group" aria-label="%s">%s</div>' % (esc(self.t['cites_label']), ''.join(self.cite(r) for r in refs))

    # ---- diagrams
    def diagram(self, source):
        self.diagrams += 1
        t = self.t
        return ('<figure class="diagram"><div class="dtools" role="group" aria-label="%s">'
                '<button type="button" data-zoom="out" aria-label="%s">&minus;</button>'
                '<button type="button" data-zoom="reset">%s</button>'
                '<button type="button" data-zoom="in" aria-label="%s">+</button></div>'
                '<div class="dscroll" tabindex="0" role="img" aria-label="%s"><pre class="mermaid-src">%s</pre></div>'
                '<p class="dfail" hidden>%s</p>'
                '<details class="dsrc"><summary>%s</summary><pre><code>%s</code></pre></details></figure>') % (
            esc(t['diagram_label']), esc(t['zoom_out']), esc(t['zoom_reset']), esc(t['zoom_in']), esc(t['diagram_label']),
            esc(source), esc(t['diagram_failed']), esc(t['diagram_src']), esc(source))

    # ---- sections
    def head(self, key, conclusion, count=None):
        t = self.t
        return '<section id="%s"><h2>%s</h2><p class="lede">%s</p>' % (key, esc(t[key]), rich(conclusion))

    def s_why(self):
        w = self.d['why']
        return self.head('why', w['conclusion']) + '<ul class="plain">%s</ul>%s</section>' % (
            ''.join('<li>%s</li>' % rich(x) for x in w['lines']), self.cites(w.get('refs')))

    def file_rows(self, paths):
        by = {f['path']: f for f in self.files}
        rows = []
        for p in paths:
            f = by[p]
            st = f['status'] if f['status'] in 'AMDR' else 'M'
            counts = ('<span class="bin">%s</span>' % esc(self.t['binary'])) if f['binary'] else (
                '<span class="add">+%d</span><span class="del">&minus;%d</span>' % (f['add'], f['del']))
            old = ' <span class="from">%s <code>%s</code></span>' % (esc(self.t['renamed_from']), esc(f['old_path'])) if f['old_path'] else ''
            rows.append('<li><span class="st st-%s">%s</span><span class="path"><code>%s</code>%s</span><span class="num">%s</span></li>' % (
                st, esc(self.t['status_' + st]), esc(p), old, counts))
        ul = '<ul class="files">%s</ul>' % ''.join(rows)
        if len(paths) > FILES_COLLAPSE_OVER:
            return '<details class="filelist"><summary>%s</summary>%s</details>' % (esc(self.t['show_files'] % len(paths)), ul)
        return ul

    def s_changes(self):
        sec = self.d['changes']
        by = {f['path']: f for f in self.files}
        out = [self.head('changes', sec['conclusion'])]
        deep = {}
        for it in self.d['logic']['items']:
            if it.get('change'):
                deep.setdefault(it['change'], []).append(it)
        for c in sec['items']:
            add = sum(by[p]['add'] for p in c['files'])
            dele = sum(by[p]['del'] for p in c['files'])
            more = ''
            if deep.get(c.get('id')):
                more = '<p class="seealso">%s: %s</p>' % (esc(self.t['explained_in']), ' &middot; '.join(
                    '<a href="#logic-%s">%s</a>' % (esc(i['id']), rich(i['title'])) for i in deep[c['id']]))
            out.append('<article class="card" id="change-%s"><h3><span>%s</span><span class="num total"><span class="add">+%d</span><span class="del">&minus;%d</span></span></h3><p>%s</p>%s%s%s</article>' % (
                esc(c.get('id', '')), rich(c['title']), add, dele, rich(c['summary']), more, self.file_rows(c['files']), self.cites(c.get('refs'))))
        return ''.join(out) + '</section>'

    def s_flows(self):
        sec = self.d['flows']
        out = [self.head('flows', sec['conclusion'])]
        if not sec['items']:
            out.append('<p class="none">%s</p>' % rich(sec.get('none_reason', self.t['none'])))
        for f in sec['items']:
            actors = {a['id']: a.get('label') or a['id'] for a in f['actors']}
            steps = []
            for i, s in enumerate(f['steps'], 1):
                chg = '<span class="badge chg">%s</span>' % esc(self.t['changed_step']) if s.get('changed') else ''
                who = '<strong>%s</strong>' % esc(actors[s['from']]) if s['from'] == s['to'] else '<strong>%s</strong> &rarr; <strong>%s</strong>' % (
                    esc(actors[s['from']]), esc(actors[s['to']]))
                steps.append('<li class="%s"><p>%s: %s %s</p>%s</li>' % (
                    'changed' if s.get('changed') else '', who, rich(s['label']), chg, self.cites([s['ref']])))
            out.append('<article class="card"><h3><span>%s</span></h3><p>%s</p>%s<p class="legend">%s</p><h4>%s</h4><ol class="steps">%s</ol></article>' % (
                rich(f['title']), rich(f['summary']), self.diagram(mm.sequence(f)), esc(self.t['legend_changed']),
                esc(self.t['steps']), ''.join(steps)))
        return ''.join(out) + '</section>'

    def trace(self, tr):
        t = self.t
        org = tr['origin']
        kind = org['kind']
        if kind == 'illustrative':
            origin = '<p class="origin illus"><span class="badge warn">%s</span> %s</p>' % (esc(t['origin_illustrative']), esc(t['illustrative_note']))
        elif kind == 'run':
            origin = '<div class="origin"><p><span class="badge ok">%s</span></p><p>%s: <code>%s</code></p><pre><code>%s</code></pre></div>' % (
                esc(t['origin_run']), esc(t['command']), esc(org['command']), esc(org['output']))
        else:
            origin = '<div class="origin"><p><span class="badge ok">%s</span></p>%s</div>' % (esc(t['origin_' + kind]), self.cites([org['cite']]))
        inputs = ''.join('<li><code>%s</code> = <code>%s</code></li>' % (esc(i['name']), esc(i['value'])) for i in tr['input'])
        rows = ''.join('<li><div class="tx">%s</div><div class="val"><code>%s</code></div><div class="src">%s</div></li>' % (
            rich(s['text']), esc(s['value']), self.cites([s['ref']])) for s in tr['steps'])
        return ('%s<h4>%s</h4><ul class="inputs">%s</ul><ol class="trace">%s</ol>'
                '<p class="result"><strong>%s:</strong> %s</p>') % (origin, esc(t['input']), inputs, rows, esc(t['result']), rich(tr['result']))

    def s_logic(self):
        sec = self.d['logic']
        out = [self.head('logic', sec['conclusion'])]
        if not sec['items']:
            out.append('<p class="none">%s</p>' % rich(sec.get('none_reason', self.t['none'])))
        for it in sec['items']:
            if it['kind'] == 'flowchart':
                fl = it['flow']
                names = {n['id']: n['label'] for n in fl['nodes']}
                edges = ''.join('<li><p><strong>%s</strong> &rarr; <strong>%s</strong>%s</p>%s</li>' % (
                    esc(names[e['from']]), esc(names[e['to']]), (': ' + rich(e['label'])) if e.get('label') else '', self.cites([e['ref']]))
                    for e in fl['edges'])
                body = '%s<p class="legend">%s</p><h4>%s</h4><ul class="steps">%s</ul>' % (
                    self.diagram(mm.flowchart(fl)), esc(self.t['legend_flow']), esc(self.t['edges']), edges)
            else:
                body = self.trace(it['trace'])
            titles = {c.get('id'): c['title'] for c in self.d['changes']['items']}
            back = ('<p class="seealso">%s: <a href="#change-%s">%s</a></p>' % (esc(self.t['part_of']), esc(it['change']), rich(titles[it['change']]))) if it.get('change') else ''
            out.append('<article class="card" id="logic-%s"><h3><span><code>%s</code></span></h3><p class="where"><code>%s</code></p><p><strong>%s</strong></p><p>%s</p>%s%s%s</article>' % (
                esc(it['id']), esc(it['function']), esc(it['file']), rich(it['title']), rich(it['summary']), back, body, self.cites(it.get('refs'))))
        if sec.get('skipped'):
            out.append('<h3>%s</h3><ul class="plain">%s</ul>' % (esc(self.t['skipped']), ''.join(
                '<li><code>%s</code> <code>%s</code>: %s</li>' % (esc(s['file']), esc(s['function']), rich(s['reason'])) for s in sec['skipped'])))
        return ''.join(out) + '</section>'

    def s_risks(self):
        sec = self.d['risks']
        out = [self.head('risks', sec['conclusion'])]
        if not sec['items']:
            out.append('<p class="none">%s</p>' % rich(sec.get('none_reason', self.t['none'])))
        for r in sec['items']:
            out.append('<article class="card risk %s"><p><span class="badge %s">%s</span> %s</p>%s</article>' % (
                r['kind'], 'warn' if r['kind'] == 'break' else 'info', esc(self.t['risk_' + r['kind']]), rich(r['text']), self.cites(r.get('refs'))))
        return ''.join(out) + '</section>'

    def s_quiz(self):
        t = self.t
        out = ['<section id="quiz"><h2>%s</h2><p class="lede">%s</p>' % (esc(t['quiz']), esc(t['quiz_intro']))]
        for i, q in enumerate(self.d['quiz']['items'], 1):
            out.append('<article class="card quiz"><p class="qn">%s %d</p><h3><span>%s</span></h3><details class="answer"><summary>%s</summary><p>%s</p>%s</details></article>' % (
                esc(t['question']), i, rich(q['q']), esc(t['show_answer']), rich(q['a']), self.cites(q.get('refs'))))
        return ''.join(out) + '</section>'

    # ---- page
    def render(self):
        d, t = self.d, self.t
        totals_add = sum(f['add'] for f in self.files)
        totals_del = sum(f['del'] for f in self.files)
        body = [self.s_why(), self.s_changes(), self.s_flows(), self.s_logic(), self.s_risks(), self.s_quiz()]
        counts = {'why': None, 'changes': len(d['changes']['items']), 'flows': len(d['flows']['items']),
                  'logic': len(d['logic']['items']), 'risks': len(d['risks']['items']), 'quiz': len(d['quiz']['items'])}
        nav = ''.join('<li><a href="#%s">%s%s</a></li>' % (k, esc(t[k]), ('<span class="n">%d</span>' % c) if c is not None else '')
                      for k, c in counts.items())
        mermaid = ''
        if self.diagrams and self.with_mermaid:
            with open(os.path.join(ASSETS, 'mermaid.min.js'), encoding='utf-8') as fh:
                lib = fh.read()
            mermaid = '<script>%s</script>' % lib.replace('</script', '<\\/script')
        return TEMPLATE.format(
            lang=esc(d['lang']), title=esc(d['title'].replace('`', '')), h1=rich(d['title']), css=CSS, skip=esc(t['skip_nav']), nav_label=esc(t['sections']), nav=nav,
            label=esc(d['range']['label']), range_word=esc(t['range']), nfiles=len(self.files), files_word=esc(t['files']),
            add=totals_add, dele=totals_del, when=esc(datetime.datetime.now().strftime('%Y-%m-%d %H:%M')), rendered=esc(t['rendered']),
            body=''.join(body), mermaid=mermaid, js=JS.replace('__FAILED__', json.dumps(t['diagram_failed'])))


def render(doc, repo, with_mermaid=True):
    return Page(doc, repo, with_mermaid).render()


CSS = open(os.path.join(os.path.dirname(__file__), 'page.css'), encoding='utf-8').read()
JS = open(os.path.join(os.path.dirname(__file__), 'page.js'), encoding='utf-8').read()
TEMPLATE = open(os.path.join(os.path.dirname(__file__), 'page.html'), encoding='utf-8').read()
