"""Git access for explain-change: range resolution, diff collection, file versions."""
import os
import re
import subprocess
import tempfile

EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
WORKTREE = 'worktree'


class ExplainError(Exception):
    """User-facing failure: printed as one line, no traceback."""


def git(repo, *args, env=None, check=True):
    p = subprocess.run(['git', '-C', repo, *args], capture_output=True,
                       env={**os.environ, **(env or {})})
    if check and p.returncode != 0:
        raise ExplainError('git %s: %s' % (' '.join(args[:2]), p.stderr.decode('utf-8', 'replace').strip()))
    return p.stdout


def toplevel(path):
    p = subprocess.run(['git', '-C', path, 'rev-parse', '--show-toplevel'], capture_output=True)
    if p.returncode != 0:
        raise ExplainError('not a git repository: %s' % path)
    return p.stdout.decode().strip()


def resolve_rev(repo, rev):
    """Object id (commit, else tree) of a doc-supplied revision, or ExplainError. Never lets `rev` act as a git option:
    a leading '-' is refused and --end-of-options guards the call. Use only the returned id in later git calls."""
    if not isinstance(rev, str) or not rev or rev.startswith('-') or '\0' in rev or '\n' in rev:
        raise ExplainError('not a revision: %r' % (rev,))
    for peel in ('^{commit}', '^{tree}'):
        p = subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', '--end-of-options', rev + peel], capture_output=True)
        if p.returncode == 0:
            return p.stdout.decode().strip()
    raise ExplainError('unknown revision: %s' % rev)


def rev_parse(repo, rev):
    if not isinstance(rev, str) or rev.startswith('-'):
        raise ExplainError('unknown revision: %s' % rev)
    p = subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', '--end-of-options', rev + '^{object}'], capture_output=True)
    if p.returncode != 0:
        raise ExplainError('unknown revision: %s' % rev)
    return p.stdout.decode().strip()


def snapshot_worktree(repo):
    """Tree object of the working tree (tracked + untracked, ignore rules applied), built in a throwaway index."""
    with tempfile.TemporaryDirectory(prefix='explain-index-') as d:
        env = {'GIT_INDEX_FILE': os.path.join(d, 'index')}
        git(repo, 'read-tree', 'HEAD', env=env)
        git(repo, 'add', '-A', '--', '.', env=env)
        return git(repo, 'write-tree', env=env).decode().strip()


def has_head(repo):
    return subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', 'HEAD'], capture_output=True).returncode == 0


def is_dirty(repo):
    return bool(git(repo, 'status', '--porcelain', '--untracked-files=all').strip())


def resolve_range(repo, arg=None):
    """Return dict(mode, base, head, label). base/head are object ids usable with `git show <id>:path`."""
    if not has_head(repo):
        raise ExplainError('repository has no commits yet')
    if not arg:
        if is_dirty(repo):
            return {'mode': WORKTREE, 'base': rev_parse(repo, 'HEAD'), 'head': snapshot_worktree(repo),
                    'label': 'uncommitted changes vs HEAD'}
        arg = 'HEAD'
    m = re.match(r'^(.*?)(\.\.\.?)(.*)$', arg)
    if m:
        a, dots, b = m.group(1) or 'HEAD', m.group(2), m.group(3) or 'HEAD'
        base, head = rev_parse(repo, a), rev_parse(repo, b)
        if dots == '...':
            base = git(repo, 'merge-base', base, head).decode().strip()
        return {'mode': 'range', 'base': base, 'head': head, 'label': arg}
    head = rev_parse(repo, arg)
    parent = subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', head + '^1^{commit}'], capture_output=True)
    base = parent.stdout.decode().strip() if parent.returncode == 0 else EMPTY_TREE
    return {'mode': 'commit', 'base': base, 'head': head, 'label': arg}


def read_version(repo, rev, path):
    """Bytes of path at rev, or None when it does not exist there."""
    if not re.fullmatch(r'[0-9a-f]{40,64}', rev):
        raise ExplainError('read_version needs a resolved object id, got %r' % (rev,))
    p = subprocess.run(['git', '-C', repo, 'cat-file', 'blob', '%s:%s' % (rev, path)], capture_output=True)
    return p.stdout if p.returncode == 0 else None


def decode(b):
    return b.decode('utf-8', 'replace')


def is_binary(b):
    return b'\0' in b[:8000]


def ensure_empty_tree(repo, *revs):
    if EMPTY_TREE in revs:
        subprocess.run(['git', '-C', repo, 'mktree'], input=b'', capture_output=True)


def normalize_scope(repo, paths):
    """Repo-relative, slash-separated form of the --path values, or ExplainError. Refused: a leading '-' (it would read as a git
    option), control characters, '.', and any path that leaves the repo. A relative path is taken from the repo root; an absolute
    one must lie inside it. Nothing here needs the path to exist (a deleted file is a fine scope)."""
    out = []
    root = os.path.realpath(repo)
    for raw in paths or []:
        if not isinstance(raw, str) or not raw.strip() or raw.startswith('-') or any(c in raw for c in '\0\n\r'):
            raise ExplainError('--path %r: a path is a non-empty folder or file of the repo and does not start with "-"' % (raw,))
        p = os.path.relpath(os.path.realpath(raw), root) if os.path.isabs(raw) else os.path.normpath(raw)
        p = p.replace(os.sep, '/')
        if p == '.' or p == '..' or p.startswith('../') or os.path.isabs(p):
            raise ExplainError('--path %r: outside the repo %s (or the whole repo: then leave --path out)' % (raw, repo))
        if p not in out:
            out.append(p)
    return out


def pathspecs(scope):
    """git arguments that limit a command to the scope: `--` first, then each path as a literal (no glob, no magic)."""
    return ['--'] + [':(literal)' + p for p in scope] if scope else []


def changed_files(repo, base, head, scope=None):
    """List of dicts path, old_path, status (A/M/D/R), add, del, binary. Uses -z so any path is safe. `scope`: repo-relative paths
    (from normalize_scope) that limit the diff."""
    ensure_empty_tree(repo, base, head)
    base, head = resolve_rev(repo, base), resolve_rev(repo, head)  # ids only past this line
    spec = pathspecs(scope)
    ns = git(repo, 'diff', '--name-status', '-z', '-M', '--no-color', base, head, *spec).split(b'\0')
    stats = {}
    parts = git(repo, 'diff', '--numstat', '-z', '-M', '--no-color', base, head, *spec).split(b'\0')
    i = 0
    while i < len(parts):
        rec = parts[i]
        i += 1
        if not rec:
            continue
        add, dele, path = rec.decode('utf-8', 'replace').split('\t', 2)
        if path == '':  # rename: next two fields are old and new
            old, new = decode(parts[i]), decode(parts[i + 1])
            i += 2
            path = new
        stats[path] = (add, dele)
    files = []
    i = 0
    while i < len(ns) and ns[i]:
        st = decode(ns[i])
        i += 1
        if st[0] in 'RC':
            old, new = decode(ns[i]), decode(ns[i + 1])
            i += 2
        else:
            old, new = None, decode(ns[i])
            i += 1
        add, dele = stats.get(new, ('0', '0'))
        binary = add == '-'
        files.append({'path': new, 'old_path': old, 'status': 'R' if st[0] == 'R' else st[0][0],
                      'add': 0 if binary else int(add), 'del': 0 if binary else int(dele), 'binary': binary})
    return files
