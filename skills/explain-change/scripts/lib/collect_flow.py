"""collect.py --flow: what an explain-flow/1 doc needs, with no diff. HEAD, the modules, the files under each --path."""
import json
import os

from . import arch as archmod
from . import collect, collect2, gitio

MAX_FILES = 300


def tracked(repo, commit, scope):
    """Tracked files of `commit` (all, or those under the scope), sorted."""
    out = gitio.git(repo, 'ls-tree', '-r', '-z', '--name-only', commit, *gitio.pathspecs(scope))
    return sorted(p for p in out.decode('utf-8', 'replace').split('\0') if p)


def build(repo, scope):
    """Returns (summary, text). Raises ExplainError when the repo has no commit or a --path matches nothing."""
    if not gitio.has_head(repo):
        raise gitio.ExplainError('the repository has no commit yet: a flow doc is written against a commit')
    commit = gitio.rev_parse(repo, 'HEAD')
    everything = tracked(repo, commit, [])
    under = tracked(repo, commit, scope) if scope else []
    if scope and not under:
        raise gitio.ExplainError('--path %s: no tracked file at HEAD %s' % (', '.join(scope), commit[:12]))
    arch = collect2.load_arch(repo)
    rep = archmod.map_files(repo, [{'path': p} for p in everything], arch)
    mods = {k: len(v) for k, v in sorted(rep['groups'].items())}
    summary = {'mode': 'flow', 'commit': commit, 'scope': scope, 'modules': mods, 'files': under}
    out = ['## explain-flow (no diff)',
           'HEAD=%s' % commit,
           'Write the doc against this commit: its "commit" field is this full SHA, and every source is read from it, not from the working copy.']
    if gitio.is_dirty(repo):
        out.append('warning: the working copy has uncommitted changes; the doc describes the code at HEAD, not those edits')
    if arch:
        out += ['', '## Modules (source A: %s)' % arch.path]
        for mid in sorted(mods):
            node = arch.nodes.get(mid)
            if node:
                out.append('  %s  %s [%s] - %s  (%d files)' % (mid, node.get('label', ''), node.get('kind', ''), node.get('summary', ''), mods[mid]))
            else:
                out.append('  %s  (files the architecture does not claim)  (%d files)' % (mid, mods[mid]))
    else:
        root = rep.get('root') or ''
        out += ['', '## Modules (source B: no floorplan/architecture.json; one per directory under %s)' % (('%s/' % root) if root else 'the repo root')]
        out += ['  %s  (%d files)' % (mid, n) for mid, n in sorted(mods.items())]
    if scope:
        out += ['', '## Files under %s (%d)' % (', '.join(scope), len(under))]
        out += ['  %s  [%s]' % (p, rep['assigned'].get(p, '?')) for p in under[:MAX_FILES]]
        if len(under) > MAX_FILES:
            out.append('  ... %d more' % (len(under) - MAX_FILES))
    else:
        out += ['', 'No --path given, so the %d tracked files are not listed. Rerun with --path <dir or file> to list the files of the flow.' % len(everything)]
    return summary, '\n'.join(out)


def run(repo, scope, slug):
    summary, text = build(repo, scope)
    collect.ensure_excluded(repo)
    name = slug if slug and slug.strip() else ('flow-' + os.path.basename(scope[0]) if scope else 'flow')
    run_dir = collect.new_run_dir(repo, collect.slugify(name))
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print(text)
    print('\nRUN_DIR=%s' % run_dir)
    return 0
