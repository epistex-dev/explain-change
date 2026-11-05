"""Build the diff summary the agent works from, and create the run directory."""
import datetime
import os
import re
import unicodedata

from . import funcs, gitio

HUGE_DIFF_LINES = 5000
MAX_LISTED = 400


def slugify(text, limit=40):
    t = unicodedata.normalize('NFKD', text.replace('đ', 'd').replace('Đ', 'D'))
    t = ''.join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')[:limit].strip('-') or 'change'


def ensure_excluded(repo):
    """Add `.explain/` to the repo's info/exclude (once). Returns True when the line was added."""
    path = gitio.git(repo, 'rev-parse', '--git-path', 'info/exclude').decode().strip()
    if not os.path.isabs(path):
        path = os.path.join(repo, path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existing = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
    if '.explain/' in existing.split('\n'):
        return False
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(('' if existing.endswith('\n') or not existing else '\n') + '.explain/\n')
    return True


def subject_of(message):
    return message.split('\n')[0].strip()


def pick_slug(messages, fallback='worktree'):
    """Run folder name from the commits of the range that touch the scope: their most common subject, the newest on a tie."""
    subjects = [subject_of(m['message']) for m in messages if subject_of(m['message'])]
    if not subjects:
        return fallback
    return max(subjects, key=lambda s: (subjects.count(s), -subjects.index(s)))  # messages are newest first


def build_summary(repo, rng, scope=None):
    scope = scope or []
    spec = gitio.pathspecs(scope)
    files = gitio.changed_files(repo, rng['base'], rng['head'], scope)
    patch = gitio.git(repo, 'diff', '--no-color', '-M', rng['base'], rng['head'], *spec)
    patch_lines = patch.count(b'\n')
    messages = []
    if rng['mode'] in ('commit', 'range'):
        rl = rng['base'] if rng['base'] != gitio.EMPTY_TREE else None
        spec_ = '%s..%s' % (rl, rng['head']) if rl else rng['head']
        out = gitio.git(repo, 'log', '--format=%h%x00%B%x01', '-n', '20', spec_, *spec).decode('utf-8', 'replace')
        for rec in out.split('\x01'):
            rec = rec.strip('\n')
            if rec:
                sha, _, body = rec.partition('\x00')
                messages.append({'sha': sha.strip(), 'message': body.strip()})
    return {
        'schema': 'explain-change/summary@1', 'repo': repo, 'range': rng, **({'scope': scope} if scope else {}), 'files': files,
        'totals': {'files': len(files), 'add': sum(f['add'] for f in files), 'del': sum(f['del'] for f in files),
                   'binary': sum(1 for f in files if f['binary']), 'patch_lines': patch_lines},
        'huge': patch_lines > HUGE_DIFF_LINES,
        'functions': funcs.changed_functions(repo, rng['base'], rng['head'], files),
        'messages': messages,
    }, patch


def new_run_dir(repo, slug, now=None):
    now = now or datetime.datetime.now()
    root = os.path.join(repo, '.explain')
    stem = '%s-%s' % (now.strftime('%Y%m%d-%H%M'), slug)
    d, n = os.path.join(root, stem), 1
    while os.path.exists(d):
        n += 1
        d = os.path.join(root, '%s-%d' % (stem, n))
    os.makedirs(d)
    return d


def format_text(s, run_dir, v2=False):
    """v2 leaves out what only the v1 report page uses (the 'explain in "Logic bên trong"' hints, sub-change advice)."""
    r = s['range']
    t = s['totals']
    out = ['# Diff summary: %s' % r['label'],
           'mode: %s   base: %s   head: %s' % (r['mode'], r['base'][:12], r['head'][:12]),
           'files: %d   +%d -%d   binary: %d   patch lines: %d' % (t['files'], t['add'], t['del'], t['binary'], t['patch_lines']),
           'run dir: %s' % run_dir, 'full patch: %s' % os.path.join(run_dir, 'diff.patch'),
           'read a file at head: git -C %s show %s:<path>   at base: git -C %s show %s:<path>' % (
               s['repo'], r['head'][:12], s['repo'], r['base'][:12])]
    if s.get('scope'):
        out.append('scope: %s  (only these paths are in the diff, the map and the validator)' % ', '.join(s['scope']))
    if s['huge']:
        out.append('NOTE: huge diff (>%d patch lines). Group files by %s; read the patch '
                   'per file with `git diff base head -- <path>`, not whole.' % (HUGE_DIFF_LINES, 'module' if v2 else 'directory into sub-changes'))
    for m in s['messages']:
        out += ['', 'commit %s:' % m['sha']] + ['  ' + ln for ln in m['message'].split('\n')]
    out += ['', '## Files (status, +add -del, path)']
    for f in s['files'][:MAX_LISTED]:
        c = 'binary' if f['binary'] else '+%d -%d' % (f['add'], f['del'])
        p = f['path'] if not f['old_path'] else '%s <- %s' % (f['path'], f['old_path'])
        out.append('%s  %-10s %s' % (f['status'], c, p))
    if len(s['files']) > MAX_LISTED:
        out.append('... %d more files in summary.json' % (len(s['files']) - MAX_LISTED))
    out += ['', '## Changed functions (heuristic; branches = control-flow tokens in the body)']
    shown = [f for f in s['functions'] if f['branches'] > 0] if s['huge'] else s['functions']
    for f in shown[:MAX_LISTED]:
        out.append('%s:%d  %s  branches=%d%s' % (f['file'], f['line'], f['name'], f['branches'],
                                                  '  <- explain in "Logic bên trong"' if f['branches'] >= 2 and not f['test'] and not v2 else ('  (test)' if f['test'] else '')))
    if not s['functions']:
        out.append('(none detected)')
    return '\n'.join(out)
