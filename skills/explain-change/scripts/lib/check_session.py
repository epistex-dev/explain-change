"""Validate an explain-session/1 doc (references/session-schema.md): the themes of a whole session, each event tied to the session
transcript. Grounding, credential sweep and error-result rules are the ones of schema v2 (lib/ground.py). Returns (errors, stats)."""
import json
import os

from . import gitio, ground, outward, session, transcript
from .ground import as_list, nonempty

SCHEMA = 'explain-session/1'
LANGS = ('vi', 'en')
STATUSES = ('done', 'done_by_user', 'done_needs_you', 'in_progress', 'not_done')
EVENT_KINDS = ('asked', 'decided', 'redirected', 'blocked', 'done', 'outward', 'in_progress')
SOURCES = ('transcript', 'user_reported', 'report', 'tool_call', 'url', 'inferred')
EVIDENCE_SOURCES = ('transcript', 'user_reported', 'report', 'tool_call')
MAX_LINE = 200  # an outcome or an event is one line
MAX_SUMMARY = 300
BY_HAND = ('user_reported', 'report')


def is_session(doc):
    return isinstance(doc, dict) and doc.get('schema') == SCHEMA


def validate(doc, transcript_path=None, base_dir=None):
    """base_dir: the folder a theme's change_doc is relative to (the doc's own folder)."""
    errs, stats = _validate(doc, transcript_path, base_dir)
    return [transcript.redact(e) for e in errs], stats


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _validate(doc, transcript_path, base_dir):
    errs, warns = [], []
    stats = {'kind': 'session', 'warnings': warns}

    def err(path, msg):
        errs.append('%s: %s' % (path, msg))

    if not isinstance(doc, dict):
        return ['$: the doc must be an object'], stats
    if doc.get('schema') != SCHEMA:
        err('schema', 'must be %r' % SCHEMA)
    if doc.get('lang') not in LANGS:
        err('lang', 'must be one of %s' % (LANGS,))

    def line(obj, field, path, limit=MAX_LINE):
        v = obj.get(field) if isinstance(obj, dict) else None
        if not nonempty(v):
            err('%s.%s' % (path, field), 'required non-empty string')
            return None
        if '\n' in v.strip():
            err('%s.%s' % (path, field), 'one line, no line breaks')
        elif len(v) > limit:
            warns.append('%s.%s: %d characters; keep it to one short line (at most %d)' % (path, field, len(v), limit))
        return v

    line(doc, 'title', '$')
    line(doc, 'summary', '$', MAX_SUMMARY)

    # ---- transcript
    tpath, tfiles = doc.get('transcript') if transcript_path is None else transcript_path, {}
    if isinstance(tpath, str) and tpath:
        try:
            tpath = transcript.safe_path(tpath)
            tfiles = transcript.session_files(tpath)
            transcript.learn(tpath)  # a bare occurrence of a credential the session shows is then hidden and refused everywhere
        except gitio.ExplainError as e:  # : outside ~/.claude/projects or not a file
            err('transcript', str(e))
            tpath = None
    else:
        tpath = None
        if nonempty(doc.get('transcript_unavailable')):
            warns.append('transcript checks off (%s): quotes, commands and outward counts are not compared with a session' % doc['transcript_unavailable'].strip())
        else:
            err('transcript', 'required: pass --transcript <file under ~/.claude/projects> or set "transcript"; '
                'without a session set "transcript_unavailable" to the reason')
    stats['transcript'] = tpath is not None

    not_compared, inferred = [], []
    grd = ground.Grounder(err, tpath, tfiles, not_compared, inferred.append)
    queries = grd.queries

    def sources(obj, path, allow=SOURCES, sink=None):
        """The `source` of obj: one Source or a non-empty list of them. Returns the kinds."""
        s = obj.get('source') if isinstance(obj, dict) else None
        srcs = s if isinstance(s, list) else [s] if s is not None else []
        if not srcs:
            err(path + '.source', 'required: a source {kind, ...} or a list of them; kinds here: %s' % (allow,))
        return [grd.source(x, path + '.source' + ('[%d]' % i if isinstance(s, list) else ''), allow, sink) for i, x in enumerate(srcs)]

    # ---- themes
    themes = doc.get('themes')
    if not isinstance(themes, list) or not themes:
        err('themes', 'required list with at least one theme')
        themes = []
    ids = {}
    done_runs = []  # (path, tool queries behind a `done` event, backed by hand)
    order_checks = []  # (path, order, quote)
    outward_events = set()
    for i, t in enumerate(themes):
        p = 'themes[%d]' % i
        if not isinstance(t, dict):
            err(p, 'must be an object')
            continue
        tid = t.get('id')
        if not nonempty(tid):
            err(p + '.id', 'required non-empty string')
        elif tid in ids:
            err(p + '.id', 'duplicate theme id %r' % tid)
        else:
            ids[tid] = t.get('status')
        line(t, 'title', p)
        if t.get('status') not in STATUSES:
            err(p + '.status', 'one of %s' % (STATUSES,))
        line(t, 'outcome', p)
        cd = t.get('change_doc')
        if cd is not None:
            _change_doc(cd, p + '.change_doc', base_dir, err)
        evs = t.get('events')
        if not isinstance(evs, list) or not evs:
            err(p + '.events', 'required list with at least one event')
            continue
        last = None
        for j, e in enumerate(evs):
            ep = '%s.events[%d]' % (p, j)
            if not isinstance(e, dict):
                err(ep, 'must be an object')
                continue
            if e.get('kind') not in EVENT_KINDS:
                err(ep + '.kind', 'one of %s' % (EVENT_KINDS,))
            elif e['kind'] == 'outward' and isinstance(tid, str):
                outward_events.add(tid)
            line(e, 'text', ep)
            o = e.get('order')
            if o is not None:
                if not _is_int(o) or o < 0:
                    err(ep + '.order', 'a whole number: the turn u<N> of the digest where this happened')
                elif last is not None and o < last:
                    err(ep + '.order', 'events must be in order: %d comes after %d' % (o, last))
                else:
                    last = o
            first_q = len(queries)
            kinds = sources(e, ep)
            if e.get('kind') == 'done':
                done_runs.append((ep, [q for q, _ in queries[first_q:] if q.kind == 'tool'], any(k in BY_HAND for k in kinds)))
            if _is_int(o):
                order_checks.append((ep, o, [q.text for q, _ in queries[first_q:] if q.kind == 'quote' and q.roles == {'user'}]))
    stats['themes'] = len(ids)
    stats['events'] = sum(len(as_list(t.get('events'))) for t in themes if isinstance(t, dict))
    stats['statuses'] = {s: sum(1 for v in ids.values() if v == s) for s in STATUSES}

    def theme_ref(obj, path):
        r = obj.get('theme') if isinstance(obj, dict) else None
        if not isinstance(r, str) or r not in ids:
            err(path + '.theme', 'no theme with id %r (themes: %s)' % (r, ', '.join(map(str, ids)) or 'none'))
            return None
        return r

    def block(name):
        v = doc.get(name)
        if not isinstance(v, list):
            err(name, 'required list (empty when there is nothing to list)')
            return []
        return v

    # ---- needs_you, decided
    needs = set()
    for i, n in enumerate(block('needs_you')):
        p = 'needs_you[%d]' % i
        if not isinstance(n, dict):
            err(p, 'must be an object {text, theme, source}')
            continue
        line(n, 'text', p)
        needs.add(theme_ref(n, p))
        sources(n, p)
    for tid, st in ids.items():
        if st == 'done_needs_you' and tid not in needs:
            err('themes', 'theme %r is done_needs_you but no needs_you item points at it' % tid)
    irreversible = 0
    for i, d in enumerate(block('decided')):
        p = 'decided[%d]' % i
        if not isinstance(d, dict):
            err(p, 'must be an object {text, reversible, theme, source}')
            continue
        line(d, 'text', p)
        if not isinstance(d.get('reversible'), bool):
            err(p + '.reversible', 'required true or false')
        else:
            irreversible += not d['reversible']
        theme_ref(d, p)
        sources(d, p)
    stats['needs_you'], stats['decided'], stats['irreversible'] = len(needs), len(as_list(doc.get('decided'))), irreversible

    # ---- outward
    claimed, scratch_claimed = {}, 0
    for i, o in enumerate(block('outward')):
        p = 'outward[%d]' % i
        if not isinstance(o, dict):
            err(p, 'must be an object {kind, count, themes, evidence}')
            continue
        k = o.get('kind')
        if k not in outward.KINDS:
            err(p + '.kind', 'one of %s' % (outward.KINDS,))
        elif k in claimed:
            err(p + '.kind', 'listed twice: one entry per kind, with its total count')
        if not _is_int(o.get('count')) or o['count'] < 1:
            err(p + '.count', 'a whole number, at least 1')
        elif k in outward.KINDS:
            claimed.setdefault(k, o['count'])
        if 'scratch' in o:
            sv = o['scratch']
            if k != 'delete':
                err(p + '.scratch', 'only a delete entry has scratch (deletes under /tmp/ or $TMPDIR, counted in count)')
            elif not _is_int(sv) or sv < 0 or (_is_int(o.get('count')) and sv > o['count']):
                err(p + '.scratch', 'a whole number from 0 to count: the deletes whose every target is under /tmp/ or $TMPDIR')
            else:
                scratch_claimed = sv
        ths = o.get('themes')
        if not isinstance(ths, list) or not ths:
            err(p + '.themes', 'required list of theme ids')
        else:
            for t in ths:
                if not isinstance(t, str) or t not in ids:
                    err(p + '.themes', 'no theme with id %r' % (t,))
                elif t not in outward_events:
                    err(p + '.themes', 'theme %r has no event of kind outward' % t)
        ev = o.get('evidence')
        if not isinstance(ev, list) or not ev:
            err(p + '.evidence', 'required list with at least one source')
            continue
        for j, x in enumerate(ev):
            xp = '%s.evidence[%d]' % (p, j)
            if grd.source(x, xp, EVIDENCE_SOURCES) == 'tool_call' and k in outward.KINDS and isinstance(x.get('command'), str) \
                    and k not in outward.kinds(x['command']):
                err(xp + '.command', 'this command is not a %s action' % k)
    stats['outward'] = dict(claimed)

    # ---- the session itself
    sc = None
    if tpath:
        sc = session.scan(tpath)
        for w in sc.warnings:
            warns.append(w)
        have = sc.counts()
        for k in outward.KINDS:
            if k in claimed and claimed[k] != have[k]:
                err('outward', '%s: the doc says %d, the transcript shows %d successful call(s)' % (k, claimed[k], have[k]))
            elif k not in claimed and have[k]:
                err('outward', '%s: %d successful call(s) in the transcript but the doc does not list them' % (k, have[k]))
        if 'delete' in claimed and scratch_claimed != sc.scratch():
            err('outward', 'delete: the doc says scratch %d, the transcript shows %d delete(s) whose every target is under /tmp/ or $TMPDIR' % (scratch_claimed, sc.scratch()))
        turns = len(sc.users)
        wanted = [q for _, _, qs in order_checks for q in qs]
        where = session.quote_turns(tpath, wanted) if wanted else {}
        for ep, o, qs in order_checks:
            if o > turns:
                err(ep + '.order', 'the session has %d user turns; u%d does not exist' % (turns, o))
            for q in qs:
                if where.get(q) and o not in where[q]:
                    err(ep + '.order', 'the user quote sits in turn(s) %s, not u%d' % (', '.join('u%d' % n for n in where[q][:5]), o))

    # ---- a credential never reaches the doc, the page or this report
    ground.sweep(doc, err)

    grd.resolve(warns)
    if tpath:
        for path, qs, by_hand in done_runs:
            if not by_hand and ground.only_errors(qs):
                err(path + '.kind', '"done" rests on tool calls whose result is an error (is_error); an errored run cannot back a done (use blocked, or redirected)')
    stats['verified_in_transcript'] = sum(1 for q, _ in queries if q.found)
    stats['reported'] = grd.reported
    stats['inferred'] = len(inferred)
    stats['not_compared'] = len(not_compared)
    return errs, stats


def _change_doc(cd, path, base_dir, err):
    if not nonempty(cd) or cd.startswith(('/', '~')) or '\\' in cd or '..' in cd.split('/') or not cd.endswith('.json'):
        err(path, 'a relative path to an explain-change/2 .json file, inside the folder of this doc')
        return
    if base_dir is None:
        return
    full = os.path.join(base_dir, cd)
    try:
        with open(full, encoding='utf-8') as fh:
            schema = json.load(fh).get('schema')
    except (OSError, ValueError, AttributeError):
        err(path, 'cannot read %s as an explain-change/2 doc' % cd)
        return
    if schema != 'explain-change/2':
        err(path, '%s is not an explain-change/2 doc' % cd)
