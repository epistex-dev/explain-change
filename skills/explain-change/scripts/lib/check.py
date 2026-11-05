"""Entry point for validating a change doc. Only schema v2 is supported (references/explain-schema.md)."""
from . import check2, gitio

LEGACY = 'explain-change v1 docs are no longer supported; write version 2 (references/explain-schema.md)'


class LegacyDoc(gitio.ExplainError):
    """The doc is not a schema v2 change doc."""


def require_v2(doc):
    """Raises LegacyDoc for a doc with `version` 1 or none (the callers print it as one line, exit 1)."""
    if not check2.is_v2(doc):
        version = doc.get('version') if isinstance(doc, dict) else None
        raise LegacyDoc(LEGACY if version in (None, 1) else 'unknown version %r; write version 2 (references/explain-schema.md)' % (version,))


def validate(doc, repo, transcript=None, scope=None, fmt='auto'):
    require_v2(doc)
    return check2.validate(doc, repo, transcript, scope, fmt)
