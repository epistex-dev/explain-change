"""Grounding of claims: a ref is {file, line, snippet} (or inferred=true) and its snippet must occur within
TOLERANCE lines of `line` in the head version (the base version for a deleted file or side="base")."""
import re

from . import gitio

TOLERANCE = 3
MIN_SNIPPET_CHARS = 4


def norm(s):
    return re.sub(r'\s+', ' ', s).strip()


def snippet_error(text_lines, line, snippet):
    """None when `snippet` (one or more lines) occurs with its first line within TOLERANCE of `line`."""
    want = [norm(s) for s in snippet.split('\n') if norm(s)]
    if not want or sum(len(w) for w in want) < MIN_SNIPPET_CHARS:
        return 'snippet too short (need at least %d characters)' % MIN_SNIPPET_CHARS
    if not 1 <= line <= len(text_lines):
        return 'line %d outside file (%d lines)' % (line, len(text_lines))
    norm_lines = [norm(t) for t in text_lines]
    lo, hi = max(1, line - TOLERANCE), min(len(text_lines), line + TOLERANCE)
    for start in range(lo, hi + 1):
        if all(start - 1 + k < len(norm_lines) and w in norm_lines[start - 1 + k] for k, w in enumerate(want)):
            return None
    return 'snippet not found within %d lines of line %d: %r' % (TOLERANCE, line, want[0][:80])


class Verifier:
    def __init__(self, repo, base, head, deleted=()):
        self.repo, self.base, self.head, self.deleted = repo, base, head, set(deleted)
        self.cache = {}

    def lines(self, rev, path):
        key = (rev, path)
        if key not in self.cache:
            b = gitio.read_version(self.repo, rev, path)
            self.cache[key] = None if b is None else (None if gitio.is_binary(b) else gitio.decode(b).split('\n'))
        return self.cache[key]

    def check(self, ref):
        """Return (status, error). status is 'verified' or 'inferred'; error is None when the ref is acceptable."""
        if not isinstance(ref, dict):
            return 'verified', 'ref must be an object {file, line, snippet}'
        path, line = ref.get('file'), ref.get('line')
        if not isinstance(path, str) or not path or isinstance(line, bool) or not isinstance(line, int):
            return 'verified', 'ref needs file (string) and line (integer)'
        side = ref.get('side') or ('base' if path in self.deleted else 'head')
        if side not in ('head', 'base'):
            return 'verified', 'side must be "head" or "base"'
        if ref.get('inferred') is True:
            return 'inferred', None
        snippet = ref.get('snippet')
        if not isinstance(snippet, str):
            return 'verified', 'ref needs snippet (copied from the code) or inferred: true'
        rev = self.base if side == 'base' else self.head
        text = self.lines(rev, path)
        if text is None:
            return 'verified', 'file not found (or binary) in the %s version: %s' % (side, path)
        return 'verified', snippet_error(text, line, snippet)
