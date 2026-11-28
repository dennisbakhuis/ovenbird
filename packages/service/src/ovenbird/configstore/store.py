"""``config.db``: configuration versions, the audit trail and runtime flags.

Separate from ``history.db``; same pragmas (WAL), integrity check, quarantine and
numbered migrations (:mod:`ovenbird.configstore.migrations`). Tables:

- ``config_version``: append-only (enforced by triggers; only ``applied_ts`` is set
  once the control loop runs the version). ``doc`` holds the stored values only,
  a flat ``{field: value}`` JSON object.
- ``audit``: append-only record of state-changing requests.
- ``runtime``: flags that survive restarts (pause, pending reset).
- ``connection``: the connections set in the app: Home Assistant (``ha_url`` and the
  secret ``ha_token``) and the broker (``mqtt_*``, ``heishamon_base``, text values).
  Kept outside the versions on purpose: a rollback, an export or a seed never carries a
  connection or a secret, and no secret is part of a document the API returns. It does
  reach ``config.snapshot.db`` (backups).

Unlike ``history.db`` it runs with ``synchronous = FULL``: every commit (a pause,
the release run, the go-live snapshot) is on disk before the call returns, so a
power cut right after "Release control" cannot roll the pause back.

After every write that matters for a restore, :meth:`ConfigStore.snapshot` copies the
database consistently to ``config.snapshot.db`` (what backups pick up). A marker file
``config.id`` remembers that a store existed, so a missing ``config.db`` without a
snapshot to restore from is recognised as a loss rather than a first start.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from ovenbird.history.schema import (
    SchemaTooNewError,
    bundled_migrations,
    check_integrity,
    connect,
    migrate,
    quarantine,
)
from ovenbird.history.snapshot import restore_snapshot, write_snapshot
from ovenbird.sql import sql

LOGGER = logging.getLogger("ovenbird.configstore")
STORE_NAME: Final = "config.db"
SNAPSHOT_NAME: Final = "config.snapshot.db"
MARKER_NAME: Final = "config.id"
MIGRATIONS_PACKAGE: Final = "ovenbird.configstore.migrations"
COMPACT: Final = (",", ":")
VERSION_COLUMNS: Final = (
    "version, created_ts, actor, source_ip, origin, comment, parent, doc, doc_hash, applied_ts"
)
MAX_AUDIT: Final = 5000


class StoreLoss(StrEnum):
    """Why the stored configuration could not be used at start."""

    MISSING = "missing"
    CORRUPT = "corrupt"
    INVALID = "invalid"


class Origin(StrEnum):
    """Where a configuration version came from."""

    UI = "ui"
    ROLLBACK = "rollback"
    SEED = "seed"
    RESET = "reset"


def canonical(values: Mapping[str, Any]) -> str:
    """Return the canonical JSON text of a stored document."""
    return json.dumps(dict(values), sort_keys=True, separators=COMPACT, ensure_ascii=False)


def doc_hash(values: Mapping[str, Any]) -> str:
    """Return the SHA-256 hex digest of a document's canonical JSON."""
    return hashlib.sha256(canonical(values).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfigVersion:
    """One stored configuration version.

    Parameters
    ----------
    version
        Version number (1, 2, ...).
    created_ts
        When it was written (service clock, unix seconds).
    actor
        Who wrote it.
    source_ip
        Client address of the request.
    origin
        ``ui``, ``rollback``, ``seed`` or ``reset``.
    comment
        Optional comment.
    parent
        Version that was current when it was written.
    values
        Stored values.
    doc_hash
        SHA-256 of the canonical document.
    applied_ts
        When the control loop first ran it; ``None`` until then.
    """

    version: int
    created_ts: float
    actor: str
    source_ip: str | None
    origin: Origin
    comment: str | None
    parent: int | None
    values: dict[str, Any]
    doc_hash: str
    applied_ts: float | None

    @classmethod
    def from_row(cls, row: tuple[Any, ...]) -> ConfigVersion:
        """Build a version from a ``config_version`` row."""
        version, created, actor, ip, origin, comment, parent, doc, digest, applied = row
        return cls(
            version=int(version),
            created_ts=float(created),
            actor=str(actor),
            source_ip=None if ip is None else str(ip),
            origin=Origin(origin),
            comment=None if comment is None else str(comment),
            parent=None if parent is None else int(parent),
            values=json.loads(doc),
            doc_hash=str(digest),
            applied_ts=None if applied is None else float(applied),
        )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One audit row.

    Parameters
    ----------
    ts
        When it happened (service clock).
    actor
        Who did it.
    source_ip
        Client address.
    action
        ``config_apply``, ``config_rollback``, ``config_reset_ack``, ``mode_pause``,
        ``mode_resume``, ``hold_release``, ``pump_setting`` or ``auth_refused``.
    detail
        Machine-readable details.
    """

    ts: float
    actor: str
    source_ip: str | None
    action: str
    detail: dict[str, Any]


class ConfigStore:
    """Thread-safe access to ``config.db`` (one shared connection behind a lock).

    Build with :meth:`open`.

    Parameters
    ----------
    conn
        Open, migrated connection usable from several threads.
    path
        Database file.
    snapshot_path
        Consistent copy written by :meth:`snapshot`.
    """

    def __init__(self, conn: sqlite3.Connection, path: Path, snapshot_path: Path) -> None:
        self._conn = conn
        self.path = path
        self.snapshot_path = snapshot_path
        self._lock = threading.Lock()

    @classmethod
    def open(cls, data_dir: Path) -> tuple[ConfigStore, StoreLoss | None]:
        """Open (and create, restore or quarantine) the store in ``data_dir``.

        Parameters
        ----------
        data_dir
            Service data directory.

        Returns
        -------
        tuple
            The store and the loss detected while opening: ``missing`` when
            ``config.db`` is gone after having existed (marker present, no snapshot
            to restore), ``corrupt`` when it failed the integrity check (moved
            aside); ``None`` otherwise.

        Raises
        ------
        SchemaTooNewError
            When ``config.db`` was written by a newer version (left untouched).
        """
        data_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(data_dir, os.W_OK | os.X_OK):
            raise PermissionError(errno.EACCES, "Permission denied", str(data_dir))
        path = data_dir / STORE_NAME
        snapshot = data_dir / SNAPSHOT_NAME
        marker = data_dir / MARKER_NAME
        loss: StoreLoss | None = None
        if not path.exists() and not restore_snapshot(path, snapshot) and marker.exists():
            loss = StoreLoss.MISSING
            LOGGER.critical("CONFIGURATION STORE MISSING: %s existed before and is gone", path)
        migrations = bundled_migrations(MIGRATIONS_PACKAGE)
        conn: sqlite3.Connection | None = None
        try:
            conn = connect(path, shared=True)
            check_integrity(conn)
            migrate(conn, migrations, label=STORE_NAME)
        except SchemaTooNewError:
            if conn is not None:
                conn.close()
            raise
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()
            moved = quarantine(path)
            LOGGER.critical("CONFIGURATION STORE CORRUPT (%s): moved to %s", exc, moved)
            loss = StoreLoss.CORRUPT
            conn = connect(path, shared=True)
            migrate(conn, migrations, label=STORE_NAME)
        conn.execute("PRAGMA synchronous = FULL")
        if not marker.exists():
            marker.write_text(secrets.token_hex(16) + "\n", encoding="utf-8")
        return cls(conn, path, snapshot), loss

    def close(self) -> None:
        """Close the connection."""
        with self._lock:
            self._conn.close()

    def snapshot(self) -> None:
        """Write ``config.snapshot.db`` (atomically replaced)."""
        with self._lock:
            write_snapshot(self._conn, self.snapshot_path)

    def latest(self) -> ConfigVersion | None:
        """Return the newest version, if any."""
        with self._lock:
            row = self._conn.execute(
                sql(
                    "SELECT {columns} FROM config_version ORDER BY version DESC LIMIT 1",
                    columns=VERSION_COLUMNS,
                )
            ).fetchone()
        return None if row is None else ConfigVersion.from_row(row)

    def get(self, version: int) -> ConfigVersion | None:
        """Return version ``version``, if stored."""
        with self._lock:
            row = self._conn.execute(
                sql(
                    "SELECT {columns} FROM config_version WHERE version = ?",
                    columns=VERSION_COLUMNS,
                ),
                (version,),
            ).fetchone()
        return None if row is None else ConfigVersion.from_row(row)

    def versions(self, limit: int) -> list[ConfigVersion]:
        """Return the newest ``limit`` versions, newest first."""
        with self._lock:
            rows = self._conn.execute(
                sql(
                    "SELECT {columns} FROM config_version ORDER BY version DESC LIMIT ?",
                    columns=VERSION_COLUMNS,
                ),
                (limit,),
            ).fetchall()
        return [ConfigVersion.from_row(row) for row in rows]

    def append(
        self,
        values: Mapping[str, Any],
        *,
        actor: str,
        origin: Origin,
        now_ts: float,
        source_ip: str | None = None,
        comment: str | None = None,
    ) -> ConfigVersion:
        """Write a new version on top of the latest one.

        Parameters
        ----------
        values
            Stored values (JSON-serialisable).
        actor
            Who wrote it.
        origin
            Where it came from.
        now_ts
            Service clock time.
        source_ip
            Client address.
        comment
            Optional comment.

        Returns
        -------
        ConfigVersion
            The stored version.
        """
        text = canonical(values)
        digest = doc_hash(values)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT MAX(version) FROM config_version").fetchone()
                parent = None if row[0] is None else int(row[0])
                version = 1 if parent is None else parent + 1
                self._conn.execute(
                    sql(
                        "INSERT INTO config_version ({columns}) VALUES ({marks}, NULL)",
                        columns=VERSION_COLUMNS,
                        marks=9,
                    ),
                    (
                        version,
                        now_ts,
                        actor,
                        source_ip,
                        origin.value,
                        comment,
                        parent,
                        text,
                        digest,
                    ),
                )
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
        return ConfigVersion(
            version,
            now_ts,
            actor,
            source_ip,
            origin,
            comment,
            parent,
            json.loads(text),
            digest,
            None,
        )

    def mark_applied(self, version: int, ts: float) -> None:
        """Record when the control loop first ran ``version``."""
        with self._lock:
            self._conn.execute(
                "UPDATE config_version SET applied_ts = ? WHERE version = ? AND applied_ts IS NULL",
                (ts, version),
            )

    def count_since(self, ts: float, origins: Iterable[Origin]) -> int:
        """Return the number of versions of ``origins`` written at or after ``ts``."""
        names = [origin.value for origin in origins]
        with self._lock:
            row = self._conn.execute(
                sql(
                    "SELECT COUNT(*) FROM config_version WHERE created_ts >= ? "
                    "AND origin IN ({marks})",
                    marks=len(names),
                ),
                (ts, *names),
            ).fetchone()
        return int(row[0])

    def last_created(self, origins: Iterable[Origin]) -> float | None:
        """Return when the newest version of ``origins`` was written."""
        names = [origin.value for origin in origins]
        with self._lock:
            row = self._conn.execute(
                sql(
                    "SELECT MAX(created_ts) FROM config_version WHERE origin IN ({marks})",
                    marks=len(names),
                ),
                names,
            ).fetchone()
        return None if row[0] is None else float(row[0])

    def audit(
        self,
        ts: float,
        actor: str,
        action: str,
        detail: Mapping[str, Any] | None = None,
        *,
        source_ip: str | None = None,
    ) -> None:
        """Append one audit row.

        Parameters
        ----------
        ts
            Unix time of the event.
        actor
            Who did it.
        action
            What was done.
        detail
            Further facts, stored as JSON.
        source_ip
            Client address, when there is one.
        """
        text = json.dumps(dict(detail or {}), sort_keys=True, separators=COMPACT, default=str)
        with self._lock:
            self._conn.execute(
                "INSERT INTO audit (ts, actor, source_ip, action, detail) VALUES (?, ?, ?, ?, ?)",
                (ts, actor, source_ip, action, text),
            )

    def latest_audit(self, action: str, limit: int = 100) -> list[AuditEvent]:
        """Return the newest ``limit`` audit rows of ``action``, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, actor, source_ip, action, detail FROM audit "
                "WHERE action = ? ORDER BY ts DESC, id DESC LIMIT ?",
                (action, min(limit, MAX_AUDIT)),
            ).fetchall()
        return [
            AuditEvent(float(ts), str(actor), ip, str(name), json.loads(detail))
            for ts, actor, ip, name, detail in rows
        ]

    def audit_events(self, start: float, end: float, limit: int) -> list[AuditEvent]:
        """Return the newest ``limit`` audit rows in ``[start, end)``, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, actor, source_ip, action, detail FROM audit "
                "WHERE ts >= ? AND ts < ? ORDER BY ts DESC, id DESC LIMIT ?",
                (start, end, min(limit, MAX_AUDIT)),
            ).fetchall()
        return [
            AuditEvent(float(ts), str(actor), ip, str(action), json.loads(detail))
            for ts, actor, ip, action, detail in reversed(rows)
        ]

    def connection(self) -> dict[str, str]:
        """Return the stored connection values (HA and broker fields)."""
        with self._lock:
            rows = self._conn.execute("SELECT name, value FROM connection").fetchall()
        return {str(name): str(value) for name, value in rows}

    def set_connection(self, values: Mapping[str, str | None], now_ts: float) -> None:
        """Store (or with ``None`` remove) connection values in one transaction."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for name, value in values.items():
                    if value is None:
                        self._conn.execute("DELETE FROM connection WHERE name = ?", (name,))
                    else:
                        self._conn.execute(
                            "INSERT OR REPLACE INTO connection (name, value, updated_ts) "
                            "VALUES (?, ?, ?)",
                            (name, value, now_ts),
                        )
                self._conn.execute("COMMIT")
            except sqlite3.Error:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    def runtime_get(self, key: str) -> str | None:
        """Return the runtime flag ``key``, if set."""
        with self._lock:
            row = self._conn.execute("SELECT value FROM runtime WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def runtime_set(self, key: str, value: str | None) -> None:
        """Set (or with ``None`` remove) the runtime flag ``key``."""
        with self._lock:
            if value is None:
                self._conn.execute("DELETE FROM runtime WHERE key = ?", (key,))
            else:
                self._conn.execute(
                    "INSERT OR REPLACE INTO runtime (key, value) VALUES (?, ?)", (key, value)
                )
