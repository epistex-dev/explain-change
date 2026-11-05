"""Grounding shared by every doc kind (explain-change/2 in check2, explain-session/1 in check_session): a Source object becomes a
transcript Query, the queries are resolved in one streaming pass per file, and a credential never survives in a doc.
Nothing here knows a schema; the caller says which source kinds a field accepts."""
import re

from . import transcript

QUOTE_ROLES = ('user', 'assistant', 'tool_result', 'report')
URL_ROLES = QUOTE_ROLES


def as_list(v):
    return v if isinstance(v, list) else []


def nonempty(v):
    return isinstance(v, str) and bool(v.strip())


class Grounder:
    """err(path, msg) reports a problem. tpath/tfiles: the main transcript and {id: file} of its session (None: no transcript, the quotes
    are only listed in `not_compared`). on_inferred(path) is called for each `{"inferred": true}` source."""

    def __init__(self, err, tpath=None, tfiles=None, not_compared=None, on_inferred=None):
        self.err, self.tpath, self.tfiles = err, tpath, tfiles or {}
        self.queries = []  # (transcript.Query, path)
        self.not_compared = [] if not_compared is None else not_compared
        self.on_inferred = on_inferred or (lambda path: None)
        self.reported = 0

    def query(self, q, path):
        self.queries.append((q, path))
        return q

    def tid_of(self, src, path):
        t = src.get('transcript', 'main')
        if not isinstance(t, str) or not (t == 'main' or transcript.AGENT_ID.match(t)):
            self.err(path + '.transcript', '"main" or an agent id like "agent-a1b2c3"')
            return None
        if self.tpath and t not in self.tfiles:
            self.err(path + '.transcript', 'unknown transcript %r; this session has: %s' % (t, ', '.join(self.tfiles)))
            return None
        return t

    def text(self, obj, field, path):
        v = obj.get(field) if isinstance(obj, dict) else None
        if not isinstance(v, str) or not v.strip():
            self.err('%s.%s' % (path, field), 'required non-empty string')
            return None
        return v

    def source(self, src, path, allow, sink=None, code=None):
        """Validate one Source object; returns its kind, or None when invalid. code(src, path) checks a `code` source."""
        err = self.err
        if not isinstance(src, dict):
            err(path, 'source must be an object {kind, ...}')
            return None
        kind = 'inferred' if src.get('inferred') is True and 'kind' not in src else src.get('kind')
        if kind not in allow:
            err(path + '.kind', 'one of %s here' % (allow,))
            return None
        if kind == 'inferred':
            self.on_inferred(path)
        elif kind == 'code':
            code(src, path)
        elif kind in ('transcript', 'user_reported', 'report'):
            q = self.text(src, 'quote', path)
            if kind == 'report':
                self.reported += 1
            if q and self.tpath:
                tid = 'main' if kind == 'user_reported' else self.tid_of(src, path)
                if tid:
                    roles = {'user_reported': ('user',), 'report': ('report', 'assistant')}.get(kind, QUOTE_ROLES)
                    self.query(transcript.Query('quote', tid, roles, text=q), path + '.quote')
            elif q:
                self.not_compared.append(path)
            if sink is not None and q:
                sink.append(q)
        elif kind == 'url':
            u = src.get('url')
            if not isinstance(u, str) or not re.match(r'https?://[^\s]+\Z', u):
                err(path + '.url', 'needs an http(s) URL')
            elif self.tpath:
                self.query(transcript.Query('url', 'main', URL_ROLES, text=u), path + '.url')
            else:
                self.not_compared.append(path)
        elif kind == 'tool_call':
            c, x = self.text(src, 'command', path), self.text(src, 'excerpt', path)
            if c and x and self.tpath:
                tid = self.tid_of(src, path)
                if tid:
                    self.query(transcript.Query('tool', tid, command=c, excerpt=x), path)
            elif c and x:
                self.not_compared.append(path)
            if sink is not None and x:
                sink.append(x)
        return kind

    def resolve(self, warns):
        """One streaming pass per transcript file; an error for each query that found nothing."""
        err = self.err
        if not (self.tpath and self.queries):
            return
        tstats = transcript.resolve_queries(self.tpath, [q for q, _ in self.queries])
        for tid, st in tstats.items():
            w = st.warning('transcript %s' % tid)
            if w:
                warns.append(w)
        for q, path in self.queries:
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


def only_errors(tool_queries):
    """True when every tool call that matched a source ran with an error result: an errored run cannot back a pass or a done."""
    return bool(tool_queries) and all(q.found and not q.found_ok for q in tool_queries)


def sweep(node, err, path='', is_snippet=None, in_snippet=False):
    """Report each string, and each key, that holds a credential: one learned from the session (transcript.learn) or one that looks like
    one by its label. is_snippet(path, key) is True for a code line quoted from the diff, where only a learned credential counts."""
    if isinstance(node, str):
        if transcript.contains_learned(node):
            err(path, 'contains a password, token or key that the session shows; the page would show it. Leave the secret out')
        elif not in_snippet and transcript.has_secret(node):
            err(path, 'contains what looks like a password, token or key; the page would show it. Quote another part of the message and leave the secret out')
    elif isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and transcript.contains_learned(k):
                err(path, 'a key contains a password, token or key that the session shows')
            sweep(v, err, '%s.%s' % (path, k) if path else str(k), is_snippet, bool(is_snippet and is_snippet(path, k)))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            sweep(v, err, '%s[%d]' % (path, i), is_snippet, in_snippet)
