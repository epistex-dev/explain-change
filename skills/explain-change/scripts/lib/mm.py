"""Mermaid source from structured data. The agent never writes Mermaid; labels are escaped here."""
import re


def label(s, quoted=False):
    s = re.sub(r'\s+', ' ', str(s)).strip()
    s = s.replace('#', '#35;').replace(';', '#59;').replace('"', '#quot;')
    s = s.replace('<', '#lt;').replace('>', '#gt;')
    return s


CHANGED_FILL = 'rgba(255, 224, 130, 0.45)'


def sequence(flow, nlabel=lambda i: '%d. ' % i):
    ids = {a['id']: 'p%d' % i for i, a in enumerate(flow['actors'])}
    out = ['sequenceDiagram', '  autonumber off']
    for a in flow['actors']:
        out.append('  participant %s as %s' % (ids[a['id']], label(a.get('label') or a['id'])))
    open_rect = False
    for i, s in enumerate(flow['steps'], 1):
        changed = s.get('changed') is True
        if changed and not open_rect:
            out.append('  rect %s' % CHANGED_FILL)
            open_rect = True
        elif not changed and open_rect:
            out.append('  end')
            open_rect = False
        arrow = {'call': '->>', 'return': '-->>', 'async': '-)'}[s.get('kind', 'call')]
        if s['from'] == s['to']:
            out.append('  Note over %s: %s%s' % (ids[s['from']], nlabel(i), label(s['label'])))
            continue
        out.append('  %s%s%s: %s%s' % (ids[s['from']], arrow, ids[s['to']], nlabel(i), label(s['label'])))
    if open_rect:
        out.append('  end')
    return '\n'.join(out)


def flowchart(flow):
    ids = {n['id']: 'n%d' % i for i, n in enumerate(flow['nodes'])}
    out = ['flowchart TD']
    shape = {'start': '([%s])', 'end': '([%s])', 'step': '[%s]', 'decision': '{%s}'}
    for n in flow['nodes']:
        out.append('  %s%s' % (ids[n['id']], shape[n['type']] % ('"%s"' % label(n['label']))))
    for e in flow['edges']:
        lab = e.get('label')
        mid = '-->|"%s"|' % label(lab) if lab else '-->'
        out.append('  %s %s %s' % (ids[e['from']], mid, ids[e['to']]))
    changed = [ids[n['id']] for n in flow['nodes'] if n.get('changed') is True]
    out.append('  classDef changed fill:#fff3c4,stroke:#c28a00,stroke-width:2px,color:#14181f')
    out.append('  classDef decision fill:#e8f0fc,stroke:#1f5fbf,color:#14181f')
    if changed:
        out.append('  class %s changed' % ','.join(changed))
    return '\n'.join(out)
