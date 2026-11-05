"""Per-harness transcript adapters. Each adapter module offers

    detect(path) -> bool
    default_root() -> path of the harness's official transcript directory
    find_sessions(cwd, root=None) -> list of transcript references recorded in cwd (a file path; OpenCode's database
        holds many sessions, so its reference is `<database path>#<session id>`)
    read(path, root=None) -> model.Session

and reads only under the harness's root (after resolving symlinks): a transcript elsewhere raises
_io.RootError (a store that is corrupt, locked or in another format raises _io.StoreError), so an agent cannot ground a claim in a file it wrote itself. The root is a function
argument for tests; there is no environment variable or flag that moves it.
"""
from . import codex, copilot, gemini, opencode
from ._io import RootError, StoreError  # noqa: F401
from .model import Event, Session, Tool  # noqa: F401

ADAPTERS = {copilot.HARNESS: copilot, codex.HARNESS: codex, opencode.HARNESS: opencode, gemini.HARNESS: gemini}


def get(name):
    """The adapter module for a harness name, or None."""
    return ADAPTERS.get(name)


def detect_format(path):
    """The name of the first adapter that recognises the file, or None."""
    for name, mod in ADAPTERS.items():
        if mod.detect(path):
            return name
    return None
