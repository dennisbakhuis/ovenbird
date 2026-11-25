"""Open ``history.db``: pragmas, integrity check, quarantine and numbered migrations.

Migrations are the files ``NNNN_<name>.sql`` in :mod:`ovenbird.history.migrations`;
``PRAGMA user_version`` holds the number of the last one applied. Each migration
runs in its own transaction together with the ``user_version`` bump.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Final

from ovenbird.history.packing import register_functions

LOGGER = logging.getLogger("ovenbird.history")
MIGRATIONS_PACKAGE: Final = "ovenbird.history.migrations"
MIGRATION_RE: Final = re.compile(r"(\d{4})_[a-z0-9_]+\.sql")
SIDE_SUFFIXES: Final = ("-wal", "-shm", "-journal")
BUSY_TIMEOUT_MS: Final = 5000


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer version; it is left untouched."""


class CorruptDatabaseError(sqlite3.DatabaseError):
    """The integrity check failed."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One numbered schema migration.

    Parameters
    ----------
    version
        Number; becomes ``user_version`` once applied.
    name
        File name, for logging.
    sql
        Script to run.
    """

    version: int
    name: str
    sql: str


def bundled_migrations(package: str = MIGRATIONS_PACKAGE) -> tuple[Migration, ...]:
    """Return the migrations shipped in ``package``, in order.

    Parameters
    ----------
    package
        Package holding the ``NNNN_<name>.sql`` files (the history migrations by
        default).

    Raises
    ------
    RuntimeError
        When no migration is found or the numbering has gaps or duplicates.
    """
    found: list[Migration] = []
    for entry in resources.files(package).iterdir():
        match = MIGRATION_RE.fullmatch(entry.name)
        if match is not None:
            found.append(Migration(int(match.group(1)), entry.name, entry.read_text("utf-8")))
    found.sort(key=lambda migration: migration.version)
    if not found or [m.version for m in found] != list(range(1, len(found) + 1)):
        raise RuntimeError(f"{package} must be numbered 0001, 0002, ... without gaps")
    return tuple(found)


def user_version(conn: sqlite3.Connection) -> int:
    """Return ``PRAGMA user_version``."""
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def migrate(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] | None = None,
    *,
    label: str = "history.db",
) -> int:
    """Apply every migration newer than the database's ``user_version``.

    Parameters
    ----------
    conn
        Connection in autocommit mode (``isolation_level=None``).
    migrations
        Migrations in order; defaults to :func:`bundled_migrations`.
    label
        Database name for messages.

    Returns
    -------
    int
        The schema version after migrating.

    Raises
    ------
    SchemaTooNewError
        When the database is newer than the newest known migration.
    """
    available = tuple(migrations) if migrations is not None else bundled_migrations()
    latest = available[-1].version if available else 0
    current = user_version(conn)
    if current > latest:
        raise SchemaTooNewError(
            f"{label} has schema version {current}, this version knows up to {latest}"
        )
    for migration in available:
        if migration.version <= current:
            continue
        script = f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version:d};\nCOMMIT;"
        try:
            conn.executescript(script)
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        LOGGER.info("%s schema migrated to %d (%s)", label, migration.version, migration.name)
        current = migration.version
    return current


def connect(path: Path, *, read_only: bool = False, shared: bool = False) -> sqlite3.Connection:
    """Open a connection with the service's pragmas.

    Parameters
    ----------
    path
        Database file.
    read_only
        Open with ``mode=ro`` (for API queries).
    shared
        Allow use from several threads (the caller serialises access).

    Returns
    -------
    sqlite3.Connection
        Connection in autocommit mode; transactions are explicit. A writable
        connection can call the packing functions of :mod:`ovenbird.history.packing`
        from SQL, and a new database is created with incremental auto-vacuum.
    """
    if read_only:
        conn = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro",
            uri=True,
            isolation_level=None,
            check_same_thread=False,
        )
    else:
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=not shared)
        register_functions(conn)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS:d}")
    conn.execute("PRAGMA temp_store = MEMORY")
    if not read_only:
        if _empty(conn):
            conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _empty(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    return int(row[0]) == 0


def check_integrity(conn: sqlite3.Connection) -> None:
    """Run ``PRAGMA integrity_check``.

    Raises
    ------
    CorruptDatabaseError
        When SQLite reports anything other than ``ok``.
    """
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    if [tuple(row) for row in rows] != [("ok",)]:
        detail = "; ".join(str(row[0]) for row in rows[:5])
        raise CorruptDatabaseError(f"integrity check failed: {detail}")


def quarantine(path: Path, *, now: datetime | None = None) -> Path:
    """Move a database and its WAL/SHM side files aside.

    Parameters
    ----------
    path
        Database file.
    now
        Timestamp for the new name; defaults to the current UTC time.

    Returns
    -------
    Path
        The new path of the database file.
    """
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    for suffix in ("", *SIDE_SUFFIXES):
        source = path.with_name(path.name + suffix)
        if source.exists():
            source.replace(target.with_name(target.name + suffix))
    return target


def open_history(path: Path, migrations: Sequence[Migration] | None = None) -> sqlite3.Connection:
    """Open, check and migrate the history database; quarantine it when corrupt.

    Parameters
    ----------
    path
        Database file; created when missing.
    migrations
        Migrations to apply; defaults to the bundled ones.

    Returns
    -------
    sqlite3.Connection
        Writer connection on a healthy, migrated database.

    Raises
    ------
    SchemaTooNewError
        When the database is newer than this version (it is not quarantined).
    sqlite3.OperationalError
        When the file cannot be used right now (disk full, locked, I/O error, read-only):
        a healthy database is never quarantined for that; the caller retries later.
        Only real corruption (``file is not a database``, ``malformed``, a failed
        integrity check) moves the file aside.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection | None = None
    try:
        conn = connect(path)
        check_integrity(conn)
        migrate(conn, migrations)
    except SchemaTooNewError, sqlite3.OperationalError:
        if conn is not None:
            conn.close()
        raise
    except sqlite3.DatabaseError as exc:
        if conn is not None:
            conn.close()
        moved = quarantine(path)
        LOGGER.critical(
            "HISTORY DATABASE CORRUPT (%s): moved to %s and starting with an empty history",
            exc,
            moved,
        )
        conn = connect(path)
        migrate(conn, migrations)
    return conn
