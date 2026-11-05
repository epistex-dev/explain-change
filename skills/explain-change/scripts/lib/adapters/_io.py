"""Shared, hostile-input-safe file access for the adapters."""
import json
import os
import stat

MAX_LINE = 32 * 1024 * 1024      # a line longer than this is skipped, not buffered


class RootError(ValueError):
    """A transcript path outside the harness's root, or not a plain file."""


class StoreError(ValueError):
    """A transcript store (a database or a legacy JSON file) that cannot be read: corrupt, locked, or not the expected format."""


def confine(path, root):
    """The real path of `path`, if it lies under the real path of `root`.

    Symlinks are resolved on both sides first, so a link inside the root that points out of it is refused.
    """
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    if real != real_root and not real.startswith(real_root.rstrip(os.sep) + os.sep):
        raise RootError('transcript is outside the harness root: %s' % path)
    return real


def open_plain(real):
    """Open a resolved path read-only; refuse anything but a regular file (a FIFO would block)."""
    try:
        fd = os.open(real, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except OSError as e:
        raise RootError('cannot open transcript %s: %s' % (real, e.strerror))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RootError('transcript is not a regular file: %s' % real)
        return os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise


def records(real):
    """Yield (line_number, dict) for each JSON object line of a resolved path.

    Reads line by line from a snapshot of the file's size at open time, so a file that keeps growing
    is read up to where it ended when we started. A line that is empty, not JSON, not an object, longer
    than MAX_LINE, or a final line cut short is skipped; invalid UTF-8 is replaced, not fatal.
    """
    with open_plain(real) as fh:
        limit = os.fstat(fh.fileno()).st_size
        used = 0
        n = 0
        while used < limit:
            n += 1
            raw = fh.readline(min(MAX_LINE + 1, limit - used))
            if not raw:
                break
            used += len(raw)
            if not raw.endswith(b'\n') and len(raw) > MAX_LINE:
                while used < limit:                      # drop the rest of the oversized line
                    chunk = fh.readline(min(1 << 20, limit - used))
                    used += len(chunk)
                    if not chunk or chunk.endswith(b'\n'):
                        break
                continue
            if n == 1 and raw.startswith(b'\xef\xbb\xbf'):
                raw = raw[3:]
            text = raw.decode('utf-8', 'replace').strip()
            if not text:
                continue
            try:
                rec = json.loads(text)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield n, rec


def first_record(real):
    """The first JSON object record of a resolved path, or None."""
    for i, rec in records(real):
        return rec
    return None


def s(v):
    """v when it is a string, else None."""
    return v if isinstance(v, str) else None


def d(v):
    """v when it is a dict, else an empty dict, so .get chains never raise on odd shapes."""
    return v if isinstance(v, dict) else {}


def same_dir(a, b):
    """Whether two directory paths name the same place (symlinks resolved, case kept)."""
    if not a or not b:
        return False
    return os.path.realpath(a) == os.path.realpath(b)
