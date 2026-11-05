"""Validate explain.json against references/explain-schema.md and against the code. Returns (errors, stats)."""
from . import check2, funcs, gitio
from .refs import Verifier

SCHEMA = 'explain-change/1'
LANGS = ('vi', 'en')
ORIGINS_CITED = ('test', 'fixture', 'seed')
ORIGINS = ORIGINS_CITED + ('run', 'illustrative')
MIN_BRANCHES_FOR_FLOWCHART = 3
MIN_BRANCHES_TO_EXPLAIN = 2
MAX_DIAGRAM_LABEL = 90
MAX_NODE_LABEL = 50


def known(x, container):
    """`x in container` that is False, not a TypeError, for unhashable x (list/dict from a malformed doc)."""
    return isinstance(x, (str, int, float, bool, type(None))) and x in container


def count_branches(flow):
    """Branches of a flowchart = outgoing edges of decision nodes."""
    decisions = {n['id'] for n in as_list(flow.get('nodes')) if isinstance(n, dict) and n.get('type') == 'decision' and isinstance(n.get('id'), str)}
    return sum(1 for e in as_list(flow.get('edges')) if isinstance(e, dict) and known(e.get('from'), decisions))


def as_list(v):
    return v if isinstance(v, list) else []


def has_cycle(nodes, edges):
    adj = {n: [] for n in nodes}
    for e in edges:
        if isinstance(e, dict) and known(e.get('from'), adj) and known(e.get('to'), adj):
            adj[e['from']].append(e['to'])
    state = {}

    def visit(n):
        state[n] = 1
        for m in adj[n]:
            if state.get(m) == 1 or (m not in state and visit(m)):
                return True
        state[n] = 2
        return False
    return any(n not in state and visit(n) for n in adj)


def validate(doc, repo, transcript=None, scope=None):
    """Dispatch on the schema version: 2 -> check2 (needs the session transcript; `scope` limits the changed files to those paths),
    absent or 1 -> the rules below."""
    if check2.is_v2(doc):
        return check2.validate(doc, repo, transcript, scope)
    errs = []
    stats = {}

    def err(path, msg):
        errs.append('%s: %s' % (path, msg))

    def text(obj, field, path, required=True):
        v = obj.get(field) if isinstance(obj, dict) else None
        if not isinstance(v, str) or (required and not v.strip()):
            err('%s.%s' % (path, field), 'required non-empty string')
            return None
        return v

    def ident(obj, path):
        """The renderer links and looks up by obj['id']: it must be a non-empty string."""
        v = obj.get('id')
        if not isinstance(v, str) or not v.strip():
            err(path + '.id', 'required non-empty string')
            return None
        return v

    def items(obj, field, path):
        v = obj.get(field) if isinstance(obj, dict) else None
        if not isinstance(v, list):
            err('%s.%s' % (path, field), 'required list')
            return []
        return v

    if not isinstance(doc, dict):
        return ['$: explain.json must be an object'], stats
    if doc.get('schema') != SCHEMA:
        err('schema', 'must be %r' % SCHEMA)
    if doc.get('version') not in (None, 1):
        err('version', 'absent or 1 for schema %s, 2 for explain-change/2' % SCHEMA)
    if doc.get('lang') not in LANGS:
        err('lang', 'must be one of %s' % (LANGS,))
    text(doc, 'title', '$')
    rng = doc.get('range')
    if not isinstance(rng, dict) or not all(isinstance(rng.get(k), str) and rng.get(k) for k in ('base', 'head', 'label')):
        err('range', 'needs base, head, label (copy from summary.json range)')
        return errs, stats
    ids_ = {}
    for k in ('base', 'head'):
        try:
            ids_[k] = gitio.resolve_rev(repo, rng[k])
        except gitio.ExplainError as e:
            err('range.' + k, str(e))
    if len(ids_) < 2:
        return errs, stats
    base, head = ids_['base'], ids_['head']  # only object ids reach git from here on
    try:
        files = gitio.changed_files(repo, base, head)
    except gitio.ExplainError as e:
        err('range', 'cannot diff %s..%s: %s' % (rng['base'][:12], rng['head'][:12], e))
        return errs, stats
    by_path = {f['path']: f for f in files}
    changed_funcs = funcs.changed_functions(repo, base, head, files)
    ver = Verifier(repo, base, head, deleted=[f['path'] for f in files if f['status'] == 'D'])
    counts = {'verified': 0, 'inferred': 0}

    def ref(r, path):
        status, e = ver.check(r)
        if e:
            err(path, e)
        else:
            counts[status] += 1
        return status

    def refs(obj, path, field='refs', minimum=1):
        lst = obj.get(field) if isinstance(obj, dict) else None
        if not isinstance(lst, list) or len(lst) < minimum:
            err('%s.%s' % (path, field), 'needs at least %d ref {file, line, snippet}' % minimum)
            return
        for i, r in enumerate(lst):
            ref(r, '%s.%s[%d]' % (path, field, i))

    def section(name, need_items=True):
        sec = doc.get(name)
        if not isinstance(sec, dict):
            err(name, 'required object')
            return {}, []
        text(sec, 'conclusion', name)
        lst = sec.get('items')
        if not isinstance(lst, list):
            err(name + '.items', 'required list')
            lst = []
        if need_items and not lst and not (isinstance(sec.get('none_reason'), str) and sec['none_reason'].strip()):
            err(name + '.items', 'empty: add items, or give none_reason')
        return sec, lst

    # 1 why
    why = doc.get('why')
    if not isinstance(why, dict):
        err('why', 'required object')
    else:
        text(why, 'conclusion', 'why')
        lines = items(why, 'lines', 'why')
        if not 2 <= len(lines) <= 5 or not all(isinstance(x, str) and x.strip() for x in lines):
            err('why.lines', '2 to 5 non-empty lines, got %d' % len(lines))
        refs(why, 'why')

    # 2 changes: every changed file in exactly one sub-change
    _, changes = section('changes', need_items=True)
    owner = {}
    ids = set()
    for i, c in enumerate(changes):
        p = 'changes.items[%d]' % i
        if not isinstance(c, dict):
            err(p, 'must be an object')
            continue
        text(c, 'title', p)
        text(c, 'summary', p)
        cid = ident(c, p)
        if cid is not None:
            if cid in ids:
                err(p + '.id', 'duplicate id %r' % cid)
            ids.add(cid)
        refs(c, p)
        fl = c.get('files')
        if not isinstance(fl, list) or not fl:
            err(p + '.files', 'needs at least one file path')
            continue
        for path in fl:
            if not isinstance(path, str) or path not in by_path:
                err(p + '.files', 'not a changed file in %s: %r' % (rng['label'], path))
            elif path in owner:
                err(p + '.files', '%s is also in sub-change %r (a file belongs to exactly one)' % (path, owner[path]))
            else:
                owner[path] = cid or p
    for path in by_path:
        if path not in owner:
            err('changes', 'changed file not covered by any sub-change: %s' % path)
    stats['files'] = (len(by_path), len(owner))

    # 3 flows
    _, flows = section('flows')
    nsteps = 0
    for i, f in enumerate(flows):
        p = 'flows.items[%d]' % i
        if not isinstance(f, dict):
            err(p, 'must be an object')
            continue
        text(f, 'title', p)
        text(f, 'summary', p)
        actors = set()
        for k, a in enumerate(as_list(f.get('actors'))):
            if not isinstance(a, dict):
                err('%s.actors[%d]' % (p, k), 'must be an object {id, label}')
                continue
            aid = ident(a, '%s.actors[%d]' % (p, k))
            if aid is not None:
                actors.add(aid)
            if 'label' in a and not isinstance(a['label'], str):
                err('%s.actors[%d].label' % (p, k), 'must be a string')
        if len(actors) < 2:
            err(p + '.actors', 'needs at least 2 actors {id, label}')
        steps = items(f, 'steps', p)
        if not steps:
            err(p + '.steps', 'needs at least 1 step')
        if steps and not any(isinstance(s, dict) and s.get('changed') is True for s in steps):
            err(p + '.steps', 'no step has changed: true (a flow in this section is affected by the change)')
        for j, s in enumerate(steps):
            sp = '%s.steps[%d]' % (p, j)
            if not isinstance(s, dict):
                err(sp, 'must be an object')
                continue
            nsteps += 1
            for k in ('from', 'to'):
                if not known(s.get(k), actors):
                    err('%s.%s' % (sp, k), 'unknown actor %r' % s.get(k))
            lab = text(s, 'label', sp)
            if lab and len(lab) > MAX_DIAGRAM_LABEL:
                err(sp + '.label', 'longer than %d characters; the diagram stays readable with a short label' % MAX_DIAGRAM_LABEL)
            if not isinstance(s.get('changed'), bool):
                err(sp + '.changed', 'required boolean')
            if s.get('kind', 'call') not in ('call', 'return', 'async'):
                err(sp + '.kind', 'call | return | async')
            r = s.get('ref')
            if r is None:
                err(sp + '.ref', 'every step needs a ref')
            else:
                ref(r, sp + '.ref')
    stats['flows'] = (len(flows), nsteps)

    # 4 logic
    lsec, logic = section('logic')
    covered = set()
    for i, it in enumerate(logic):
        p = 'logic.items[%d]' % i
        if not isinstance(it, dict):
            err(p, 'must be an object')
            continue
        file_, fn = text(it, 'file', p), text(it, 'function', p)
        covered.add((file_, fn))
        ident(it, p)
        text(it, 'title', p)
        text(it, 'summary', p)
        refs(it, p)
        if it.get('change') is not None and not known(it['change'], ids):
            err(p + '.change', 'unknown sub-change id %r (use an id from changes.items)' % (it['change'],))
        kind = it.get('kind')
        if kind == 'flowchart':
            fl = it.get('flow')
            if not isinstance(fl, dict):
                err(p + '.flow', 'kind=flowchart needs flow {nodes, edges}')
                continue
            raw_nodes = fl.get('nodes')
            if not isinstance(raw_nodes, list) or not isinstance(fl.get('edges'), list):
                err(p + '.flow', 'needs nodes (list) and edges (list)')
                continue
            nodes = {n['id'] for n in raw_nodes if isinstance(n, dict) and isinstance(n.get('id'), str)}
            for j, n in enumerate(raw_nodes):
                if not isinstance(n, dict) or not isinstance(n.get('id'), str) or not n['id'] or not isinstance(n.get('label'), str) \
                        or n.get('type') not in ('start', 'step', 'decision', 'end'):
                    err('%s.flow.nodes[%d]' % (p, j), 'needs id, label, type (start|step|decision|end)')
                elif len(n['label']) > MAX_NODE_LABEL:
                    err('%s.flow.nodes[%d].label' % (p, j), 'longer than %d characters; shorten it' % MAX_NODE_LABEL)
            edges = fl['edges']
            for j, e in enumerate(edges):
                ep = '%s.flow.edges[%d]' % (p, j)
                if not isinstance(e, dict) or not known(e.get('from'), nodes) or not known(e.get('to'), nodes):
                    err(ep, 'from/to must be declared node ids')
                    continue
                if e.get('ref') is None:
                    err(ep + '.ref', 'every edge needs a ref')
                else:
                    ref(e['ref'], ep + '.ref')
            if has_cycle(nodes, edges):
                err(p + '.flow', 'edges loop back to an earlier node; draw one pass and let end nodes say what happens next')
            nb = count_branches(fl)
            if nb < MIN_BRANCHES_FOR_FLOWCHART:
                err(p + '.flow', 'flowchart only for 3 or more branches (found %d); use kind "trace"' % nb)
            if 'trace' in it:
                err(p + '.trace', 'a logic item has a flowchart OR a trace, not both')
        elif kind == 'trace':
            tr = it.get('trace')
            if not isinstance(tr, dict):
                err(p + '.trace', 'kind=trace needs trace {input, steps, result, origin}')
                continue
            if 'flow' in it:
                err(p + '.flow', 'a logic item has a flowchart OR a trace, not both')
            inputs = items(tr, 'input', p + '.trace')
            if not inputs or not all(isinstance(x, dict) and x.get('name') and 'value' in x for x in inputs):
                err(p + '.trace.input', 'needs a list of {name, value}')
            tsteps = items(tr, 'steps', p + '.trace')
            if not tsteps:
                err(p + '.trace.steps', 'needs at least one step')
            for j, s in enumerate(tsteps):
                sp = '%s.trace.steps[%d]' % (p, j)
                if not isinstance(s, dict) or not s.get('text') or 'value' not in s:
                    err(sp, 'needs text and value')
                    continue
                if s.get('ref') is None:
                    err(sp + '.ref', 'every step needs a ref')
                else:
                    ref(s['ref'], sp + '.ref')
            text(tr, 'result', p + '.trace')
            org = tr.get('origin')
            ok = isinstance(org, dict) and org.get('kind') in ORIGINS
            if not ok:
                err(p + '.trace.origin.kind', 'one of %s' % (ORIGINS,))
            elif org['kind'] in ORIGINS_CITED:
                if ref(org.get('cite'), p + '.trace.origin.cite') == 'inferred':
                    err(p + '.trace.origin.cite', 'values from a %s must cite it with a verified ref' % org['kind'])
            elif org['kind'] == 'run':
                if not (isinstance(org.get('command'), str) and org['command'].strip()
                        and isinstance(org.get('output'), str) and org['output'].strip()):
                    err(p + '.trace.origin', 'kind=run needs command and output')
        else:
            err(p + '.kind', 'flowchart | trace')
    wanted = [f for f in changed_funcs if f['branches'] >= MIN_BRANCHES_TO_EXPLAIN and not f['test']]
    skipped = set()
    raw_skipped = lsec.get('skipped', []) if isinstance(lsec, dict) else []
    if not isinstance(raw_skipped, list):
        err('logic.skipped', 'must be a list of {file, function, reason}')
        raw_skipped = []
    for i, s in enumerate(raw_skipped):
        if isinstance(s, dict) and isinstance(s.get('file'), str) and s['file'] and isinstance(s.get('function'), str) and s['function'] \
                and isinstance(s.get('reason'), str) and s['reason'].strip():
            skipped.add((s['file'], s['function']))
        else:
            err('logic.skipped[%d]' % i, 'needs file, function, reason')
    missing = [f for f in wanted if (f['file'], f['name']) not in covered and (f['file'], f['name']) not in skipped]
    for f in missing:
        err('logic', 'changed function with %d branches not explained: %s %s (add an item, or list it in logic.skipped with a reason)'
            % (f['branches'], f['file'], f['name']))
    stats['functions'] = (len(wanted), len(wanted) - len(missing))
    stats['logic'] = len(logic)

    # 5 risks
    _, risks = section('risks')
    for i, r in enumerate(risks):
        p = 'risks.items[%d]' % i
        if not isinstance(r, dict):
            err(p, 'must be an object')
            continue
        if r.get('kind') not in ('break', 'similar'):
            err(p + '.kind', 'break | similar')
        text(r, 'text', p)
        refs(r, p)
    stats['risks'] = len(risks)

    # 6 quiz
    quiz = doc.get('quiz')
    qs = quiz.get('items') if isinstance(quiz, dict) else None
    if not isinstance(qs, list) or not 2 <= len(qs) <= 3:
        err('quiz.items', '2 to 3 questions')
        qs = qs if isinstance(qs, list) else []
    for i, q in enumerate(qs):
        p = 'quiz.items[%d]' % i
        if isinstance(q, dict):
            text(q, 'q', p)
            text(q, 'a', p)
            refs(q, p)
        else:
            err(p, 'must be an object')
    stats['quiz'] = len(qs)
    stats['refs'] = dict(counts)
    return errs, stats

