"""Render a v2 explain.json into the layout-2 page: one self-contained HTML file, no Mermaid, fonts inlined.

The map is laid out from the doc's modules and edges plus the architecture groups (zones = top-level architecture
nodes, columns = flow order). Refs, commands and excerpts never reach the page; every doc string is escaped.
"""
import base64
import html
import json
import os
import re
from html.parser import HTMLParser

from . import arch as archmod
from .ground import MAX_REASON
from .i18n2 import STR2, count
from .themes import THEMES, head_script, picker
from .transcript import redact

UI = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'assets', 'ui')
MAX_COLS = 3
MAX_FILE_ROWS = 4  # file rows a map node lists; the rest is one "+N file" line
MAX_BYTES = 512 * 1024  # html_preview / html_render limit
FONTS = (
    ('Inter', 'inter-latin', 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD'),
    ('Inter', 'inter-vietnamese', 'U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,U+1EA0-1EF9,U+20AB'),
    ('JetBrains Mono', 'jetbrains-mono-latin', 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD'),
)
ICON_OF_KIND = {'ui': 'monitor', 'service': 'server', 'data': 'database', 'test': 'flask-conical', 'external': 'globe'}
RESULT_CHIP = {'passed': ('ok', 'circle-check', 'r_passed'), 'failed': ('bad', 'circle-x', 'r_failed'), 'mixed': ('warn', 'triangle-alert', 'r_mixed')}


def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)


def txt(s):
    """Escaped plain text: backticks only marked identifiers in the doc, the page shows no code."""
    return esc(redact(str(s if s is not None else '')).replace('`', ''))  # redact: a credential that got past validation (--no-validate) still stays off the page


def soft(s):
    """txt() with a line-break chance after `=`, `-`, `_`, `.` or `/` inside a long word (an identifier, a path, `a=b`): prose breaks at spaces,
    a code-like word only at its separators, never in the middle of a name."""
    return re.sub(r'(?<=[-=_./])(?=[^-=_./\s])', '<wbr>', txt(s))


def ic(name, cls=''):
    return '<svg class="ic%s" aria-hidden="true"><use href="#i-%s"/></svg>' % (' ' + cls if cls else '', name)


def jdump(o):
    """JSON safe inside a <script> element."""
    return json.dumps(o, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026') \
        .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def _read(path):
    with open(path, encoding='utf-8') as fh:
        return fh.read()


def _read_bytes(path):
    with open(path, 'rb') as fh:
        return fh.read()


def font_faces():
    faces = []
    for fam, f, rng in FONTS:
        b = base64.b64encode(_read_bytes(os.path.join(UI, 'fonts', f + '.woff2'))).decode('ascii')
        faces.append('@font-face{font-family:"%s";font-style:normal;font-weight:100 900;font-display:swap;'
                     'src:url(data:font/woff2;base64,%s) format("woff2-variations");unicode-range:%s}' % (fam, b, rng))
    return '\n'.join(faces)


def css():
    return font_faces() + '\n' + _read(os.path.join(UI, 'page2.css'))


# ---------------------------------------------------------------- modules and layout
def top_kind(arch, mid):
    seen = {mid}
    while True:
        p = arch.parent(mid)
        if p is None or p in seen:
            return arch.nodes[mid].get('kind')
        seen.add(p)
        mid = p


def describe(doc, arch, t):
    """One dict per listed module with everything the page shows about it."""
    out = []
    for i, m in enumerate(doc['map']['modules']):
        mid = m['id']
        node = arch.nodes.get(mid) if arch else None
        outside = m.get('outside') is True
        kind = m.get('kind') or (node or {}).get('kind')
        kind = kind if isinstance(kind, str) else None
        tkind = top_kind(arch, mid) if node else None
        ik = kind if kind in ICON_OF_KIND else (tkind if tkind in ICON_OF_KIND else None)
        if outside:
            ik = 'external'
        if outside:
            zone, zlabel = '__out', t['zone_out']
        elif node:
            zlabel = arch.top_label(mid)
            zone = zlabel
        elif mid == archmod.OTHER:
            zone, zlabel = '__other', t['zone_other']
        else:
            zone, zlabel = '__sys', t['zone_system']
        out.append({
            'i': i, 'id': mid, 'tok': 'n%d' % i, 'name': m.get('name') or (node or {}).get('label') or mid,
            'summary': m.get('summary') or (node or {}).get('summary') or '', 'what': m.get('what_changed') or '',
            'changed': m.get('changed') is True, 'outside': outside, 'files': m.get('files') or [], 'icon': ICON_OF_KIND.get(ik or '', 'file-code'),
            'k': ik, 'zone': zone, 'zlabel': zlabel, 'is_test': ik == 'test' and not outside,
            'state': 'out' if outside else 'changed' if m.get('changed') is True else 'same'})
    return out


def norm(text):
    return ' '.join(str(text).casefold().split())


def layout(mods, edges):
    """Zones -> columns. Returns [[zone, ...], ...] (columns left to right); a zone is
    {key, label, icon, ext, mods}. Flow order decides the column; tests sit under the outside actors."""
    zones, order = {}, []
    for m in mods:
        z = zones.get(m['zone'])
        if z is None:
            z = zones[m['zone']] = {'key': m['zone'], 'label': m['zlabel'], 'mods': [], 'ext': m['zone'] == '__out', 'first': m['i']}
            order.append(m['zone'])
        z['mods'].append(m)
    for z in zones.values():
        z['mods'].sort(key=lambda m: not m['changed'])  # changed first, stable
        z['test'] = all(m['is_test'] for m in z['mods'])
        z['icon'] = 'globe' if z['ext'] else z['mods'][0]['icon']
    zone_of = {m['id']: m['zone'] for m in mods}
    flow, tests = {}, []
    for e in edges:
        a, b = zone_of.get(e.get('from')), zone_of.get(e.get('to'))
        if a is None or b is None or a == b:
            continue
        if e.get('kind') == 'tests':
            tests.append((a, b))
        else:
            flow.setdefault(a, [])
            if b not in flow[a]:
                flow[a].append(b)
    plain = [k for k in order if not zones[k]['test']]
    # drop back edges (DFS from the outside actors, then in order) so layering ends
    state, kept = {}, {k: [] for k in plain}
    def dfs(u):
        state[u] = 1
        for v in flow.get(u, []):
            if v not in kept or v == '__out':
                continue
            if state.get(v) == 1:
                continue
            kept[u].append(v)
            if v not in state:
                dfs(v)
        state[u] = 2
    for k in (['__out'] if '__out' in kept else []) + plain:
        if k not in state:
            dfs(k)
    layer = {}
    def depth(k, seen=()):
        if k in layer:
            return layer[k]
        preds = [u for u in kept if k in kept[u] and u not in seen]
        layer[k] = 0 if k == '__out' or not preds else 1 + max(depth(u, seen + (k,)) for u in preds)
        return layer[k]
    for k in plain:
        depth(k)
    linked = {k for k in plain if kept[k] or any(k in v for v in kept.values())}
    n_layers = max([layer[k] for k in linked] + [0]) + 1 if linked else 1
    want = min(MAX_COLS, max(n_layers, len(plain)))
    count = {i: 0 for i in range(want)}
    for k in plain:
        if k in linked:
            layer[k] = min(layer[k], MAX_COLS - 1)
            count[layer[k]] = count.get(layer[k], 0) + len(zones[k]['mods'])
    for k in plain:
        if k not in linked:  # isolated zone: the emptiest column, new columns up to the cap
            layer[k] = min(count, key=lambda c: (count[c], c))
            count[layer[k]] += len(zones[k]['mods'])
    for k in order:
        if zones[k]['test']:
            tgt = next((b for a, b in tests if a == k and b in layer), None)
            layer[k] = 0 if '__out' in zones else (layer[tgt] if tgt is not None else min(count, key=lambda c: (count[c], c)))
    cols = {}
    for k in sorted(order, key=lambda k: (layer[k], k != '__out', not zones[k]['test'], zones[k]['first'])):
        cols.setdefault(layer[k], []).append(zones[k])
    return [cols[c] for c in sorted(cols)]


# ---------------------------------------------------------------- builder
class Builder:
    def __init__(self, doc, arch, validated, session_checked=None, theme=THEMES[0]):
        if theme not in THEMES:
            raise ValueError('unknown theme %r; valid: %s' % (theme, ', '.join(THEMES)))
        self.d, self.arch, self.validated, self.theme = doc, arch, validated, theme
        if session_checked is None:  # the caller did not say: a doc that declares no session was not checked against one
            session_checked = not (isinstance(doc.get('transcript_unavailable'), str) and doc['transcript_unavailable'].strip()) or bool(doc.get('transcript'))
        self.session_checked = session_checked
        self.t = STR2[doc.get('lang') if doc.get('lang') in STR2 else 'vi']
        self.mods = describe(doc, arch, self.t)
        self.tok = {m['id']: m['tok'] for m in self.mods}
        self.byid = {m['id']: m for m in self.mods}
        self.ev_tok = {}
        for i, r in enumerate(doc.get('evidence', {}).get('ran', [])):
            if r.get('id'):
                self.ev_tok[r['id']] = 'ev%d' % i

    # -- helpers
    def nodes_attr(self, obj):
        return ' data-nodes="%s"' % esc(' '.join(self.tok[x] for x in (obj.get('modules') or []) if x in self.tok))

    @staticmethod
    def is_inferred(obj):
        src = obj.get('source')
        if obj.get('inferred') is True:
            return True
        return isinstance(src, dict) and src.get('inferred') is True and 'kind' not in src

    def chip(self, cls, icon, text):
        return '<span class="chip %s">%s%s</span>' % (cls, ic(icon), esc(text))

    def inferred_chip(self, obj):
        return self.chip('warn', 'circle-help', self.t['inferred']) if self.is_inferred(obj) else ''

    @staticmethod
    def sources(obj):
        s = obj.get('source')
        return [x for x in (s if isinstance(s, list) else [s]) if isinstance(x, dict)]

    def own_account(self, obj):
        """On a page not checked against a session, a run or a user's word that would need the session to be proven rests on the agent's say-so."""
        s = self.sources(obj)
        return not self.session_checked and bool(s) and any(x.get('kind') in ('tool_call', 'user_reported') for x in s) and not self.reported_only(obj)

    def reason(self):
        """The doc's reason for having no transcript, as one short line of text (the validator already holds it to this; an unvalidated doc is cut here)."""
        r = self.d.get('transcript_unavailable')
        r = redact(' '.join(r.split())) if isinstance(r, str) else ''
        return r[:MAX_REASON - 1] + '…' if len(r) > MAX_REASON else r

    def reported_only(self, obj):
        s = self.sources(obj)
        return bool(s) and all(x.get('kind') == 'report' for x in s)

    # -- verdict
    def verdict(self):
        from . import check2
        v = check2.derive_verdict(self.d)
        t = self.t
        done, total = v['requests']['done'], v['requests']['total']
        ran = [r.get('result') for r in self.d.get('evidence', {}).get('ran', [])]
        full = done == total
        seg1 = '<button class="vseg" type="button" data-goto="req">%s<span class="num"><span class="%s">%d/%d</span> %s</span></button>' % (
            ic('circle-check' if full else 'circle-dashed'), 'g' if full else 'w', done, total, esc(t['req_n_1'] if total == 1 and 'req_n_1' in t else t['req_n']))
        if v['tests_passed']:
            label, cls, icon = t['tests_ok'], 'g', 'circle-check'
        elif 'failed' in ran:
            label, cls, icon = t['tests_bad'], 'b', 'circle-x'
        else:
            label, cls, icon = t['tests_none'], 'w', 'triangle-alert'
        extra = ' <span class="w num">&middot; %s</span>' % esc(count(t, 'caveats', v['caveats'])) if v['caveats'] else ''
        seg2 = '<button class="vseg" type="button" data-goto="evidence">%s<span><span class="%s">%s</span>%s</span></button>' % (ic(icon), cls, esc(label), extra)
        return '<div class="verdict" role="group" aria-label="%s">%s%s</div>' % (esc(t['verdict_label']), seg1, seg2)

    # -- map
    def file_li(self, f, dup):
        p = str(f.get('path', ''))
        parts = p.split('/')
        name = '/'.join(parts[-2:]) if dup.get(parts[-1], 0) > 1 and len(parts) > 1 else parts[-1]
        pieces = re.split(r'(?<=[-_./])(?=[^-_./])', name)  # a line may break after a separator, never inside a word
        fn = '<wbr>'.join(esc(x) for x in pieces)
        add, dele = f.get('add') or 0, f.get('del') or 0
        counts = []
        if add:
            counts.append('<span class="add d">+%d</span>' % add)
        if dele:
            counts.append('<span class="del d">&minus;%d</span>' % dele)
        return '<li><span class="fn">%s</span><span class="d">%s</span></li>' % (fn, ' '.join(counts))

    def node(self, m, n):
        t = self.t
        files = m['files']
        out = m['outside']
        cls = 'node%s%s%s' % (' out' if out else '', ' lit' if m['changed'] else '', ' k-' + m['k'] if m['k'] else '')
        body = ''
        if m['changed'] and m['what']:
            body += '<p class="n-what">%s</p>' % soft(m['what'])
        elif m['summary']:
            body += '<p class="n-sum">%s</p>' % soft(m['summary'])
        if out:
            body += '<span class="badge out">%s</span>' % esc(t['badge_out'])
        elif m['changed']:
            body += '<span class="badge ch">%s%s</span>' % (ic('file-code'), esc('%s · %s' % (t['badge_changed'], count(t, 'files_n', len(files)))) if files else esc(t['badge_changed']))
        else:
            body += '<span class="badge un">%s</span>' % esc(t['badge_same'])
        if files:
            # the biggest changes first, at most MAX_FILE_ROWS rows, then one "+N file" line; the badge above keeps the full count
            shown = sorted(files, key=lambda f: (-((f.get('add') or 0) + (f.get('del') or 0)), str(f.get('path', ''))))[:MAX_FILE_ROWS]
            dup = {}
            for f in shown:
                b = str(f.get('path', '')).split('/')[-1]
                dup[b] = dup.get(b, 0) + 1
            rows = ''.join(self.file_li(f, dup) for f in shown)
            if len(files) > len(shown):
                rows += '<li class="more"><span class="fn">%s</span></li>' % esc(count(t, 'files_more', len(files) - len(shown)))
            body += '<ul class="files">%s</ul>' % rows
        return ('<article class="%s" data-id="%s" data-real="%s" data-state="%s" data-sum="%s" style="--i:%d">'
                '<h3><button class="hit" type="button" aria-pressed="false">%s<span class="n-name">%s</span></button></h3>%s</article>') % (
            cls, m['tok'], esc(m['id']), m['state'], txt(m['summary']), n, ic(m['icon']), txt(m['name']), body)

    def stage(self):
        cols = layout(self.mods, self.d['map'].get('edges') or [])
        single = len(cols) == 1
        n = 0
        col_html, widths = [], []
        for col in cols:
            zs, w = [], 1.3
            for z in col:
                k = len(z['mods'])
                zc = min(3, k) if single else (2 if k >= 3 else 1)
                if zc > 1:
                    w = 2.4
                nodes = []
                for m in z['mods']:
                    nodes.append(self.node(m, n))
                    n += 1
                if k == 1 and not z['ext'] and norm(z['mods'][0]['name']) == norm(z['label']):  # a frame never repeats the title of its only card: draw the card bare
                    zs.append('<section class="zone solo"><div class="zone-grid" style="--zc:1">%s</div></section>' % ''.join(nodes))
                    continue
                zs.append('<section class="zone%s%s" aria-label="%s"><p class="zone-label">%s%s</p><div class="zone-grid" style="--zc:%d">%s</div></section>' % (
                    ' ext' if z['ext'] else '', ' wz' if zc > 1 else '', txt(z['label']), ic(z['icon']), txt(z['label']), zc, ''.join(nodes)))
            col_html.append('<div class="col">%s</div>' % ''.join(zs))
            widths.append(w)
        colw = ' '.join('minmax(%s,%gfr)' % ('0' if single else '200px', w) for w in widths)
        return ('<div class="stage" id="stage" style="--colw:%s"><svg class="edges" id="edges" aria-hidden="true"><defs>'
                '<marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                '<path d="M1 1.5 8.5 5 1 8.5z" fill="context-stroke"/></marker></defs></svg><svg class="edges lbls" id="elabels" aria-hidden="true"></svg>%s</div>') % (colw, ''.join(col_html))

    def edge_data(self):
        edges, listed = [], []
        arch_lbl = {}
        for e in (self.arch.edges if self.arch else []):
            arch_lbl[(e.get('from'), e.get('to'))] = e.get('label')
        for e in self.d['map'].get('edges') or []:
            a, b = self.byid.get(e.get('from')), self.byid.get(e.get('to'))
            if not a or not b:
                continue
            kind = e.get('kind')
            lit = kind == 'flow' and (a['changed'] or b['changed']) and all(x['changed'] or x['outside'] for x in (a, b))
            label = e.get('label') or (arch_lbl.get((a['id'], b['id'])) if kind == 'arch' else None)
            edges.append({'a': a['tok'], 'b': b['tok'], 'k': 'test' if kind == 'tests' else 'lit' if lit else '', 'label': label or '', 'mono': kind == 'arch'})
            listed.append('<li>%s &rarr; %s%s</li>' % (txt(a['name']), txt(b['name']), (': ' + txt(label)) if label else ''))
        return edges, '<ul class="sr edges-list" aria-label="%s">%s</ul>' % (esc(self.t['edges_label']), ''.join(listed)) if listed else ''

    def hidden_count(self):
        if not self.arch:
            return 0
        ids = [m['id'] for m in self.mods if m['id'] in self.arch.nodes]
        return len(self.arch.nodes) - len(set(ids) | self.arch.holders(ids))  # a group that holds a drawn module is its frame, not an unrelated part

    # -- tabs
    def concl(self, key):
        return '<p class="concl">%s</p>' % txt(self.d['conclusions'][key])

    def empty(self, key):
        return '<div class="empty" data-empty><p>%s</p><p data-hint></p><button class="golink" type="button" data-clear>%s</button></div>' % (
            esc(self.t['empty_' + key]), esc(self.t['nc_clear']))

    def tab_req(self):
        t, out = self.t, []
        for i, r in enumerate(self.d['requests']):
            st = r.get('status')
            chips, cls = '', ''
            if st == 'done':
                chips = self.chip('ok', 'circle-check', t['st_done'])
            elif st == 'done_after_fix':
                chips, cls = self.chip('ok', 'circle-check', t['st_done']) + self.chip('warn', 'triangle-alert', t['st_fix']), ' hl'
            elif st == 'not_done':
                chips, cls = self.chip('bad', 'circle-x', t['st_not']), ' dash'
            else:
                chips = self.chip('mut', 'arrow-right', t['st_changed'])
            note = ''
            if r.get('note') and st in ('done_after_fix', 'changed'):
                note = '<span class="lbl gap">%s</span><p>%s</p>' % (esc(t['note_fix'] if st == 'done_after_fix' else t['note_changed']), txt(r['note']))
            rep = '<p class="src">%s</p>' % esc(t['reported_note']) if self.reported_only(r) else ''
            see = r.get('see') if r.get('see') in ('logic', 'evidence') else None
            more = ('<p class="more"><button class="golink" type="button" data-goto="%s">%s</button></p>' % (see, esc(t['see_' + see]))) if see else ''
            out.append('<li class="card%s"%s id="rq%d"><div class="row">%s</div><span class="lbl">%s</span><p class="ask">&ldquo;%s&rdquo;</p>'
                       '<span class="lbl gap">%s</span><p>%s</p>%s%s%s</li>' % (cls, self.nodes_attr(r), i, chips, esc(t['ask']), txt(r.get('quote')),
                                                                               esc(t['result']), txt(r.get('result')), note, more, rep))
        return '%s<ol class="list">%s</ol>%s' % (self.concl('requests'), ''.join(out), self.empty('req'))

    def visual(self, v):
        if not isinstance(v, dict):
            return ''
        if v.get('kind') == 'form':
            rows = [r for r in (v.get('rows') if isinstance(v.get('rows'), list) else []) if isinstance(r, dict)]
            label = '; '.join('%s: %s' % (r.get('label', ''), r.get('value', '')) for r in rows)
            cells = ''.join('<div class="mf-row%s"><span>%s</span><i>%s</i></div>' % (
                {'none': ' none', 'bad': ' none', 'user': ' user', 'good': ' user', 'new': ' user'}.get(r.get('state'), ''), txt(r.get('label')), txt(r.get('value'))) for r in rows)
            return '<div class="mf" role="img" aria-label="%s">%s</div>' % (txt(label), cells)
        if v.get('kind') == 'dialog':
            tone = 'good' if v.get('tone') == 'good' else 'bad'
            sub = '<span>%s</span>' % txt(v['subtitle']) if v.get('subtitle') else ''
            return '<div class="dlg %s">%s<div><b>%s</b>%s</div></div>' % (tone, ic('shield-check' if tone == 'good' else 'triangle-alert'), txt(v.get('title')), sub)
        return ''

    def step(self, s):
        return '<div class="step stp"%s>%s<p class="s-label">%s</p><p>%s</p>%s</div>' % (
            self.nodes_attr(s), self.visual(s.get('visual')), txt(s.get('label')), txt(s.get('text')),
            ('<p class="src">%s</p>' % self.inferred_chip(s)) if self.is_inferred(s) else '')

    def tab_logic(self):
        t, lg = self.t, self.d['logic']
        parts = [self.concl('logic'), '<div class="list">']
        for side, icon, chip_cls in (('before', 'circle-x', 'bad'), ('after', 'circle-check', 'ok')):
            steps = lg.get(side) or []
            title = lg.get(side + '_title') or ''
            body = ''.join(self.step(s) for s in steps) if steps else '<p class="empty-ba">%s</p>' % txt(lg.get('before_none_reason') or t['before_none'])
            # the empty "before" has no node tags: it stays visible only in the unfiltered view
            attrs = '' if steps else ' data-nodes=""'
            parts.append('<div class="ba %s grp"%s><p class="ba-h">%s%s</p>%s</div>' % (side, attrs, self.chip(chip_cls, icon, t[side]), txt(title), body))
        parts.append('</div>')
        cases = lg.get('cases') or []
        if cases:
            lis = ''.join('<li%s><h4>%s%s</h4><p>%s</p></li>' % (self.nodes_attr(c), txt(c.get('title')), (' ' + self.inferred_chip(c)) if self.is_inferred(c) else '', txt(c.get('text'))) for c in cases)
            parts.append('<div class="grp"><h3 class="sec">%s<span>%s</span></h3><ul class="forms">%s</ul></div>' % (ic('key-round'), esc(t['cases_h']), lis))
        ex = lg.get('examples') or []
        if ex:
            lis = []
            for e in ex:
                go = ''
                target = self.ev_tok.get(e.get('evidence_id'))
                if target:
                    go = '<p class="src">%s <button class="golink" type="button" data-goto="evidence" data-target="%s">%s</button></p>' % (esc(t['example_go']), target, esc(t['tab_evidence']))
                lis.append('<li%s><p>%s %s</p>%s</li>' % (self.nodes_attr(e), txt(e.get('text')), self.inferred_chip(e), go))
            parts.append('<div class="grp"><h3 class="sec">%s<span>%s</span></h3><ul class="forms">%s</ul></div>' % (ic('flask-conical'), esc(t['examples_h']), ''.join(lis)))
        parts.append(self.empty('logic'))
        return ''.join(parts)

    def tab_why(self):
        t, ra = self.t, self.d['rationale']
        ch = ra['chosen']
        head = '<h4>%s</h4>' % txt(ch['option']) if ch.get('option') else ''
        out = ['%s<div class="list">' % self.concl('rationale'),
               '<div class="card hl"%s><div class="row">%s%s</div>%s<p>%s</p>%s</div>' % (
                   self.nodes_attr(ch), self.chip('acc', 'circle-check', t['chosen']), self.inferred_chip(ch), head, txt(ch.get('text')),
                   ('<p class="src">%s</p>' % esc(t['inferred_note'])) if self.is_inferred(ch) else '')]
        rej = ra.get('rejected') or []
        if rej:
            out.append('<h3 class="sec" data-g="rej">%s<span>%s &middot; <span class="cnt">%d</span> %s</span></h3>' % (ic('ban'), esc(t['rejected_h']), len(rej), esc(t['rejected_unit'])))
            for r in rej:
                out.append('<div class="g-rej card"%s><h4>%s</h4><p>%s</p>%s</div>' % (
                    self.nodes_attr(r), txt(r.get('option')), txt(r.get('why_not')), ('<p class="row">%s</p>' % self.inferred_chip(r)) if self.is_inferred(r) else ''))
        for key, label, icon, cls in [('tradeoff', t['tradeoff'], 'triangle-alert', 'warn')] + [('notes', t['note'], 'circle-help', 'mut')]:
            items = [ra[key]] if key == 'tradeoff' and ra.get(key) else (ra.get(key) or [] if key == 'notes' else [])
            for it in items:
                inf = self.is_inferred(it)
                out.append('<div class="card dash"%s><div class="row">%s%s</div><p>%s</p></div>' % (
                    self.nodes_attr(it), self.chip(cls, icon, label), self.inferred_chip(it) if inf else '', txt(it.get('text'))))
        out.append('</div>' + self.empty('why'))
        return ''.join(out)

    def tab_evidence(self):
        t, ev = self.t, self.d['evidence']
        cited = {e.get('evidence_id') for e in self.d['logic'].get('examples') or [] if e.get('evidence_id')}
        ran = ev.get('ran') or []
        nrep = sum(1 for r in ran if self.reported_only(r))
        nown = sum(1 for r in ran if self.own_account(r))
        out = [self.concl('evidence')]
        if not self.session_checked and self.reason():  # the full reason lives here, so a long one never changes the header
            out.append('<p class="hint nt-why">%s</p>' % esc(t['unchecked_why'] + self.reason()))
        if nrep:
            out.append('<p class="hint">%s</p>' % esc(count(t, 'reported_summary', nrep)))
        if nown:
            out.append('<p class="hint">%s</p>' % esc(count(t, 'own_summary', nown)))
        out.append('<div class="grp"><h3 class="sec" data-g="ran">%s<span>%s &middot; <span class="cnt">%d</span> %s</span></h3><ul class="list">' % (
            ic('circle-check'), esc(t['ran_h']), len(ran), esc(t['ran_unit'])))
        for i, r in enumerate(ran):
            cls, icon, key = RESULT_CHIP.get(r.get('result'), RESULT_CHIP['mixed'])
            rep = self.chip('mut', 'circle-help', t['reported']) if self.reported_only(r) else self.chip('mut', 'circle-help', t['own']) if self.own_account(r) else ''
            note = '<p class="src">%s</p>' % esc(t['reported_note'] if self.reported_only(r) else t['own_note']) if rep else ''
            out.append('<li class="g-ran card ev %s%s"%s id="ev%d">%s<div><div class="row">%s%s</div><h4>%s</h4><p class="num">%s</p>%s</div></li>' % (
                {'ok': 'ok', 'bad': 'bad', 'warn': 'warn'}[cls], ' hl' if r.get('id') in cited else '', self.nodes_attr(r), i, ic(icon),
                self.chip(cls, icon, t[key]), rep, txt(r.get('what')), txt(r.get('detail')), note))
        out.append('</ul></div>')
        nc = ev.get('not_checked') or []
        if nc:
            out.append('<div class="grp"><h3 class="sec" data-g="no">%s<span>%s &middot; <span class="cnt">%d</span> %s</span></h3><ul class="list">' % (
                ic('circle-dashed'), esc(t['nc_h']), len(nc), esc(t['nc_unit'])))
            for r in nc:
                why = '<p class="src">%s: %s</p>' % (esc(t['why_not']), txt(r['why'])) if r.get('why') else ''
                out.append('<li class="g-no card dash ev no"%s>%s<div><p>%s</p>%s</div></li>' % (self.nodes_attr(r), ic('circle-dashed'), txt(r.get('what')), why))
            out.append('</ul></div>')
        out.append(self.empty('evidence'))
        return ''.join(out)

    # -- page
    def build(self):
        d, t = self.d, self.t
        edges, edge_list = self.edge_data()
        hidden = self.hidden_count()
        js_t = {'hide': t['hide'], 'show': t['show'], 'has': t['js_has'],
                'state': {'changed': t['js_state_changed'], 'same': t['js_state_same'], 'out': t['js_state_out']},
                'note': {'changed': t['js_note_changed'], 'same': t['js_note_same'], 'out': t['js_note_out']},
                'tabs': {k: t['tab_' + k] for k in ('req', 'logic', 'why', 'evidence')}}
        sprite = _read(os.path.join(UI, 'icons.svg'))
        title = d.get('title') or t['untitled']
        sub = '<p>%s</p>' % txt(d['subtitle']) if d.get('subtitle') else ''
        legend = ''.join('<li><span class="sw%s"></span>%s</li>' % (c, esc(t[k])) for c, k in (('', 'lg_changed'), (' un', 'lg_same'), (' ex', 'lg_out')))
        tabs = ''.join('<button class="tab" role="tab" id="t-%s" aria-controls="p-%s" aria-selected="%s" %sdata-tab="%s">%s</button>' % (
            k, k, 'true' if k == 'req' else 'false', '' if k == 'req' else 'tabindex="-1" ', k, esc(t['tab_' + k])) for k in ('req', 'logic', 'why', 'evidence'))
        panels = ''.join('<section class="tp" id="p-%s" role="tabpanel" aria-labelledby="t-%s"%s>%s</section>' % (
            k, k, '' if k == 'req' else ' hidden', getattr(self, 'tab_' + k)()) for k in ('req', 'logic', 'why', 'evidence'))
        notice = ('<!-- Fonts: Inter (SIL OFL 1.1, Copyright 2016 The Inter Project Authors), JetBrains Mono (SIL OFL 1.1, Copyright 2020 The JetBrains Mono Project Authors). '
                  'Icons: Lucide (ISC). Full notices: explain-change/assets/ui/LICENSES.txt -->')
        return '''<!doctype html>
<html lang="%(lang)s" data-panel="open" data-theme="%(theme)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="generator" content="explain-change v2; validated=%(validated)s">
<title>%(title)s &middot; %(page)s</title>
%(notice)s
%(head_js)s
<style>
%(css)s
</style>
</head>
<body>
%(sprite)s
<a class="skip" href="#map">%(skip)s</a>
<header class="top">
  <span class="brand" aria-hidden="true">%(i_map)s</span>
  <div class="title"><h1>%(title)s</h1>%(sub)s</div>
  %(unchecked)s
  %(verdict)s
  %(picker)s
  <button class="pillbtn toggle" id="toggle" type="button" aria-expanded="true" aria-controls="panel">%(i_close)s<span>%(hide)s</span></button>
</header>
<main class="map" id="map">
  <section class="intro" aria-labelledby="map-h">
    <h2 id="map-h">%(map_concl)s</h2>
    <p>%(map_hint)s</p>
    <ul class="legend" aria-label="%(legend_label)s">%(legend)s</ul>
  </section>
  %(stage)s
  %(edge_list)s
  %(hidden)s
</main>
<aside class="panel" id="panel" aria-label="%(panel_label)s">
  <div class="p-head">
    <button class="grab" id="grab" type="button" aria-expanded="true" aria-controls="p-body" aria-label="%(toggle_label)s"><span></span></button>
    <div class="p-title"><strong>%(i_sparkles)s%(page)s</strong><button class="iconbtn" id="hide" type="button" aria-label="%(hide)s">%(i_x)s</button></div>
    <div class="tabs" role="tablist" aria-label="%(tabs_label)s">%(tabs)s</div>
    <div class="filterbar" id="filterbar" hidden><span class="fb-text">%(filter_label)s <b id="fb-name"></b></span><button class="fb-clear" id="fb-clear" type="button">%(i_x)s%(nc_clear)s</button></div>
  </div>
  <div class="p-body" id="p-body">
    <div class="nodecard" id="nodecard" aria-live="polite">
      <div class="nc-top"><h3 id="nc-name"></h3><span class="chip" id="nc-chip"></span></div>
      <p class="nc-sum" id="nc-sum"></p>
      <ul class="nc-edges" id="nc-edges" hidden></ul>
      <p class="nc-note" id="nc-note"></p>
    </div>
    %(panels)s
  </div>
</aside>
<script type="application/json" id="data">%(data)s</script>
<script>
%(router)s
%(js)s
</script>
</body>
</html>
''' % {
            'lang': t['html_lang'], 'validated': 'yes' if self.validated else 'no', 'title': txt(title), 'page': esc(t['page_name']), 'notice': notice,
            'theme': self.theme, 'head_js': head_script(), 'picker': picker(t, self.theme), 'css': css(), 'sprite': sprite, 'skip': esc(t['skip']), 'i_map': ic('map'), 'sub': sub, 'verdict': self.verdict(), 'i_close': ic('panel-right-close'),
            'hide': esc(t['hide']), 'map_concl': txt(d['conclusions']['map']), 'map_hint': esc(t['map_hint']), 'legend_label': esc(t['legend_label']),
            'legend': legend, 'stage': self.stage(), 'edge_list': edge_list,
            'hidden': ('<p class="hidden-note">%s</p>' % esc(count(t, 'hidden_note', hidden))) if hidden else '',
            'panel_label': esc(t['panel_label']), 'toggle_label': esc(t['toggle_label']), 'i_sparkles': ic('sparkles'), 'i_x': ic('x'),
            'tabs_label': esc(t['tabs_label']), 'tabs': tabs, 'nc_clear': esc(t['nc_clear']), 'filter_label': esc(t['filter_label']), 'panels': panels,
            'unchecked': ('<span class="chip warn unchecked">%s%s</span>' % (ic('triangle-alert'), esc(t['unchecked']))) if not self.session_checked else '',
            'data': jdump({'edges': edges, 't': js_t}), 'router': _read(os.path.join(UI, 'route.js')), 'js': _read(os.path.join(UI, 'page2.js'))}


def shape_problems(doc):
    """What the page cannot do without (used when validation is skipped); the validator is the real check."""
    errs = []
    def need(ok, path):
        if not ok:
            errs.append('%s: missing or wrong type' % path)
    c = doc.get('conclusions')
    need(isinstance(c, dict) and all(isinstance(c.get(k), str) for k in ('requests', 'map', 'logic', 'rationale', 'evidence')), 'conclusions')
    need(isinstance(doc.get('requests'), list) and all(isinstance(r, dict) for r in doc['requests']), 'requests')
    m = doc.get('map')
    need(isinstance(m, dict) and isinstance(m.get('modules'), list) and all(isinstance(x, dict) and isinstance(x.get('id'), str) for x in m['modules']), 'map.modules')
    need(isinstance(doc.get('logic'), dict), 'logic')
    r = doc.get('rationale')
    need(isinstance(r, dict) and isinstance(r.get('chosen'), dict), 'rationale.chosen')
    e = doc.get('evidence')
    need(isinstance(e, dict) and isinstance(e.get('ran'), list) and isinstance(e.get('not_checked', []), list), 'evidence')
    return errs


def render(doc, repo=None, arch=None, validated=True, session_checked=None, theme=THEMES[0]):
    """The page for a v2 doc. `arch`: an Architecture, or None to look for floorplan/architecture.json from `repo`.
    `session_checked`: False shows the "not checked against the session" badge; None reads it from the doc.
    `theme`: the colour theme baked in as the default; the reader's stored pick wins."""
    if arch is None and repo:
        from . import collect2
        arch = collect2.load_arch(repo)
    return Builder(doc, arch, validated, session_checked, theme).build()


class _Text(HTMLParser):
    SKIP = {'style', 'script', 'svg', 'head'}
    BLOCK = {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'div', 'section', 'article', 'header', 'main', 'aside', 'button', 'ul', 'ol', 'span'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK - {'span'}:
            self.out.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK - {'span'}:
            self.out.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def page_text(page):
    """The words of the page, for the cold-read gate: no markup, no scripts, no styles; hidden tabs included."""
    p = _Text()
    p.feed(page)
    lines = [re.sub(r'[ \t]+', ' ', x).strip() for x in ''.join(p.out).split('\n')]
    return '\n'.join(x for x in lines if x) + '\n'
