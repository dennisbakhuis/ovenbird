"""Consistent copies of ``history.db`` for backups, and restoring from them.

A hot file copy of a live WAL database can be torn (the main file and the WAL
are copied at different moments). The writer therefore copies the database with
SQLite's online backup API into ``history.snapshot.db.tmp``, syncs it and renames
it atomically to ``history.snapshot.db``; backups include only the snapshot. After
a restore the snapshot is the only copy, and :func:`restore_snapshot` turns it
back into ``history.db`` before the database is opened.
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Final

LOGGER = logging.getLogger("ovenbird.history")
TMP_SUFFIX: Final = ".tmp"


def _fsync(path: Path) -> None:
    """Flush a file's contents to disk."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _replace_atomically(source: Path, target: Path) -> None:
    """Sync ``source``, rename it over ``target`` and sync the folder."""
    _fsync(source)
    os.replace(source, target)
    with contextlib.suppress(OSError):
        _fsync(target.parent)


def temp_path(target: Path) -> Path:
    """Return the temporary file a snapshot of ``target`` is written to."""
    return target.with_name(target.name + TMP_SUFFIX)


def discard_temp(target: Path) -> None:
    """Remove a leftover temporary snapshot file (and its journals), ignoring errors."""
    tmp = temp_path(target)
    for suffix in ("", "-journal", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            tmp.with_name(tmp.name + suffix).unlink(missing_ok=True)


def write_snapshot(conn: sqlite3.Connection, target: Path) -> None:
    """Copy the database behind ``conn`` consistently to ``target``.

    Parameters
    ----------
    conn
        Open connection to the source database (not inside a transaction).
    target
        Snapshot path; replaced atomically, so it is always a complete database.
        The temporary file is removed when the copy fails.
    """
    tmp = temp_path(target)
    tmp.unlink(missing_ok=True)
    try:
        dest = sqlite3.connect(tmp)
        try:
            conn.backup(dest)
            dest.execute("PRAGMA journal_mode = DELETE")
        finally:
            dest.close()
        _replace_atomically(tmp, target)
    except BaseException:
        discard_temp(target)
        raise


def backup_to(path: Path, target: Path) -> None:
    """Copy the database at ``path`` into a new file ``target`` through a read-only connection.

    The copy is one step of SQLite's online backup, so it is a consistent state of
    the database even while the writer keeps writing (for archives).

    Parameters
    ----------
    path
        The live database.
    target
        New file; must not exist.
    """
    source = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        source.execute("PRAGMA busy_timeout = 5000")
        dest = sqlite3.connect(target)
        try:
            source.backup(dest)
            dest.execute("PRAGMA journal_mode = DELETE")
        finally:
            dest.close()
    finally:
        source.close()


def restore_snapshot(path: Path, snapshot: Path) -> bool:
    """Recreate a missing ``path`` from ``snapshot`` (after a backup restore).

    Parameters
    ----------
    path
        Database file.
    snapshot
        Snapshot written by :func:`write_snapshot`.

    Returns
    -------
    bool
        Whether the database was restored; ``False`` when it exists or there is
        no snapshot.
    """
    if path.exists() or not snapshot.is_file():
        return False
    for suffix in ("-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)
    tmp = path.with_name(path.name + TMP_SUFFIX)
    shutil.copyfile(snapshot, tmp)
    _replace_atomically(tmp, path)
    LOGGER.warning("%s was missing; restored it from %s", path.name, snapshot)
    return True
