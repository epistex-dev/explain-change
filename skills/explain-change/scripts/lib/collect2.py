"""Schema v2 additions to collect.py: module mapping and transcript candidates/digest, as printable text."""
import os

from . import arch as archmod
from . import transcript

MAX_UNCHANGED = 60


def load_arch(repo):
    p = archmod.find_architecture(repo)
    return archmod.Architecture(p) if p else None


def module_report(repo, files):
    a = load_arch(repo)
    rep = archmod.map_files(repo, files, a)
    rep['status'] = {f['path']: f for f in files}
    return a, rep


def format_modules(repo, a, rep):
    if a:
        out = ['## Modules (source A: %s)' % a.path,
               'Globs are read from %s; a file goes to the deepest matching node, then the longer literal prefix, then the node declared first.' % a.root]
    else:
        root = rep.get('root') or ''
        out = ['## Modules (source B: no floorplan/architecture.json at %s or %d parents)' % (repo, archmod.MAX_PARENTS),
               'Module ids are directories relative to %s ("." = files directly there). The rule: one module per child directory; a directory with over 60%% of the files is split by its children, until 3 to 8 modules result. Use these ids and no others.'
               % (('%s/' % root) if root else 'the repo root'),
               'Files outside the change you explain are not on the map: limit the run with --path (rerun collect.py) instead of an "_other" module.']
    status = rep['status']
    for mid, paths in sorted(rep['groups'].items()):
        node = a.nodes.get(mid) if a else None
        if mid == archmod.OTHER:
            head = '%s  (files the architecture does not claim)' % mid
        elif node:
            head = '%s  %s [%s] - %s' % (mid, node.get('label', ''), node.get('kind', ''), node.get('summary', ''))
        else:
            head = '%s  (%s)' % (mid, 'files directly in the root' if mid == '.' else 'directory')
        out.append('  ' + head)
        for p in paths:
            f = status[p]
            out.append('      %s %s %s' % (f['status'], 'binary' if f['binary'] else '+%d -%d' % (f['add'], f['del']), p))
    if rep['unassigned']:
        out.append('Unassigned (module id "%s"): %s' % (archmod.OTHER, ', '.join(rep['unassigned'])))
    if rep['ignored']:
        out.append('Left off the board by the architecture "ignore" list: %s' % ', '.join(rep['ignored']))
    for o in rep['overlaps']:
        out.append('OVERLAP: %s matches %s equally; first declared wins -> %s' % (o['path'], ', '.join(o['tied']), o['winner']))
    if a:
        changed = set(rep['groups'])
        rest = [n for n in a.order if n not in changed]
        out += ['', 'Other architecture modules you may list as unchanged neighbours (id  label): %d, none of them touched' % len(rest)]
        out += ['  %s  %s' % (n, a.nodes[n].get('label', '')) for n in rest[:MAX_UNCHANGED]]
        if len(rest) > MAX_UNCHANGED:
            out.append('  ... %d more in %s' % (len(rest) - MAX_UNCHANGED, a.path))
        out.append('map.hidden_count for a map that draws N modules (changed + unchanged, not outside actors): %d minus N' % len(a.order))
    return '\n'.join(out)


def format_candidates(repo, cands, others=()):
    out = ['## Transcript candidates (most recently modified first; pass the right one as --transcript <path>)']
    if not cands:
        out.append('  none found under ~/.claude/projects for %s or its parents' % repo)
        if not others:
            out.append('  No transcript to read: write "transcript_unavailable": "<why>" in the doc and take the words and commands from your own context (SKILL.md, step 2)')
    for c in cands:
        transcript.learn(c['path'])  # the bare value, not only a labelled one, is hidden in every line below
    for i, c in enumerate(cands, 1):
        first = transcript.redact((c['first_user'] or '(no user message)').replace('\n', ' '))  # the first message may hold a credential
        out.append('  %d. %s' % (i, c['path']))
        out.append('     %s .. %s   %d KB, %d worker transcripts' % (c['start'] or '?', c['end'] or '?', c['size'] // 1024, c['subagents']))
        out.append('     first user message: %s' % (first[:140] + ('…' if len(first) > 140 else '')))
    for name, found in others:
        for c in found:
            transcript.learn(c['np'])
        out += ['', '## %s sessions recorded in %s (most recent first; pass the right one as --transcript <reference>)' % (name, repo)]
        for i, c in enumerate(found, 1):
            first = transcript.redact((c['first_user'] or '(no user message)').replace('\n', ' '))
            out.append('  %d. [%s] %s' % (i, name, c['path']))
            out.append('     %s .. %s   %d events, %d sub-agent sessions' % (c['start'] or '?', c['end'] or '?', c['events'], c['subagents']))
            out.append('     first user message: %s' % (first[:140] + ('…' if len(first) > 140 else '')))
    return '\n'.join(out)
