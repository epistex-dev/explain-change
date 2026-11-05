"""Per-harness transcript adapters. Each adapter module offers

    detect(path) -> bool
    default_root() -> path of the harness's official transcript directory
    find_sessions(cwd, root=None) -> list of transcript references recorded in cwd (a file path; the databases of OpenCode
        and Cursor IDE hold many sessions, so their references are `<database path>#<session id>`)
    read(path, root=None) -> model.Session

and reads only under the harness's root (after resolving symlinks): a transcript elsewhere raises
_io.RootError (a store that is corrupt, locked or in another format raises _io.StoreError), so an agent cannot ground a claim in a file it wrote itself. The root is a function
argument for tests; there is no environment variable or flag that moves it.
"""
from . import codex, copilot, cursor_cli, cursor_ide, gemini, opencode
from ._io import RootError, StoreError  # noqa: F401
from .model import Event, Session, Tool  # noqa: F401

# The two SQLite stores come first: detecting a database costs one page read, while the JSON-lines adapters read a file
# line by line until they find a record, which for a database of hundreds of megabytes is the whole file.
ADAPTERS = {cursor_ide.HARNESS: cursor_ide, opencode.HARNESS: opencode, copilot.HARNESS: copilot, codex.HARNESS: codex, gemini.HARNESS: gemini,
            cursor_cli.HARNESS: cursor_cli}


def get(name):
    """The adapter module for a harness name, or None."""
    return ADAPTERS.get(name)


def detect_format(path):
    """The name of the first adapter that recognises the file, or None."""
    for name, mod in ADAPTERS.items():
        if mod.detect(path):
            return name
    return None
