"""Module map sources for schema v2.

Source A: floorplan/architecture.json (found from the repo root and up to 2 parents). Files are assigned to nodes with
floorplan's rules (floorplan 0.6.1 references/schema.md "How files get assigned"; re-implemented, no plugin code):
  1. nodes whose `paths` match and whose own or inherited `exclude` does not;
  2. the deepest node wins;
  3. same depth: the glob with the longer literal prefix wins;
  4. a real tie: the node declared first wins (reported in `overlaps`).
  Top-level `ignore` globs leave a file off the board (no node).
Source B (no architecture.json): `fallback_modules` below. The same function serves collect.py and the validator, so the ids match.
"""
import json
import os
import re

MAX_PARENTS = 2
OTHER = '_other'  # reserved module id for changed files the architecture does not claim


class ArchError(Exception):
    pass


def _seg_is_literal_bracket(seg):
    return len(seg) > 2 and seg.startswith('[') and seg.endswith(']')


def _seg_regex(seg):
    """One path segment without `**`: `*` stays inside the segment, `?` is one char, `{a,b}` alternation."""
    if _seg_is_literal_bracket(seg):
        return re.escape(seg)
    out, i = [], 0
    while i < len(seg):
        c = seg[i]
        if c == '*':
            out.append('[^/]*')
        elif c == '?':
            out.append('[^/]')
        elif c == '{' and '}' in seg[i:]:
            j = seg.index('}', i)
            out.append('(?:' + '|'.join(_seg_regex(a) for a in seg[i + 1:j].split(',')) + ')')
            i = j
        elif c == '[' and ']' in seg[i:]:
            j = seg.index(']', i)
            out.append('[' + seg[i + 1:j].replace('\\', '\\\\') + ']')
            i = j
        else:
            out.append(re.escape(c))
        i += 1
    return ''.join(out)


def glob_regex(pattern):
    """Compiled regex for a floorplan glob. A pattern with no wildcard also matches as a directory."""
    pattern = pattern.strip('/')
    if not re.search(r'[*?{\[]', pattern):
        pattern += '/**'
        exact = re.escape(pattern[:-3])
    else:
        exact = None
    segs = pattern.split('/')
    parts = []
    for k, s in enumerate(segs):
        last = k == len(segs) - 1
        if s == '**':
            parts.append('.*' if last else '(?:[^/]+/)*')  # trailing `**`: everything below; `**/`: zero or more dirs
            continue
        parts.append(_seg_regex(s) + ('' if last else '/'))
    rx = '(?:%s)' % ''.join(parts)
    if exact:
        rx = '(?:%s|%s)' % (rx, exact)
    return re.compile(rx + r'\Z')


def literal_prefix_len(pattern):
    m = re.search(r'[*?{\[]', pattern)
    return len(pattern if not m else pattern[:m.start()])


def find_architecture(repo):
    """Path of floorplan/architecture.json at the repo root or up to MAX_PARENTS parents, or None."""
    d = os.path.realpath(repo)
    for _ in range(MAX_PARENTS + 1):
        p = os.path.join(d, 'floorplan', 'architecture.json')
        if os.path.isfile(p):
            return p
        up = os.path.dirname(d)
        if up == d:
            break
        d = up
    return None


class Architecture:
    def __init__(self, path):
        self.path = path
        self.root = os.path.dirname(os.path.dirname(path))  # the directory that holds floorplan/
        try:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            raise ArchError('cannot read %s: %s' % (path, e))
        nodes = data.get('nodes') if isinstance(data, dict) else None
        if not isinstance(nodes, list):
            raise ArchError('%s: "nodes" must be a list' % path)
        self.nodes, self.order = {}, []
        for n in nodes:
            if isinstance(n, dict) and isinstance(n.get('id'), str) and n['id'] not in self.nodes:
                self._check_node(n)
                self.nodes[n['id']] = n
                self.order.append(n['id'])
        raw_edges = data.get('edges')
        if raw_edges is not None and not isinstance(raw_edges, list):
            raise ArchError('%s: "edges" must be a list' % path)
        self.edges = [e for e in (raw_edges or []) if isinstance(e, dict)]
        for e in self.edges:
            if not (isinstance(e.get('from'), str) and isinstance(e.get('to'), str)) or not isinstance(e.get('label') or '', str):
                raise ArchError('%s: an edge needs string "from" and "to" (and a string "label"): %r' % (path, e))
        ignore = data.get('ignore')
        if ignore is not None and not isinstance(ignore, list):
            raise ArchError('%s: "ignore" must be a list of globs' % path)
        self.ignore = [g for g in (ignore or []) if isinstance(g, str)]
        self._rx = {}
        self._ignore_rx = [self._compiled(g) for g in self.ignore]
        for n in self.nodes.values():  # a bad glob is an ArchError now, not a re.error in the middle of a validation
            for g in self._globs(n, 'paths') + self._globs(n, 'exclude'):
                self._compiled(g)

    def _check_node(self, n):
        for f in ('parent', 'kind', 'label', 'summary'):
            if n.get(f) is not None and not isinstance(n[f], str):
                raise ArchError('%s: node %r: "%s" must be a string, got %s' % (self.path, n['id'], f, type(n[f]).__name__))
        for f in ('paths', 'exclude'):
            v = n.get(f)
            if v is not None and (not isinstance(v, list) or not all(isinstance(g, str) for g in v)):
                raise ArchError('%s: node %r: "%s" must be a list of glob strings' % (self.path, n['id'], f))

    @staticmethod
    def _globs(n, key):
        return [g for g in (n.get(key) or []) if isinstance(g, str)]

    # tree
    def parent(self, nid):
        p = self.nodes[nid].get('parent')
        return p if p in self.nodes else None

    def depth(self, nid):
        d, seen = 0, {nid}
        while (nid := self.parent(nid)) is not None and nid not in seen:
            seen.add(nid)
            d += 1
        return d

    def holders(self, ids):
        """The nodes that are an ancestor of one of `ids`: groups the page draws as the frame of those modules."""
        out = set()
        for nid in ids:
            if nid not in self.nodes:
                continue
            seen = {nid}
            while (p := self.parent(nid)) is not None and p not in seen:
                seen.add(p)
                out.add(p)
                nid = p
        return out

    def top_label(self, nid):
        seen = {nid}
        while (p := self.parent(nid)) is not None and p not in seen:
            seen.add(p)
            nid = p
        return self.nodes[nid].get('label') or nid

    def _excludes(self, nid):
        out, seen = [], set()
        while nid is not None and nid not in seen:
            seen.add(nid)
            out += [g for g in (self.nodes[nid].get('exclude') or []) if isinstance(g, str)]
            nid = self.parent(nid)
        return out

    def _compiled(self, glob):
        if glob not in self._rx:
            try:
                self._rx[glob] = glob_regex(glob)
            except (re.error, RecursionError, OverflowError) as e:
                raise ArchError('%s: bad glob %r: %s' % (self.path, glob, e))
        return self._rx[glob]

    # file -> node
    def relpath(self, repo, path):
        """Path of a repo file relative to the architecture root (globs are written from the root)."""
        rel = os.path.relpath(os.path.realpath(repo), self.root)
        return path if rel in ('.', '') else '%s/%s' % (rel.replace(os.sep, '/'), path)

    def assign(self, path):
        """(node id or None, info). `path` is relative to the architecture root. info: {ignored, candidates, tie}."""
        info = {'ignored': False, 'candidates': [], 'tie': None}
        if any(rx.match(path) for rx in self._ignore_rx):
            info['ignored'] = True
            return None, info
        cands = []  # (depth, prefix_len, -order, id)
        for k, nid in enumerate(self.order):
            n = self.nodes[nid]
            globs = [g for g in (n.get('paths') or []) if isinstance(g, str)]
            hit = [g for g in globs if self._compiled(g).match(path)]
            if not hit:
                continue
            if any(self._compiled(g).match(path) for g in self._excludes(nid)):
                continue
            cands.append((self.depth(nid), max(literal_prefix_len(g) for g in hit), -k, nid))
        if not cands:
            return None, info
        cands.sort(reverse=True)
        info['candidates'] = [c[3] for c in cands]
        if len(cands) > 1 and cands[0][:2] == cands[1][:2]:
            tied = [c[3] for c in cands if c[:2] == cands[0][:2]]
            info['tie'] = tied  # tied[0] won because it is declared first
        return cands[0][3], info


FALLBACK_MIN, FALLBACK_MAX, FALLBACK_BIG = 3, 8, 0.6  # modules wanted; a module holding more than this share of the files is split


def fallback_root(paths):
    """The deepest directory that holds every changed file ('' for the repo root). Fallback ids are relative to it."""
    dirs = [p.split('/')[:-1] for p in paths]
    root = dirs[0] if dirs else []
    for d in dirs[1:]:
        k = 0
        while k < min(len(root), len(d)) and root[k] == d[k]:
            k += 1
        root = root[:k]
    return '/'.join(root)


def fallback_modules(paths):
    """Module of each changed file when there is no architecture: {path: id}. The rule, deterministic and free of any other input:
    take the deepest common directory of the files (the root); one module per child directory below it (the first path segment
    under the root; files directly in the root are module "."); a module that would hold more than 60% of the files is split
    by its own child directories (files directly in it stay as the module itself) until 3 to 8 modules result, or nothing can be
    split. A split-off single file joins the nearest module above it. More than 8 modules: the smallest merge into the nearest
    module above them ("." when none). Ids are paths relative to the root."""
    paths = sorted(set(paths))
    if not paths:
        return {}
    root = fallback_root(paths)
    n_root = len(root.split('/')) if root else 0
    segs = {p: tuple(p.split('/')[n_root:]) for p in paths}
    mods = {}  # key (tuple of path segments, () = the root) -> [path]
    for p in paths:
        mods.setdefault(() if len(segs[p]) == 1 else segs[p][:1], []).append(p)
    total = len(paths)

    def above(key):  # nearest existing module that is a proper ancestor of key
        for i in range(len(key) - 1, 0, -1):
            if key[:i] in mods:
                return key[:i]
        return ()

    def splittable(key):
        return bool(key) and any(len(segs[p]) > len(key) + 1 for p in mods[key])

    def split(key):
        files = mods.pop(key)
        for p in files:
            s = segs[p]
            mods.setdefault(key if len(s) == len(key) + 1 else key + (s[len(key)],), []).append(p)
        if len(mods.get(key, [])) == 1:  # a lone file left behind: it joins the module above
            mods.setdefault(above(key), []).extend(mods.pop(key))

    while True:
        cands = [k for k in mods if splittable(k)]
        big = [k for k in cands if len(mods[k]) > FALLBACK_BIG * total]
        pick = big or (cands if len(mods) < FALLBACK_MIN else [])
        if not pick:
            break
        split(max(pick, key=lambda k: (len(mods[k]), k)))
    while len(mods) > FALLBACK_MAX:
        small = min((k for k in mods if k), key=lambda k: (len(mods[k]), k))
        mods.setdefault(above(small), []).extend(mods.pop(small))
    return {p: '/'.join(k) or '.' for k, ps in mods.items() for p in ps}


def top_dir(path):
    """The legacy no-architecture module of a file: its first path segment ('.' for a file at the repo root). Docs written before
    `fallback_modules` use it; it is accepted only for them (see `accept_legacy`)."""
    return path.split('/', 1)[0] if '/' in path else '.'


def accept_legacy(mapping, doc_modules):
    """Without an architecture, a v2 doc built on the legacy rule (one module per top directory of the repo) still validates.
    Returns `mapping` itself, or a copy that uses the legacy rule when the doc fits it and does not fit the current rule.
    The doc fits a rule when every file it lists sits in the module that rule gives it, every changed module id is one the rule
    produces, and (legacy only) every module id is a single top-level directory name or "."; a doc that follows one rule for
    some modules and the other for the rest fits neither, so it is judged by the current rule and fails. One function for the
    validator and the renderer (render.py validates first), so they agree."""
    if mapping.get('mode') != 'dirs' or not isinstance(doc_modules, list):
        return mapping
    mods = [m for m in doc_modules if isinstance(m, dict) and isinstance(m.get('id'), str) and m.get('outside') is not True]
    claimed = {}
    for m in mods:
        for f in m.get('files') if isinstance(m.get('files'), list) else []:
            if isinstance(f, dict) and isinstance(f.get('path'), str):
                claimed[f['path']] = m['id']
    changed = {m['id'] for m in mods if m.get('changed') is True}

    def fits(assigned, ids=()):
        return (bool(changed) and changed <= set(assigned.values()) and all(assigned.get(p) == mid for p, mid in claimed.items())
                and all(i == '.' or '/' not in i for i in ids))
    if fits(mapping['assigned']):
        return mapping
    legacy = {p: top_dir(p) for p in mapping['assigned']}
    if not fits(legacy, [m['id'] for m in mods]):
        return mapping
    groups = {}
    for p, mid in legacy.items():
        groups.setdefault(mid, []).append(p)
    return dict(mapping, assigned=legacy, groups=groups, root='', rule='legacy')


def map_files(repo, files, arch=None):
    """Assign changed files to modules. files: list of changed_files() dicts.
    Returns {mode, architecture, root (dirs mode: ids are relative to it), assigned: {path: module id}, groups: {module id: [path]}, unassigned: [path],
             overlaps: [{path, winner, tied}], ignored: [path]}."""
    res = {'mode': 'floorplan' if arch else 'dirs', 'architecture': arch.path if arch else None, 'assigned': {},
           'groups': {}, 'unassigned': [], 'overlaps': [], 'ignored': []}
    dirs = None if arch else fallback_modules([f['path'] for f in files])
    if not arch:
        res['root'] = fallback_root([f['path'] for f in files])
    for f in files:
        p = f['path']
        if arch:
            nid, info = arch.assign(arch.relpath(repo, p))
            if info['ignored']:
                res['ignored'].append(p)
            if info['tie']:
                res['overlaps'].append({'path': p, 'winner': info['tie'][0], 'tied': info['tie']})
            if nid is None:
                res['unassigned'].append(p)
                nid = OTHER
        else:
            nid = dirs[p]
        res['assigned'][p] = nid
        res['groups'].setdefault(nid, []).append(p)
    return res
