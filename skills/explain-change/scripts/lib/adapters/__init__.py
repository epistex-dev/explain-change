"""Per-harness transcript adapters. Each adapter module offers

    detect(path) -> bool
    default_root() -> path of the harness's official transcript directory
    find_sessions(cwd, root=None) -> list of transcript paths recorded in cwd
    read(path, root=None) -> model.Session

and reads only under the harness's root (after resolving symlinks): a transcript elsewhere raises
_io.RootError, so an agent cannot ground a claim in a file it wrote itself. The root is a function
argument for tests; there is no environment variable or flag that moves it.
"""
from . import codex, copilot
from ._io import RootError  # noqa: F401
from .model import Event, Session, Tool  # noqa: F401

ADAPTERS = {copilot.HARNESS: copilot, codex.HARNESS: codex}


def get(name):
    """The adapter module for a harness name, or None."""
    return ADAPTERS.get(name)


def detect_format(path):
    """The name of the first adapter that recognises the file, or None."""
    for name, mod in ADAPTERS.items():
        if mod.detect(path):
            return name
    return None
