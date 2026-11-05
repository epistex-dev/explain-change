"""Validate a schema v2 explain.json (references/explain-schema.md): the five blocks of the approved layout 2, each fact
tied to the diff, the code, the architecture map or the session transcript. Returns (errors, stats); stats['warnings'] never fail."""
import re

from . import arch as archmod
from . import gitio, transcript
from .refs import Verifier

SCHEMA = 'explain-change/2'
LANGS = ('vi', 'en')
STATUSES = ('done', 'done_after_fix', 'not_done', 'changed')
NOTE_REQUIRED = ('done_after_fix', 'changed')
RESULTS = ('passed', 'failed', 'mixed')
EDGE_KINDS = ('arch', 'flow', 'tests')
SEE = ('logic', 'evidence')  # the tab that holds a request's detail
VISUAL_TONES = ('bad', 'good')
MAX_RESULT = 160  # a request's `result` is one short sentence; the detail lives in its own tab
DUP_RUN = 6  # words in a row that two blocks must not share
MAX_STEP_LABEL = 60
CONCLUSIONS = ('requests', 'map', 'logic', 'rationale', 'evidence')
QUOTE_ROLES = ('user', 'assistant', 'tool_result', 'report')
URL_ROLES = QUOTE_ROLES
BLOCK_ALLOW = {  # grounding kinds each block accepts
    'step': ('refs', 'code', 'transcript', 'url', 'inferred'),
    'example': ('evidence_id', 'tool_call', 'transcript', 'code', 'inferred'),
    'rationale': ('transcript', 'report', 'code', 'url', 'inferred'),
    'request': ('transcript', 'report', 'tool_call', 'code'),
    'evidence': ('tool_call', 'user_reported', 'report'),
}


def is_v2(doc):
    return isinstance(doc, dict) and (doc.get('version') == 2 or doc.get('schema') == SCHEMA)


def derive_verdict(doc):
    """What the header pill shows, computed from requests (block 1) and evidence.ran (block 5)."""
    reqs = [r for r in as_list(doc.get('requests')) if isinstance(r, dict)]
    ev = doc.get('evidence')
    ran = [r for r in as_list(ev.get('ran') if isinstance(ev, dict) else None) if isinstance(r, dict)]
    results = [r.get('result') for r in ran]
    return {'requests': {'done': sum(r.get('status') in ('done', 'done_after_fix') for r in reqs),
                         'total': sum(r.get('status') != 'changed' for r in reqs)},
            'tests_passed': bool(results) and 'failed' not in results and 'passed' in results,
            'caveats': results.count('mixed')}


def as_list(v):
    return v if isinstance(v, list) else []


def nonempty(v):
    return isinstance(v, str) and bool(v.strip())


def validate(doc, repo, transcript_path=None, scope=None):
    errs, stats = _validate(doc, repo, transcript_path, scope)
    return [transcript.redact(e) for e in errs], stats  # an error line quotes the doc; never print a secret


def _validate(doc, repo, transcript_path=None, scope=None):
    errs, warns = [], []
    stats = {'version': 2, 'warnings': warns}
    queries = []  # (transcript.Query, path, what)
    module_refs = []  # (path, list of module ids)
    counts = {'verified': 0, 'inferred': 0}
    unverified = []

    def err(path, msg):
        errs.append('%s: %s' % (path, msg))

    def text(obj, field, path, required=True):
        v = obj.get(field) if isinstance(obj, dict) else None
        if not isinstance(v, str) or (required and not v.strip()):
            err('%s.%s' % (path, field), 'required non-empty string')
            return None
        return v

    def lst(obj, field, path, minimum=0):
        v = obj.get(field) if isinstance(obj, dict) else None
        if not isinstance(v, list) or len(v) < minimum:
            err('%s.%s' % (path, field), 'required list%s' % (' with at least %d item(s)' % minimum if minimum else ''))
            return []
        return v

    def opt_list(obj, field, path):
        """An optional list field: absent or null is empty; any other type is an error."""
        v = obj.get(field) if isinstance(obj, dict) else None
        if v is None:
            return []
        if not isinstance(v, list):
            err('%s.%s' % (path, field), 'must be a list')
            return []
        return v

    def modules_of(obj, path):
        m = obj.get('modules') if isinstance(obj, dict) else None
        if m is None:
            return
        if not isinstance(m, list) or not all(isinstance(x, str) for x in m):
            err(path + '.modules', 'must be a list of module ids from map.modules')
            return
        module_refs.append((path + '.modules', m))

    if not isinstance(doc, dict):
        return ['$: explain.json must be an object'], stats
    if doc.get('schema') != SCHEMA:
        err('schema', 'must be %r' % SCHEMA)
    if doc.get('version') != 2:
        err('version', 'must be 2')
    if doc.get('lang') not in LANGS:
        err('lang', 'must be one of %s' % (LANGS,))
    text(doc, 'title', '$')
    if doc.get('subtitle') is not None and not isinstance(doc['subtitle'], str):
        err('subtitle', 'must be a string')
    concl = doc.get('conclusions')
    if not isinstance(concl, dict):
        err('conclusions', 'required object with %s' % ', '.join(CONCLUSIONS))
    else:
        for k in CONCLUSIONS:
            text(concl, k, 'conclusions')

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
    base, head = ids_['base'], ids_['head']
    try:
        files = gitio.changed_files(repo, base, head, scope)
    except gitio.ExplainError as e:
        err('range', 'cannot diff %s..%s: %s' % (rng['base'][:12], rng['head'][:12], e))
        return errs, stats
    by_path = {f['path']: f for f in files}
    if not files:
        err('range', 'the range has no changes%s; there is nothing to explain' % (' under the --path scope %s' % ', '.join(scope) if scope else ''))
    ver = Verifier(repo, base, head, deleted=[f['path'] for f in files if f['status'] == 'D'])

    # ---- transcript
    tpath = transcript_path or doc.get('transcript')
    tfiles = {}
    if isinstance(tpath, str) and tpath:
        try:
            tpath = transcript.safe_path(tpath)
            tfiles = transcript.session_files(tpath)
            transcript.learn(tpath)  # the sweep below and every error line then hide the bare value too
        except gitio.ExplainError as e:
            err('transcript', str(e))
            tpath = None
    else:
        tpath = None
        if nonempty(doc.get('transcript_unavailable')):
            warns.append('transcript unavailable (%s): requests, tests and quotes are NOT checked against a session' % doc['transcript_unavailable'].strip())
        else:
            err('transcript', 'required: pass --transcript <file under ~/.claude/projects> or set "transcript"; '
                'without a session set "transcript_unavailable" to the reason (everything then stays unverified)')

    stats['transcript'] = tpath is not None  # False: nothing was checked against a session (the page says so)

    def query(q, path):
        queries.append((q, path))
        return q

    def tid_of(src, path):
        t = src.get('transcript', 'main')
        if not isinstance(t, str) or not (t == 'main' or transcript.AGENT_ID.match(t)):
            err(path + '.transcript', '"main" or an agent id like "agent-a1b2c3"')
            return None
        if tpath and t not in tfiles:
            err(path + '.transcript', 'unknown transcript %r; this session has: %s' % (t, ', '.join(tfiles)))
            return None
        return t

    def ref_ok(r, path, side=None):
        if isinstance(r, dict) and side and not r.get('side') and not (isinstance(r.get('file'), str) and r['file'] in ver.deleted):
            r = {**r, 'side': side}
        status, e = ver.check(r)
        if e:
            err(path, e)
            return None
        counts[status] += 1
        return status

    def source(src, path, allow, side=None, sink=None):
        """Validate one Source object; returns its kind, or None when invalid."""
        if not isinstance(src, dict):
            err(path, 'source must be an object {kind, ...}')
            return None
        kind = 'inferred' if src.get('inferred') is True and 'kind' not in src else src.get('kind')
        if kind not in allow:
            err(path + '.kind', 'one of %s here' % (allow,))
            return None
        if kind == 'inferred':
            counts['inferred'] += 1
            stats.setdefault('inferred', []).append(path)
        elif kind == 'code':
            ref_ok(src.get('ref'), path + '.ref', side)
        elif kind in ('transcript', 'user_reported', 'report'):
            q = text(src, 'quote', path)
            if kind == 'report':
                stats['reported'] = stats.get('reported', 0) + 1
            if q and tpath:
                tid = 'main' if kind == 'user_reported' else tid_of(src, path)
                if tid:
                    roles = {'user_reported': ('user',), 'report': ('report', 'assistant')}.get(kind, QUOTE_ROLES)
                    query(transcript.Query('quote', tid, roles, text=q), path + '.quote')
            elif q:
                unverified.append(path)
            if sink is not None and q:
                sink.append(q)
        elif kind == 'url':
            u = src.get('url')
            if not isinstance(u, str) or not re.match(r'https?://[^\s]+\Z', u):
                err(path + '.url', 'needs an http(s) URL')
            elif tpath:
                query(transcript.Query('url', 'main', URL_ROLES, text=u), path + '.url')
            else:
                unverified.append(path)
        elif kind == 'tool_call':
            c, x = text(src, 'command', path), text(src, 'excerpt', path)
            if c and x and tpath:
                tid = tid_of(src, path)
                if tid:
                    query(transcript.Query('tool', tid, command=c, excerpt=x), path)
            elif c and x:
                unverified.append(path)
            if sink is not None and x:
                sink.append(x)
        return kind

    def grounding(obj, path, block, side=None, sink=None):
        """Exactly one of refs / source / inferred / evidence_id on obj."""
        allow = BLOCK_ALLOW[block]
        given = [k for k in ('refs', 'source', 'inferred', 'evidence_id') if obj.get(k) not in (None, False)]
        if len(given) != 1:
            err(path, 'needs exactly one of refs, source, inferred: true%s (got %s)' % (', evidence_id' if 'evidence_id' in allow else '', ', '.join(given) or 'none'))
            return
        k = given[0]
        if k == 'refs':
            if 'refs' not in allow:
                err(path + '.refs', 'not accepted here')
            elif not isinstance(obj['refs'], list) or not obj['refs']:
                err(path + '.refs', 'needs at least one ref {file, line, snippet}')
            else:
                for i, r in enumerate(obj['refs']):
                    ref_ok(r, '%s.refs[%d]' % (path, i), side)
        elif k == 'inferred':
            if obj['inferred'] is not True or 'inferred' not in allow:
                err(path + '.inferred', 'only true, and only where an unsourced claim is allowed')
            else:
                counts['inferred'] += 1
                stats.setdefault('inferred', []).append(path)
        elif k == 'evidence_id':
            if 'evidence_id' not in allow:
                err(path + '.evidence_id', 'not accepted here')
            else:
                evidence_links.append((path + '.evidence_id', obj['evidence_id']))
        else:
            srcs = obj['source'] if isinstance(obj['source'], list) else [obj['source']]
            if not srcs:
                err(path + '.source', 'empty')
            for i, s in enumerate(srcs):
                source(s, path + '.source' + ('[%d]' % i if isinstance(obj['source'], list) else ''), allow, side, sink)

    evidence_links = []

    # ---- block 1: requests
    reqs = doc.get('requests')
    if not isinstance(reqs, list) or not reqs:
        err('requests', 'required list with at least one request')
        reqs = []
    for i, r in enumerate(reqs):
        p = 'requests[%d]' % i
        if not isinstance(r, dict):
            err(p, 'must be an object')
            continue
        quote = text(r, 'quote', p)
        if quote and tpath:
            query(transcript.Query('quote', 'main', ('user',), text=quote), p + '.quote')
        elif quote:
            unverified.append(p + '.quote')
        if r.get('status') not in STATUSES:
            err(p + '.status', 'one of %s' % (STATUSES,))
        result = text(r, 'result', p)
        if result and len(result) > MAX_RESULT:
            warns.append('%s.result: %d characters; a request row is one short sentence (at most %d), put the detail in logic or evidence and set "see"' % (p, len(result), MAX_RESULT))
        if r.get('see') is not None and r['see'] not in SEE:
            err(p + '.see', 'one of %s (the tab that holds the detail)' % (SEE,))
        if r.get('status') in NOTE_REQUIRED:
            text(r, 'note', p)
        elif r.get('note') is not None and not isinstance(r['note'], str):
            err(p + '.note', 'must be a string')
        modules_of(r, p)
        if r.get('source') is not None:  # optional: where the outcome in `result` comes from
            grounding({'source': r['source']}, p, 'request')

    # ---- block 2: map
    mp = doc.get('map')
    modules = []
    mod_ids = set()
    arch = None
    try:
        arch = archmod.Architecture(archmod.find_architecture(repo)) if archmod.find_architecture(repo) else None
    except archmod.ArchError as e:
        err('map', str(e))
    mapping = archmod.map_files(repo, files, arch)

    def dir_exists(root, mid):
        if mid == '.':
            return True
        path = '%s/%s' % (root, mid) if root else mid
        return bool(gitio.git(repo, 'ls-tree', '-d', '--name-only', '-z', head, '--', ':(literal)' + path, check=False).strip(b'\0'))
    stats['map_source'] = 'floorplan' if arch else 'dirs'
    if mapping['overlaps']:
        warns.append('architecture globs overlap for %d changed file(s); first declared wins: %s' % (
            len(mapping['overlaps']), '; '.join('%s -> %s (tied: %s)' % (o['path'], o['winner'], ', '.join(o['tied'])) for o in mapping['overlaps'][:5])))
    if not isinstance(mp, dict):
        err('map', 'required object {modules, edges?}')
        mp = {}
    modules = lst(mp, 'modules', 'map', 1)
    mapping = archmod.accept_legacy(mapping, modules)  # a doc built on the old top-directory rule keeps validating
    if mapping.get('rule') == 'legacy':
        stats['map_source'] = 'dirs (legacy top-directory ids)'
    owner = {}
    for i, m in enumerate(modules):
        p = 'map.modules[%d]' % i
        if not isinstance(m, dict):
            err(p, 'must be an object')
            continue
        mid = m.get('id')
        if not nonempty(mid):
            err(p + '.id', 'required non-empty string')
            continue
        if mid in mod_ids:
            err(p + '.id', 'duplicate module id %r' % mid)
        mod_ids.add(mid)
        changed, outside = m.get('changed'), m.get('outside') is True
        if not isinstance(changed, bool):
            err(p + '.changed', 'required boolean')
            continue
        if m.get('outside') is not None and not isinstance(m['outside'], bool):
            err(p + '.outside', 'must be true or false')
        if m.get('kind') is not None and not isinstance(m['kind'], str):
            err(p + '.kind', 'must be a string (omit it: the architecture gives it)')
        known_node = arch.nodes.get(mid) if arch else None
        if outside:
            if changed:
                err(p, 'an outside actor cannot be changed (it is not in the diff)')
            if arch and mid in arch.nodes:
                err(p + '.id', '%r is a module of the architecture: list it as a module, not as outside: true' % mid)
            text(m, 'name', p)
            text(m, 'summary', p)
        elif arch:
            if mid == archmod.OTHER:
                text(m, 'name', p)
            elif known_node is None:
                err(p + '.id', 'not a node of %s: %r (ids are listed by collect.py --v2)' % (arch.path, mid))
            else:
                for f, want in (('name', known_node.get('label')), ('summary', known_node.get('summary'))):
                    if f in m and m[f] != want:
                        err('%s.%s' % (p, f), 'differs from the architecture (%r); omit it to use that text' % want)
        else:
            if mid == archmod.OTHER:
                err(p + '.id', '"_other" is allowed only with floorplan/architecture.json; without one, files outside the change are left off the map: '
                    'rerun collect.py with --path <the folder you explain> (the map then holds only in-scope files)')
            elif changed and mid not in set(mapping['assigned'].values()):
                err(p + '.id', '%r is not a module of the directory map (without floorplan/architecture.json: one module per child directory of the files\' common '
                    'directory, "." for files directly in it; collect.py --v2 lists them): %s' % (mid, ', '.join(sorted(set(mapping['assigned'].values())))))
            elif not changed and not dir_exists(mapping.get('root') or '', mid):
                err(p + '.id', 'an unchanged neighbour without an architecture is a directory under %s that exists at head: %r' % (mapping.get('root') or 'the repo root', mid))
            text(m, 'name', p)
            text(m, 'summary', p)
        modules_of(m, p)
        mfiles = m.get('files')
        if changed:
            text(m, 'what_changed', p)
            if not isinstance(mfiles, list) or not mfiles:
                err(p + '.files', 'a changed module lists its changed files {path, add, del}')
                continue
            for k, f in enumerate(mfiles):
                fp = '%s.files[%d]' % (p, k)
                path = f.get('path') if isinstance(f, dict) else None
                if not isinstance(path, str) or path not in by_path:
                    err(fp, 'not a changed file in %s: %r' % (rng['label'], path))
                    continue
                if path in owner:
                    err(fp, '%s is also in module %r (a file belongs to exactly one)' % (path, owner[path]))
                    continue
                owner[path] = mid
                want = mapping['assigned'][path]
                if want != mid:
                    err(fp, '%s belongs to module %r (%s), not %r' % (path, want, 'architecture globs' if arch else 'directory map', mid))
                g = by_path[path]
                if f.get('add') != g['add'] or f.get('del') != g['del']:
                    err(fp, '+/- counts differ from git: +%d -%d' % (g['add'], g['del']))
                if f.get('status') is not None and f['status'] != g['status']:
                    err(fp + '.status', 'git says %s' % g['status'])
        else:
            if mfiles:
                err(p + '.files', 'an unchanged module lists no files')
            if m.get('what_changed'):
                err(p + '.what_changed', 'an unchanged module has no what_changed')
    for path in by_path:
        if path not in owner:
            err('map', 'changed file not assigned to any changed module: %s (collect.py --v2 shows its module)' % path)
    if files and not any(isinstance(m, dict) and m.get('changed') is True for m in modules):
        err('map.modules', 'at least one module is changed')
    for i, e in enumerate(opt_list(mp, 'edges', 'map')):
        p = 'map.edges[%d]' % i
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e[k] in mod_ids for k in ('from', 'to')):
            err(p, 'from/to must be ids of map.modules')
            continue
        if e.get('kind') not in EDGE_KINDS:
            err(p + '.kind', 'one of %s' % (EDGE_KINDS,))
        elif e['kind'] == 'arch' and not (arch and any(a.get('from') == e['from'] and a.get('to') == e['to'] for a in arch.edges)):
            err(p, 'kind "arch" needs an edge %s -> %s in the architecture file' % (e['from'], e['to']))
        if e.get('label') is not None and not isinstance(e['label'], str):
            err(p + '.label', 'must be a string')
    stats['modules'] = (sum(1 for m in modules if isinstance(m, dict) and m.get('changed') is True), len(modules))
    stats['files'] = (len(by_path), len(owner))

    # ---- block 3: logic
    lg = doc.get('logic')
    if not isinstance(lg, dict):
        err('logic', 'required object {before, after, ...}')
        lg = {}
    def visual(v, path):
        if v is None:
            return
        shape = 'optional {kind: "form", rows: [{label, value, state?}]} or {kind: "dialog", tone: "bad"|"good", title, subtitle?}'
        if not isinstance(v, dict) or v.get('kind') not in ('form', 'dialog'):
            err(path, shape)
        elif v['kind'] == 'form':
            rows = v.get('rows')
            if not isinstance(rows, list) or not rows:
                err(path + '.rows', 'a form needs a list of rows [{label, value, state?}]')
                return
            for k, row in enumerate(rows):
                rp = '%s.rows[%d]' % (path, k)
                if not isinstance(row, dict):
                    err(rp, 'must be an object {label, value, state?}')
                    continue
                text(row, 'label', rp)
                text(row, 'value', rp)
                if row.get('state') is not None and not isinstance(row['state'], str):
                    err(rp + '.state', 'must be a string')
        else:
            if v.get('tone') not in VISUAL_TONES:
                err(path + '.tone', 'one of %s' % (VISUAL_TONES,))
            text(v, 'title', path)
            if v.get('subtitle') is not None and not isinstance(v['subtitle'], str):
                err(path + '.subtitle', 'must be a string')

    nsteps = []
    for side, key in (('base', 'before'), ('head', 'after')):
        raw = lg.get(key)
        if key == 'before' and not raw and nonempty(lg.get('before_none_reason')):
            raw = []
        else:
            raw = lst(lg, key, 'logic', 1)
        for i, s in enumerate(raw):
            p = 'logic.%s[%d]' % (key, i)
            if not isinstance(s, dict):
                err(p, 'must be an object')
                continue
            lab = text(s, 'label', p)
            if lab and len(lab) > MAX_STEP_LABEL:
                err(p + '.label', 'longer than %d characters' % MAX_STEP_LABEL)
            text(s, 'text', p)
            modules_of(s, p)
            visual(s.get('visual'), p + '.visual')
            grounding(s, p, 'step', side)
        nsteps.append(len(raw))
    for k in ('before_title', 'after_title'):
        if lg.get(k) is not None and not isinstance(lg[k], str):
            err('logic.' + k, 'must be a string')
    for i, c in enumerate(opt_list(lg, 'cases', 'logic')):
        p = 'logic.cases[%d]' % i
        if not isinstance(c, dict):
            err(p, 'must be an object')
            continue
        text(c, 'title', p)
        text(c, 'text', p)
        modules_of(c, p)
        grounding(c, p, 'step', 'head')
    for i, x in enumerate(opt_list(lg, 'examples', 'logic')):
        p = 'logic.examples[%d]' % i
        if not isinstance(x, dict):
            err(p, 'must be an object')
            continue
        text(x, 'text', p)
        modules_of(x, p)
        grounding(x, p, 'example', 'head')
    stats['steps'] = tuple(nsteps)

    # ---- block 4: rationale
    ra = doc.get('rationale')
    if not isinstance(ra, dict):
        err('rationale', 'required object {chosen, rejected, tradeoff?, notes?}')
        ra = {}
    ch = ra.get('chosen')
    if not isinstance(ch, dict):
        err('rationale.chosen', 'required object {text, source}')
    else:
        text(ch, 'text', 'rationale.chosen')
        modules_of(ch, 'rationale.chosen')
        grounding(ch, 'rationale.chosen', 'rationale', 'head')
    rej = ra.get('rejected')
    if not isinstance(rej, list):
        err('rationale.rejected', 'required list (may be empty)')
        rej = []
    for i, r in enumerate(rej):
        p = 'rationale.rejected[%d]' % i
        if not isinstance(r, dict):
            err(p, 'must be an object')
            continue
        text(r, 'option', p)
        text(r, 'why_not', p)
        modules_of(r, p)
        grounding(r, p, 'rationale', 'head')
    for key in ('tradeoff',):
        t = ra.get(key)
        if t is not None:
            if not isinstance(t, dict):
                err('rationale.' + key, 'must be an object {text, source}')
            else:
                text(t, 'text', 'rationale.' + key)
                modules_of(t, 'rationale.' + key)
                grounding(t, 'rationale.' + key, 'rationale', 'head')
    for i, n in enumerate(opt_list(ra, 'notes', 'rationale')):
        p = 'rationale.notes[%d]' % i
        if isinstance(n, dict):
            text(n, 'text', p)
            modules_of(n, p)
            grounding(n, p, 'rationale', 'head')
        else:
            err(p, 'must be an object {text, source}')
    stats['rejected'] = len(rej)

    # ---- block 5: evidence
    ev = doc.get('evidence')
    if not isinstance(ev, dict):
        err('evidence', 'required object {ran, not_checked}')
        ev = {}
    ran = lst(ev, 'ran', 'evidence')
    ran_ids = set()
    passed_runs = []  # (path, tool queries behind a `passed` item, whether a user or worker quote also backs it)
    for i, r in enumerate(ran):
        p = 'evidence.ran[%d]' % i
        if not isinstance(r, dict):
            err(p, 'must be an object')
            continue
        if r.get('id') is not None:
            if not nonempty(r['id']) or r['id'] in ran_ids:
                err(p + '.id', 'unique non-empty string')
            else:
                ran_ids.add(r['id'])
        text(r, 'what', p)
        text(r, 'detail', p)
        if r.get('result') not in RESULTS:
            err(p + '.result', 'one of %s' % (RESULTS,))
        modules_of(r, p)
        if not isinstance(r.get('source'), (dict, list)) or r.get('source') == []:
            err(p + '.source', 'required: a tool_call {command, excerpt, transcript?} or user_reported {quote} (or a list of them)')
            continue
        cited = []
        first_q = len(queries)
        grounding({'source': r['source']}, p, 'evidence', sink=cited)
        if r.get('result') == 'passed':
            srcs = r['source'] if isinstance(r['source'], list) else [r['source']]
            by_hand = any(isinstance(x, dict) and x.get('kind') in ('user_reported', 'report') for x in srcs)
            passed_runs.append((p, [q for q, _ in queries[first_q:] if q.kind == 'tool'], by_hand))
        nums = {n for n in re.findall(r'\d{2,}', r.get('detail', '') if isinstance(r.get('detail'), str) else '')}
        if cited and tpath:
            seen = ' '.join(cited)
            missing = sorted(n for n in nums if n not in seen)
            if missing:
                warns.append('%s: numbers in detail that no cited excerpt contains: %s' % (p, ', '.join(missing)))
    nc = lst(ev, 'not_checked', 'evidence')
    for i, n in enumerate(nc):
        p = 'evidence.not_checked[%d]' % i
        if isinstance(n, dict):
            text(n, 'what', p)
            if n.get('why') is not None and not isinstance(n['why'], str):
                err(p + '.why', 'must be a string')
            modules_of(n, p)
        else:
            err(p, 'must be an object {what, why?}')
    stats['ran'], stats['not_checked'] = len(ran), len(nc)

    # ---- cross references
    for path, eid in evidence_links:
        if not isinstance(eid, str) or eid not in ran_ids:
            err(path, 'no evidence.ran item with id %r' % (eid,))
    for path, ms in module_refs:
        for x in ms:
            if x not in mod_ids:
                err(path, 'unknown module id %r (not in map.modules)' % x)

    # ---- a credential never reaches the doc, the page or this report
    def sweep(node, path, in_snippet=False):
        """in_snippet: a code line quoted from the diff. Code names its own variables (`password: z.string()`), so only a credential
        learned from the session counts there, not a label."""
        if isinstance(node, str):
            if transcript.contains_learned(node):
                err(path, 'contains a password, token or key that the session shows; the page would show it. Leave the secret out')
            elif not in_snippet and transcript.has_secret(node):
                err(path, 'contains what looks like a password, token or key; the page would show it. Quote another part of the message and leave the secret out')
        elif isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and transcript.contains_learned(k):
                    err(path, 'a key contains a password, token or key that the session shows')
                sweep(v, '%s.%s' % (path, k) if path else str(k), k == 'snippet' and bool(re.search(r'(^|\.)refs?(\[\d+\])?$', path)))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                sweep(v, '%s[%d]' % (path, i), in_snippet)
    sweep(doc, '')

    # ---- each fact in full in one block: a request's result must not repeat logic or evidence
    def words(v):
        return re.findall(r'\w+', v.lower()) if isinstance(v, str) else []

    def grams(v):
        w = words(v)
        return {tuple(w[i:i + DUP_RUN]) for i in range(len(w) - DUP_RUN + 1)}

    homes = []  # (where, text) in logic and evidence
    for key in ('before', 'after', 'cases', 'examples'):
        for i, st in enumerate(as_list(lg.get(key))):
            if isinstance(st, dict):
                homes.append(('logic.%s[%d]' % (key, i), st.get('text')))
    for i, st in enumerate(ran):
        if isinstance(st, dict):
            homes += [('evidence.ran[%d]' % i, st.get('what')), ('evidence.ran[%d]' % i, st.get('detail'))]
    home_grams = [(w, grams(t)) for w, t in homes]
    for i, r in enumerate(reqs):
        g = grams(r.get('result')) if isinstance(r, dict) else set()
        hit = next((w for w, hg in home_grams if g & hg), None)
        if hit:
            warns.append('requests[%d].result repeats %d or more words in a row of %s: say it once there and link it with "see"' % (i, DUP_RUN, hit))

    # ---- transcript lookups (one streaming pass per transcript file)
    if tpath and queries:
        qs = [q for q, _ in queries]
        tstats = transcript.resolve_queries(tpath, qs)
        for tid, st in tstats.items():
            w = st.warning('transcript %s' % tid)
            if w:
                warns.append(w)
        for q, path in queries:
            if q.too_short():
                err(path, 'too short to ground anything (at least %d characters)' % transcript.MIN_NEEDLE)
            elif q.found:
                continue
            elif q.kind == 'quote':
                err(path, 'quote not found in %s of transcript %s: %r' % (
                    'a message of the user' if q.roles == {'user'} else 'any message', q.tid, q.text[:80]))
            elif q.kind == 'url':
                err(path, 'URL not found anywhere in the transcript: %s' % q.text[:100])
            elif q.command_seen:
                err(path, 'the result excerpt is not in the result of the call that ran this command (transcript %s)' % q.tid)
            else:
                err(path, 'command not found in any tool call of transcript %s: %r (only a Bash call that ran it counts, not a command inside a worker brief or a written file)' % (q.tid, q.command[:80]))
        for path, qs_, by_hand in passed_runs:
            if qs_ and not by_hand and all(q.found and not q.found_ok for q in qs_):
                err(path + '.result', '"passed" rests on tool calls whose result is an error (is_error); an errored run cannot back a pass (use "failed" or "mixed")')
    stats['verified_in_transcript'] = sum(1 for q, _ in queries if q.found)
    stats['unverified'] = len(unverified)
    if unverified:
        warns.append('%d quote(s)/tool call(s) not checked against any transcript' % len(unverified))
    stats['refs'] = dict(counts)
    stats['verdict'] = derive_verdict(doc)
    given = doc.get('verdict')
    if given is not None:
        want = stats['verdict']
        if not isinstance(given, dict) or given.get('requests') != want['requests'] or given.get('tests_passed') != want['tests_passed']:
            err('verdict', 'is derived from requests and evidence; leave it out or write %s' % {'requests': want['requests'], 'tests_passed': want['tests_passed']})
    return errs, stats
