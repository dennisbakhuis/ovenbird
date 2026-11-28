"""The yearly archive: every calendar month frozen into ``archive/YYYY-MM.zip``.

Months are calendar months in the installation's time zone (``control_timezone``).
A month is built **progressively**: the history writer calls
:meth:`MonthArchiver.step` between its batches (every quarter of an hour, and before
it applies retention), which appends what ``history.db`` gained since the last step to
the month's working copy ``archive/YYYY-MM.db``, a ``history.db`` subset with the
same schema:

- the 1 min, 15 min and 1 h rollups whose bucket starts in the month and has ended;
- the decisions (packed, with the dictionaries they use), commands and alarms;
- the forecasts issued in the month, and the signal table.

Raw samples and the rollup index that only serves retention stay out. Each step
copies again the last :data:`REWIND_S` before what it had reached (rollup buckets
still change while a held value is integrated) and leaves the last :data:`LAG_S` for
the next step. Because the copy runs every quarter of an hour
and every retention is at least a day (:mod:`ovenbird.history.settings`), nothing
reaches retention before it is in the archive; while the archive catches up (after a
start, or when it was switched on) the writer holds retention back.

Rows are matched on what they hold, never on the row ids of ``history.db``: the
journal tables have no ``AUTOINCREMENT``, so ids are handed out again once the highest
rows are gone (retention removing every row, a quarantined ``history.db`` started
afresh). Signals are matched by name, dictionaries by creation time and content,
journal rows by all their columns, rollups and forecasts by their primary keys.

A step that fails (an exception, too little free space) keeps retention waiting, and
retries after :data:`INTERVAL_S`. After :data:`FAILING_AFTER` failures in a row the
alarm ``archive_failing`` is raised (the next good step clears it). Retention waits
at most :data:`MAX_WAIT_S` (3 days) from the first failure of the streak; after that it
runs again, even though data it removes may then never reach the archive.

A working copy SQLite reports as damaged (``file is not a database``, ``malformed``,
a failed ``PRAGMA quick_check``, checked once per start and before every freeze) is
moved aside to ``YYYY-MM.db.corrupt-<time>`` and rebuilt from what ``history.db``
still holds; the alarm ``archive_rebuilt`` says so for :data:`REBUILT_NOTICE_S`.

Once a month has ended (plus :data:`REWIND_S`), it is **frozen**: the working copy,
the configuration versions active in it (``config.json``) and ``manifest.json`` (the
coverage per resolution, the days without data) are written into
``YYYY-MM.zip.tmp`` a slice at a time (:class:`ZipBuild`, within the step's budget, so
the writer thread is never held for long), read back and compared with the working
copy, synced and renamed to ``YYYY-MM.zip``; only then is the working copy removed, so
a crash at any point leaves either the working copy or the finished file. Months the
live history still holds but the archive lacks (a first start, a time switched off)
are caught up oldest first, as far as the live data reaches; what retention already
removed shows as missing days in the manifest. A month without any data is not
written. Deleted months (:meth:`ArchiveFolder.delete`) are remembered in
``state.json`` and never frozen again.

The format follows ``GET api/v1/export/archive`` (a zip with ``history.db``,
``config.json`` and ``manifest.json``), so the tools that read an archive's
``history.db`` read a month as well. A year (``2026``) or heating season (August to
July, ``2026/27``) is a zip of its months with a combined manifest
(:func:`write_bundle`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import IO, Any, Final
from zoneinfo import ZoneInfo

from ovenbird import __version__
from ovenbird.clock import iso_from_unix
from ovenbird.history.database import ROLLUP_STEPS
from ovenbird.history.packing import register_functions
from ovenbird.history.schema import BUSY_TIMEOUT_MS, migrate, quarantine, user_version
from ovenbird.history.snapshot import backup_to
from ovenbird.sql import sql

LOGGER = logging.getLogger("ovenbird.history")
ARCHIVE_FORMAT: Final = 1
LAG_S: Final = 600.0
REWIND_S: Final = 6 * 3600.0
CHUNK_S: Final = 86_400.0
INTERVAL_S: Final = 900.0
BUDGET_S: Final = 0.5
FAILING_AFTER: Final = 4
MAX_WAIT_S: Final = 3 * 86_400.0
REBUILT_NOTICE_S: Final = 86_400.0
ALARM_FAILING: Final = "archive_failing"
ALARM_REBUILT: Final = "archive_rebuilt"
SEASON_START_MONTH: Final = 8
STATE_NAME: Final = "state.json"
OPEN_SUFFIX: Final = ".db"
FROZEN_SUFFIX: Final = ".zip"
TMP_SUFFIX: Final = ".tmp"
BUILD_PREFIX: Final = ".archive-"
ZIP_LEVEL: Final = 6
ZIP_SLICE_BYTES: Final = 1 << 20
RETENTION_INDEX: Final = "rollup_step_bucket"
MONTH_RE: Final = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
YEAR_RE: Final = re.compile(r"\d{4}")
SEASON_RE: Final = re.compile(r"(\d{4})-(\d{2})")
JOURNALS: Final = (("decision", "ts"), ("command", "ts"), ("alarm", "ts"))
DAILY: Final = ("60", "900", "3600", "decisions")
COMPLETE_BY: Final = ("60", "decisions")
ARCHIVE_NOTICE: Final = (
    "This archive holds the full measurement history of the installation: room and "
    "water temperatures, heat-pump activity and the controller's decisions. Over weeks "
    "they reveal when the house is occupied, heated or empty. Share it with care."
)

type ConfigSource = Callable[[float, float, Sequence[int | None]], dict[str, Any]]
type AlarmHook = Callable[[str, bool, str], None]


class ArchiveError(Exception):
    """A request about the archive that cannot be served (unknown or open period)."""


class ZipVerifyError(Exception):
    """A month's zip does not read back as the working copy it was built from."""


@dataclass(frozen=True, slots=True, order=True)
class Month:
    """One calendar month.

    Parameters
    ----------
    year, month
        Year and month (1-12).
    """

    year: int
    month: int

    @classmethod
    def parse(cls, text: str) -> Month:
        """Return the month of ``YYYY-MM``.

        Raises
        ------
        ArchiveError
            For any other text.
        """
        found = MONTH_RE.fullmatch(text)
        if found is None:
            raise ArchiveError(f"{text!r} is not a month (YYYY-MM)")
        return cls(int(found[1]), int(found[2]))

    @classmethod
    def of(cls, ts: float, timezone: str) -> Month:
        """Return the local month that holds unix time ``ts``."""
        local = datetime.fromtimestamp(ts, ZoneInfo(timezone))
        return cls(local.year, local.month)

    def __str__(self) -> str:
        """Return ``YYYY-MM``."""
        return f"{self.year:04d}-{self.month:02d}"

    def next(self) -> Month:
        """Return the following month."""
        return Month(self.year + 1, 1) if self.month == 12 else Month(self.year, self.month + 1)

    def first_day(self) -> date:
        """Return the month's first day."""
        return date(self.year, self.month, 1)

    def days(self) -> list[date]:
        """Return the days of the month."""
        first, after = self.first_day(), self.next().first_day()
        return [first + timedelta(days=n) for n in range((after - first).days)]

    def bounds(self, timezone: str) -> tuple[float, float]:
        """Return the month's start and end in unix seconds (local midnights)."""
        zone = ZoneInfo(timezone)
        first, after = self.first_day(), self.next().first_day()
        start = datetime(first.year, first.month, first.day, tzinfo=zone).timestamp()
        end = datetime(after.year, after.month, after.day, tzinfo=zone).timestamp()
        return start, end

    @property
    def season(self) -> int:
        """Return the year the heating season of this month starts (August to July)."""
        return self.year if self.month >= SEASON_START_MONTH else self.year - 1


def months_between(first: Month, last: Month) -> list[Month]:
    """Return the months from ``first`` to ``last``, both included."""
    found = []
    month = first
    while month <= last:
        found.append(month)
        month = month.next()
    return found


def season_label(start_year: int) -> str:
    """Return a heating season's label (``2026/27``)."""
    return f"{start_year}/{(start_year + 1) % 100:02d}"


def season_id(start_year: int) -> str:
    """Return a heating season's id in paths (``2026-27``)."""
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def parse_season(text: str) -> int:
    """Return the start year of a season id ``YYYY-YY``.

    Raises
    ------
    ArchiveError
        When ``text`` is not a season id.
    """
    found = SEASON_RE.fullmatch(text)
    if found is None or (int(found[1]) + 1) % 100 != int(found[2]):
        raise ArchiveError(f"{text!r} is not a heating season (YYYY-YY, e.g. 2026-27)")
    return int(found[1])


def parse_year(text: str) -> int:
    """Return the year of ``YYYY``.

    Raises
    ------
    ArchiveError
        When ``text`` is not a year.
    """
    if YEAR_RE.fullmatch(text) is None:
        raise ArchiveError(f"{text!r} is not a year (YYYY)")
    return int(text)


def year_months(year: int) -> list[Month]:
    """Return the months of a calendar year."""
    return [Month(year, n) for n in range(1, 13)]


def season_months(start_year: int) -> list[Month]:
    """Return the months of the heating season that starts in August of ``start_year``."""
    return months_between(Month(start_year, SEASON_START_MONTH), Month(start_year + 1, 7))


def _fsync(path: Path) -> None:
    """Flush a file's contents to disk."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace_atomically(source: Path, target: Path) -> None:
    """Sync ``source``, rename it to ``target`` and sync the folder."""
    _fsync(source)
    os.replace(source, target)
    with contextlib.suppress(OSError):
        _fsync(target.parent)


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    """Return the column names of a table in an attached or main schema."""
    rows = conn.execute(f"PRAGMA {schema}.table_info({table})").fetchall()
    return [str(row[1]) for row in rows]


def _has_table(conn: sqlite3.Connection, schema: str, table: str) -> bool:
    """Return whether a table exists in the schema."""
    found = conn.execute(
        sql(
            "SELECT 1 FROM {schema}.sqlite_master WHERE type = 'table' AND name = ?", schema=schema
        ),
        (table,),
    ).fetchone()
    return found is not None


def open_month(path: Path) -> sqlite3.Connection:
    """Open (and create or migrate) a month's working copy, with its ``archive_meta`` table.

    The copy has the schema of ``history.db`` without the rollup index that only
    serves retention (a quarter of the rollup bytes); every read goes by the rollup's
    primary key.
    """
    conn = sqlite3.connect(path.resolve().as_uri(), uri=True, isolation_level=None)
    try:
        register_functions(conn)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS:d}")
        conn.execute("PRAGMA journal_mode = DELETE")
        migrate(conn, label=path.name)
        conn.execute(f"DROP INDEX IF EXISTS {RETENTION_INDEX}")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS archive_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
    except BaseException:
        conn.close()
        raise
    return conn


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    """Return the ``archive_meta`` rows of a month file (empty when it has none)."""
    if not _has_table(conn, "main", "archive_meta"):
        return {}
    return {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM archive_meta")}


def _set_meta(conn: sqlite3.Connection, values: Mapping[str, Any]) -> None:
    """Store the values in the archive metadata table, replacing earlier ones."""
    conn.executemany(
        "INSERT OR REPLACE INTO archive_meta (key, value) VALUES (?, ?)",
        [(key, str(value)) for key, value in values.items()],
    )


def _content(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return the columns of a table without its row id."""
    return [name for name in _columns(conn, "main", table) if name != "id"]


def _select(names: Sequence[str], alias: str, replaced: Mapping[str, str]) -> str:
    """Return a select list taking each column from ``alias``, or its replacement expression."""
    return ", ".join(replaced.get(name, f"{alias}.{name}") for name in names)


def _same(names: Sequence[str], left: str, right: str) -> str:
    """Return a condition comparing the columns of two aliases with ``IS``."""
    return " AND ".join(f"{left}.{name} IS {right}.{name}" for name in names)


def copy_window(conn: sqlite3.Connection, lo: float, hi: float, settled: float) -> None:
    """Copy ``[lo, hi)`` of the attached ``live`` history into the month file of ``conn``.

    Rollup buckets are copied once they ended before ``settled`` and replace earlier
    copies; journal rows and forecasts keep their first copy. Nothing is matched on a
    row id of ``history.db``, which can be handed out again: signals go by name,
    rollups by resolution, signal name and bucket, dictionaries by creation time and
    content, journal rows (with a new id in the month file) by every other column,
    forecasts by issue and target time.

    Parameters
    ----------
    conn
        Month file with the live ``history.db`` attached as ``live``.
    lo, hi
        Window in unix seconds (bucket start, row time, forecast issue time).
    settled
        Buckets ending after this are left for a later step.
    """
    has_signal = _has_table(conn, "live", "signal")
    if has_signal:
        names = _content(conn, "signal")
        update = ", ".join(f"{name} = excluded.{name}" for name in names if name != "name")
        conn.execute(
            f"INSERT INTO signal ({', '.join(names)}) SELECT {', '.join(names)} "  # noqa: S608
            f"FROM live.signal WHERE true ORDER BY id ON CONFLICT (name) DO UPDATE SET {update}"
        )
    if has_signal and _has_table(conn, "live", "rollup"):
        names = _columns(conn, "main", "rollup")
        select = _select(names, "r", {"signal_id": "m.id"})
        for step in ROLLUP_STEPS:
            conn.execute(
                f"INSERT OR REPLACE INTO rollup ({', '.join(names)}) SELECT {select} "  # noqa: S608
                "FROM live.rollup AS r JOIN live.signal AS s ON s.id = r.signal_id "
                "JOIN main.signal AS m ON m.name = s.name "
                "WHERE r.step = ? AND r.bucket >= ? AND r.bucket < ? AND r.bucket + ? <= ?",
                (step, lo, hi, step, settled),
            )
    replaced: dict[str, str] = {}
    if _has_table(conn, "live", "decision_dictionary") and _has_table(conn, "live", "decision"):
        names = _content(conn, "decision_dictionary")
        same = _same(names, "m", "d")
        conn.execute(
            f"INSERT INTO decision_dictionary ({', '.join(names)}) "  # noqa: S608
            f"SELECT {_select(names, 'd', {})} FROM live.decision_dictionary AS d "
            "WHERE d.id IN (SELECT dictionary_id FROM live.decision WHERE ts >= ? AND ts < ?) "
            f"AND NOT EXISTS (SELECT 1 FROM main.decision_dictionary AS m WHERE {same}) "
            "ORDER BY d.id",
            (lo, hi),
        )
        replaced["dictionary_id"] = (
            "(SELECT m.id FROM main.decision_dictionary AS m "  # noqa: S608
            f"JOIN live.decision_dictionary AS d ON {same} "
            "WHERE d.id = l.dictionary_id ORDER BY m.id LIMIT 1)"
        )
    for table, key in JOURNALS:
        if not _has_table(conn, "live", table):
            continue
        names = _content(conn, table)
        mapped = replaced if table == "decision" else {}
        others = [name for name in names if name != key and name not in mapped]
        conn.execute(
            f"INSERT INTO {table} ({', '.join(names)}) "  # noqa: S608
            f"SELECT {_select(names, 'l', mapped)} FROM live.{table} AS l "
            f"WHERE l.{key} >= ? AND l.{key} < ? AND NOT EXISTS (SELECT 1 FROM main.{table} "
            f"AS m WHERE m.{key} = l.{key} AND {_same(others, 'm', 'l')}) ORDER BY l.id",
            (lo, hi),
        )
    if _has_table(conn, "live", "forecast"):
        listed = ", ".join(_columns(conn, "main", "forecast"))
        conn.execute(
            sql(
                "INSERT OR IGNORE INTO forecast ({columns}) SELECT {columns} FROM live.forecast "
                "WHERE issued_ts >= ? AND issued_ts < ?",
                columns=listed,
            ),
            (lo, hi),
        )


def read_only(path: Path) -> sqlite3.Connection:
    """Open ``path`` read-only with the service's busy timeout."""
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS:d}")
    return conn


def first_data(path: Path) -> float | None:
    """Return the oldest time ``history.db`` holds archived data for (rollups, journals)."""
    sources: list[tuple[str, str, int | None]] = [
        ("rollup", "bucket", step) for step in ROLLUP_STEPS
    ]
    sources += [(table, key, None) for table, key in (*JOURNALS, ("forecast", "issued_ts"))]
    conn = read_only(path)
    try:
        found: list[float] = []
        for table, column, step in sources:
            if not _has_table(conn, "main", table):
                continue
            statement = sql("SELECT min({column}) FROM {table}", column=column, table=table)
            value = (
                conn.execute(statement).fetchone()[0]
                if step is None
                else conn.execute(f"{statement} WHERE step = ?", (step,)).fetchone()[0]
            )
            if value is not None:
                found.append(float(value))
    finally:
        conn.close()
    return min(found) if found else None


def _local_dates(hours: Iterable[tuple[int, int]], zone: ZoneInfo) -> dict[date, int]:
    """Count the rows per local calendar date for ``(hour, count)`` pairs."""
    found: dict[date, int] = {}
    for hour, count in hours:
        day = datetime.fromtimestamp(hour * 3600, zone).date()
        found[day] = found.get(day, 0) + int(count)
    return found


def coverage(
    conn: sqlite3.Connection, month: Month, timezone: str, until: float | None = None
) -> dict[str, Any]:
    """Return what a month file holds per resolution and journal.

    Parameters
    ----------
    conn
        The month's database.
    month
        Its month.
    timezone
        Time zone of its days.
    until
        Days from this time on are not counted as missing (an open month).

    Returns
    -------
    dict
        ``{"60" | "900" | "3600" | "decisions": {"rows", "first", "last", "days",
        "missing_days"}, "commands" | "alarms" | "forecast": {"rows", "first", "last"}}``.
    """
    zone = ZoneInfo(timezone)
    every = month.days()
    days = every
    if until is not None:
        today = datetime.fromtimestamp(until, zone).date()
        days = [day for day in every if day < today]
    found: dict[str, Any] = {}
    sources: list[tuple[str, str, str, tuple[Any, ...]]] = [
        (str(step), "rollup", "bucket", (step,)) for step in ROLLUP_STEPS
    ]
    sources += [
        ("decisions", "decision", "ts", ()),
        ("commands", "command", "ts", ()),
        ("alarms", "alarm", "ts", ()),
        ("forecast", "forecast", "issued_ts", ()),
    ]
    for key, table, column, params in sources:
        where = "WHERE step = ?" if table == "rollup" else ""
        totals = sql(
            "SELECT count(*), min({column}), max({column}) FROM {table}", column=column, table=table
        )
        hourly = sql(
            "SELECT CAST({column} / 3600 AS INTEGER), count(*) FROM {table}",
            column=column,
            table=table,
        )
        if not _has_table(conn, "main", table):
            rows, first, last = 0, None, None
        else:
            rows, first, last = conn.execute(
                f"{totals} {where}",
                params,
            ).fetchone()
        item: dict[str, Any] = {
            "rows": int(rows or 0),
            "first": None if first is None else iso_from_unix(float(first)),
            "last": None if last is None else iso_from_unix(float(last)),
        }
        if key in DAILY:
            per_day = {}
            if rows:
                hours = conn.execute(
                    f"{hourly} {where} GROUP BY 1",
                    params,
                ).fetchall()
                per_day = _local_dates(hours, zone)
            item["days"] = sum(1 for day in every if per_day.get(day))
            item["missing_days"] = [day.isoformat() for day in days if not per_day.get(day)]
        found[key] = item
    return found


def is_complete(cover: Mapping[str, Any]) -> bool:
    """Whether a month has 1 min data and decisions on every day."""
    return all(not cover[key]["missing_days"] for key in COMPLETE_BY)


def _signals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return the signals that have rollups, with unit and kind."""
    if not _has_table(conn, "main", "signal"):
        return []
    used = (
        "SELECT name, unit, kind FROM signal WHERE id IN (SELECT DISTINCT signal_id FROM rollup) "
        "ORDER BY name"
    )
    return [{"id": name, "unit": unit, "kind": kind} for name, unit, kind in conn.execute(used)]


def used_versions(conn: sqlite3.Connection) -> list[int | None]:
    """Return the configuration versions the month's decisions ran with."""
    if not _has_table(conn, "main", "decision"):
        return []
    rows = conn.execute("SELECT DISTINCT config_version FROM decision").fetchall()
    return sorted((row[0] for row in rows), key=lambda v: (v is not None, v or 0))


def month_manifest(
    conn: sqlite3.Connection,
    month: Month,
    timezone: str,
    bounds: tuple[float, float],
    *,
    created: float,
    frozen: bool,
    config: bool,
    until: float | None = None,
) -> dict[str, Any]:
    """Return ``manifest.json`` of a month.

    Parameters
    ----------
    conn
        The month's database.
    month
        Its month.
    timezone
        Time zone of its bounds and days.
    bounds
        Start and end in unix seconds.
    created
        When the file is written.
    frozen
        Whether the month is final (``False`` for a download of the open month).
    config
        Whether ``config.json`` is part of the file.
    until
        For an open month: the time it holds data up to.
    """
    cover = coverage(conn, month, timezone, until)
    meta = read_meta(conn)
    return {
        "ovenbird_archive": ARCHIVE_FORMAT,
        "kind": "month",
        "period": str(month),
        "timezone": timezone,
        "from": iso_from_unix(bounds[0]),
        "to": iso_from_unix(bounds[1]),
        "frozen": frozen,
        "complete": frozen and is_complete(cover),
        "archived_to": iso_from_unix(float(meta["watermark"])) if "watermark" in meta else None,
        "app_version": __version__,
        "created_at": iso_from_unix(created),
        "history_schema": user_version(conn),
        "resolutions": [str(step) for step in ROLLUP_STEPS],
        "coverage": cover,
        "signals": _signals(conn),
        "config_versions": used_versions(conn),
        "files": ["history.db", "manifest.json"] + (["config.json"] if config else []),
        "notice": ARCHIVE_NOTICE,
    }


def write_month_zip(
    database: Path,
    target: Path,
    manifest: Mapping[str, Any],
    config: Mapping[str, Any] | None,
) -> None:
    """Write a month's zip to ``target`` through ``target.tmp`` (synced, then renamed).

    Parameters
    ----------
    database
        Month database file to store as ``history.db``.
    target
        Zip file to produce.
    manifest
        Manifest stored as ``manifest.json``.
    config
        Configuration stored as ``config.json``; omitted when ``None``.
    """
    tmp = target.with_name(target.name + TMP_SUFFIX)
    tmp.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(
            tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=ZIP_LEVEL
        ) as zf:
            zf.write(database, "history.db")
            if config is not None:
                zf.writestr("config.json", json.dumps(config, indent=2) + "\n")
            zf.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        replace_atomically(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def damage(conn: sqlite3.Connection) -> str | None:
    """Return what ``PRAGMA quick_check`` finds wrong with ``conn``'s file; ``None`` when sound.

    Raises
    ------
    sqlite3.OperationalError
        When the file cannot be checked right now (locked, disk full, I/O error):
        that says nothing about its content.
    """
    try:
        rows = conn.execute("PRAGMA main.quick_check").fetchall()
    except sqlite3.OperationalError:
        raise
    except sqlite3.DatabaseError as exc:
        return str(exc)
    if [tuple(row) for row in rows] == [("ok",)]:
        return None
    return "; ".join(str(row[0]) for row in rows[:5])


def damaged(path: Path) -> str | None:
    """Return what is wrong with the SQLite file ``path``; ``None`` when it checks out.

    The file is opened read-write, so a hot journal left by a crash is rolled back
    first, as any later use would.
    """
    try:
        conn = sqlite3.connect(path.resolve().as_uri(), uri=True, isolation_level=None)
    except sqlite3.OperationalError:
        raise
    except sqlite3.DatabaseError as exc:
        return str(exc)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS:d}")
        return damage(conn)
    finally:
        conn.close()


def clean_build_folders(data_dir: Path) -> list[Path]:
    """Remove the ``.archive-*`` folders downloads and exports left in the data directory.

    A download (an open month, a year, a season, ``export/archive``) is built in such a
    folder and removed after it was sent; a crash or kill in between leaves it behind.
    Call at start, before the API serves, when every such folder is a leftover.

    Returns
    -------
    list of Path
        The folders removed.
    """
    removed: list[Path] = []
    if not data_dir.is_dir():
        return removed
    for item in sorted(data_dir.glob(f"{BUILD_PREFIX}*")):
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item, ignore_errors=True)
            removed.append(item)
    if removed:
        LOGGER.info("removed %d leftover archive build folder(s)", len(removed))
    return removed


class ZipBuild:
    """Write and verify one month's zip a slice at a time, between writer batches.

    The working copy is streamed into ``YYYY-MM.zip.tmp`` (deflate level
    :data:`ZIP_LEVEL`) :data:`ZIP_SLICE_BYTES` at a time, followed by ``config.json``
    and ``manifest.json``. The zip is then read back: its members must be exactly
    those, ``manifest.json`` and ``config.json`` must read back as written, and
    ``history.db`` is decompressed slice by slice (its CRC-32 checked) and compared
    byte for byte with the working copy, which passed ``PRAGMA quick_check`` before
    the build started. The contained database is therefore the checked one, without a
    second copy on disk. Only then is the zip synced and renamed and the working copy
    removed.

    Parameters
    ----------
    month
        The month.
    source
        Its working copy (no longer written to).
    target
        ``YYYY-MM.zip``.
    manifest
        ``manifest.json``.
    config
        ``config.json``, if any.
    slice_bytes
        Bytes written or compared per slice.
    """

    def __init__(
        self,
        month: Month,
        source: Path,
        target: Path,
        manifest: Mapping[str, Any],
        config: Mapping[str, Any] | None,
        slice_bytes: int = ZIP_SLICE_BYTES,
    ) -> None:
        self.month = month
        self.source = source
        self.target = target
        self.tmp = target.with_name(target.name + TMP_SUFFIX)
        self.manifest = dict(manifest)
        self.config = None if config is None else dict(config)
        self.slice_bytes = slice_bytes
        self.size = source.stat().st_size
        self.verifying = False
        self._zip: zipfile.ZipFile | None = None
        self._member: IO[bytes] | None = None
        self._source: IO[bytes] | None = None
        self.tmp.unlink(missing_ok=True)
        try:
            self._zip = zipfile.ZipFile(
                self.tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=ZIP_LEVEL
            )
            info = zipfile.ZipInfo.from_file(source, "history.db")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.compress_level = ZIP_LEVEL
            self._member = self._zip.open(info, "w")
            self._source = source.open("rb")
        except BaseException:
            self.abort()
            raise

    def _texts(self) -> dict[str, str]:
        """Return the JSON member texts of the zip by name."""
        texts = {"manifest.json": json.dumps(self.manifest, indent=2) + "\n"}
        if self.config is not None:
            texts["config.json"] = json.dumps(self.config, indent=2) + "\n"
        return texts

    def _close(self) -> None:
        """Close the open handles, ignoring errors."""
        for handle in (self._member, self._source, self._zip):
            if handle is not None:
                with contextlib.suppress(Exception):
                    handle.close()
        self._member = self._source = self._zip = None

    def _open(self) -> tuple[zipfile.ZipFile, IO[bytes], IO[bytes]]:
        """Return the open zip, member and source, or raise when the build is not open."""
        if self._zip is None or self._member is None or self._source is None:
            raise ZipVerifyError(f"{self.tmp.name} is not open")
        return self._zip, self._member, self._source

    def _write_slice(self) -> None:
        """Copy one slice of the database into the zip, or finish the zip when it is all copied."""
        archive, member, source = self._open()
        chunk = source.read(self.slice_bytes)
        if chunk:
            member.write(chunk)
            return
        member.close()
        source.close()
        texts = self._texts()
        for name in ("config.json", "manifest.json"):
            if name in texts:
                archive.writestr(name, texts[name])
        archive.close()
        self._member = self._source = self._zip = None
        self._open_check()

    def _open_check(self) -> None:
        """Open the finished zip and check its members and sizes against the sources."""
        self._zip = zipfile.ZipFile(self.tmp)
        texts = self._texts()
        names = sorted(self._zip.namelist())
        if names != sorted(["history.db", *texts]):
            raise ZipVerifyError(f"{self.tmp.name} holds {names}")
        for name, text in texts.items():
            if json.loads(self._zip.read(name)) != json.loads(text):
                raise ZipVerifyError(f"{name} in {self.tmp.name} does not read back")
        if self._zip.getinfo("history.db").file_size != self.size:
            raise ZipVerifyError(f"history.db in {self.tmp.name} has the wrong size")
        self._member = self._zip.open("history.db")
        self._source = self.source.open("rb")
        self.verifying = True

    def _check_slice(self) -> bool:
        """Compare one slice of the zip's database with the source; return whether it ended."""
        _, member, source = self._open()
        got = member.read(self.slice_bytes)
        expected = source.read(len(got) or 1)
        if got != expected:
            raise ZipVerifyError(f"history.db in {self.tmp.name} differs from the working copy")
        return not got

    def run(self, deadline: float) -> bool:
        """Work until ``deadline`` (``time.monotonic()``); at least one slice.

        Returns
        -------
        bool
            ``True`` once the zip is verified and in place and the working copy removed.

        Raises
        ------
        ZipVerifyError, zipfile.BadZipFile, zlib.error, OSError
            When the zip cannot be written or does not read back; call :meth:`abort`.
        """
        while True:
            if not self.verifying:
                self._write_slice()
            elif self._check_slice():
                self._close()
                replace_atomically(self.tmp, self.target)
                self.source.unlink(missing_ok=True)
                self.source.with_name(self.source.name + "-journal").unlink(missing_ok=True)
                return True
            if time.monotonic() >= deadline:
                return False

    def abort(self) -> None:
        """Close the files and remove the unfinished zip; the working copy stays."""
        self._close()
        self.tmp.unlink(missing_ok=True)


def read_zip_manifest(path: Path) -> dict[str, Any] | None:
    """Return the ``manifest.json`` of a month's zip; ``None`` when unreadable."""
    try:
        with zipfile.ZipFile(path) as zf:
            body = json.loads(zf.read("manifest.json"))
    except OSError, KeyError, ValueError, zipfile.BadZipFile:
        return None
    return body if isinstance(body, dict) else None


@dataclass
class ArchiveFolder:
    """The files of the archive folder and its ``state.json``.

    Parameters
    ----------
    path
        ``<data dir>/archive``.
    """

    path: Path
    lock: threading.Lock = field(default_factory=threading.Lock)
    _manifests: dict[str, tuple[float, int, dict[str, Any] | None]] = field(default_factory=dict)

    def frozen_path(self, month: Month) -> Path:
        """Return the finished file of ``month``."""
        return self.path / f"{month}{FROZEN_SUFFIX}"

    def open_path(self, month: Month) -> Path:
        """Return the working copy of ``month``."""
        return self.path / f"{month}{OPEN_SUFFIX}"

    def _months(self, suffix: str) -> dict[Month, Path]:
        """Return the month files with ``suffix`` in the folder by month, oldest first."""
        if not self.path.is_dir():
            return {}
        found = {}
        for item in self.path.iterdir():
            if item.suffix != suffix or not item.is_file():
                continue
            with contextlib.suppress(ArchiveError):
                found[Month.parse(item.stem)] = item
        return dict(sorted(found.items()))

    def frozen(self) -> dict[Month, Path]:
        """Return the finished months and their files, oldest first."""
        return self._months(FROZEN_SUFFIX)

    def open_months(self) -> dict[Month, Path]:
        """Return the months being built and their working copies, oldest first."""
        return self._months(OPEN_SUFFIX)

    def state(self) -> dict[str, list[str]]:
        """Return ``state.json``: the ``deleted`` and ``empty`` months."""
        try:
            body = json.loads((self.path / STATE_NAME).read_text(encoding="utf-8"))
        except OSError, ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return {
            key: [str(item) for item in body.get(key, []) if isinstance(item, str)]
            for key in ("deleted", "empty")
        }

    def remember(self, key: str, months: Iterable[Month]) -> None:
        """Add ``months`` to the ``deleted`` or ``empty`` list of ``state.json``."""
        state = self.state()
        state[key] = sorted(set(state[key]) | {str(month) for month in months})
        self.path.mkdir(parents=True, exist_ok=True)
        target = self.path / STATE_NAME
        tmp = target.with_name(target.name + TMP_SUFFIX)
        tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        replace_atomically(tmp, target)

    def skipped(self) -> set[Month]:
        """Return the months never to be frozen (deleted, or without data)."""
        state = self.state()
        found = set()
        for text in (*state["deleted"], *state["empty"]):
            with contextlib.suppress(ArchiveError):
                found.add(Month.parse(text))
        return found

    def manifest(self, month: Month) -> dict[str, Any] | None:
        """Return the manifest of a finished month (cached by file time and size)."""
        path = self.frozen_path(month)
        try:
            stat = path.stat()
        except OSError:
            return None
        key = str(month)
        cached = self._manifests.get(key)
        if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
            return cached[2]
        body = read_zip_manifest(path)
        self._manifests[key] = (stat.st_mtime, stat.st_size, body)
        return body

    def cleanup(self) -> None:
        """Remove temporary files and working copies of months that are finished."""
        if not self.path.is_dir():
            return
        for item in self.path.glob(f"*{TMP_SUFFIX}"):
            item.unlink(missing_ok=True)
        frozen = self.frozen()
        for month, path in self.open_months().items():
            if month in frozen:
                path.unlink(missing_ok=True)
                path.with_name(path.name + "-journal").unlink(missing_ok=True)

    def delete(self, months: Sequence[Month]) -> list[str]:
        """Delete finished months and remember them so they are never frozen again.

        Returns
        -------
        list of str
            The months removed.
        """
        removed = []
        with self.lock:
            for month in months:
                path = self.frozen_path(month)
                if path.exists():
                    path.unlink()
                    removed.append(str(month))
            if removed:
                self.remember("deleted", [Month.parse(text) for text in removed])
        return removed


@dataclass
class ArchiveState:
    """What the last archive step did.

    Parameters
    ----------
    last_run_at
        Wall-clock unix seconds of the last step that succeeded.
    error
        Why the last step failed, if it did.
    behind
        Retention waits: the archive is catching up or freezing a month, or its steps
        fail (for at most :data:`MAX_WAIT_S` from the first failure in a row).
    archived_to
        How far the open month holds the live data.
    failures
        Steps failed in a row.
    failing_since
        Wall-clock unix seconds of the first of those failures.
    """

    last_run_at: float | None = None
    error: str | None = None
    behind: bool = False
    archived_to: float | None = None
    failures: int = 0
    failing_since: float | None = None


class MonthArchiver:
    """Builds and freezes the monthly archive from the history writer's thread.

    Parameters
    ----------
    history
        The live ``history.db``.
    folder
        The archive folder.
    timezone
        IANA time zone of the months.
    enabled
        Whether steps do anything.
    config_source
        Returns ``config.json`` of a window and the versions its decisions used.
    min_free_bytes
        A step is skipped below this much free space.
    disk_free
        Free-space probe.
    budget_s
        Longest a step works before it hands back (catching up and freezing continue
        next time).
    alarm
        Raises (``True``) and clears (``False``) ``archive_failing`` and
        ``archive_rebuilt`` with a message or reason; ``None`` only logs.
    max_wait_s
        Longest retention waits for a failing archive (:data:`MAX_WAIT_S`).
    zip_slice
        Bytes a freeze writes or verifies per slice.
    """

    def __init__(
        self,
        history: Path,
        folder: Path,
        *,
        timezone: str = "UTC",
        enabled: bool = True,
        config_source: ConfigSource | None = None,
        min_free_bytes: int = 0,
        disk_free: Callable[[Path], int] | None = None,
        budget_s: float = BUDGET_S,
        alarm: AlarmHook | None = None,
        max_wait_s: float = MAX_WAIT_S,
        zip_slice: int = ZIP_SLICE_BYTES,
    ) -> None:
        self.history = history
        self.folder = ArchiveFolder(folder)
        self.timezone = timezone
        self.enabled = enabled
        self.config_source = config_source
        self.min_free_bytes = min_free_bytes
        self._disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self.budget_s = budget_s
        self.alarm = alarm
        self.max_wait_s = max_wait_s
        self.zip_slice = zip_slice
        self.state = ArchiveState()
        self._build: ZipBuild | None = None
        self._checked: set[Month] = set()
        self._raised: dict[str, float] = {}

    @property
    def zip_build(self) -> ZipBuild | None:
        """The month's zip being written or verified, if any."""
        return self._build

    def holds_retention(self) -> bool:
        """Whether history retention must wait for the archive (see :class:`ArchiveState`)."""
        return self.enabled and self.state.behind

    def configure(self, *, enabled: bool, timezone: str) -> None:
        """Switch the archive on or off and set the time zone of new months."""
        if enabled != self.enabled:
            LOGGER.info("yearly archive %s", "enabled" if enabled else "disabled")
        self.enabled = enabled
        self.timezone = timezone
        if not enabled:
            self.state.behind = False
            self.state.failures = 0
            self.state.failing_since = None
            self._clear(ALARM_FAILING, "the archive was switched off")

    def step(self, now: float) -> bool:
        """Bring the archive up to ``now`` within the time budget.

        A failure keeps retention waiting (:meth:`holds_retention`) until a step
        succeeds or :attr:`max_wait_s` has passed since the first failure in a row.

        Parameters
        ----------
        now
            Wall-clock unix seconds.

        Returns
        -------
        bool
            ``True`` while it is catching up or freezing (call again soon; retention
            waits); ``False`` when it is done for now or failed (call again after
            :data:`INTERVAL_S`).
        """
        if not self.enabled:
            if self._build is not None:
                with self.folder.lock:
                    self._abort()
            return False
        with self.folder.lock:
            try:
                again = self._step(now)
            except Exception as exc:
                LOGGER.exception("archive step failed")
                self._abort()
                self._failed(now, exc)
                return False
        self._succeeded(now, again)
        return again

    def _abort(self) -> None:
        """Drop an unfinished zip build."""
        if self._build is not None:
            self._build.abort()
            self._build = None

    def _failed(self, now: float, exc: Exception) -> None:
        """Record a failed step and raise the alarms when it persists beyond the wait."""
        state = self.state
        state.error = f"{type(exc).__name__}: {exc}"
        state.failures += 1
        if state.failing_since is None:
            state.failing_since = now
        until = state.failing_since + self.max_wait_s
        waited = state.behind
        state.behind = now < until
        if waited and not state.behind:
            LOGGER.error(
                "archive failing since %s: retention no longer waits for it",
                iso_from_unix(state.failing_since),
            )
        if state.failures >= FAILING_AFTER and ALARM_FAILING not in self._raised:
            self._raise(
                ALARM_FAILING,
                f"the monthly archive failed {state.failures} times in a row since "
                f"{iso_from_unix(state.failing_since)} ({state.error}); history retention "
                f"waits for it until {iso_from_unix(until)}, then removes old data even if "
                "it is not archived",
                now,
            )

    def _succeeded(self, now: float, again: bool) -> None:
        """Record a successful step and clear the failure state and alarm."""
        state = self.state
        if state.failures:
            LOGGER.info("archive works again after %d failed step(s)", state.failures)
        state.last_run_at = now
        state.error = None
        state.behind = again
        state.failures = 0
        state.failing_since = None
        self._clear(ALARM_FAILING, "an archive step succeeded")
        raised = self._raised.get(ALARM_REBUILT)
        if raised is not None and now - raised >= REBUILT_NOTICE_S:
            self._clear(ALARM_REBUILT, f"{REBUILT_NOTICE_S / 3600:.0f} h ago")

    def _raise(self, code: str, message: str, now: float) -> None:
        """Raise an alarm once and tell the alarm hook."""
        self._raised[code] = now
        self._tell(code, True, message)

    def _clear(self, code: str, why: str) -> None:
        """Clear an alarm that was raised and tell the alarm hook."""
        if self._raised.pop(code, None) is not None:
            self._tell(code, False, why)

    def _tell(self, code: str, active: bool, text: str) -> None:
        """Pass an alarm change to the hook, logging a failing hook."""
        if self.alarm is None:
            return
        try:
            self.alarm(code, active, text)
        except Exception:
            LOGGER.exception("archive alarm %s could not be passed on", code)

    def _step(self, now: float) -> bool:
        """Run one archive step within its time budget; return whether more work remains.

        Parameters
        ----------
        now
            Current Unix time.
        """
        if not self.history.exists():
            return False
        self.folder.path.mkdir(parents=True, exist_ok=True)
        free = self._disk_free(self.folder.path)
        if free < self.min_free_bytes:
            raise OSError(f"only {free // 2**20} MB free in the data directory")
        deadline = time.monotonic() + self.budget_s
        if self._build is not None and not self._run_build(deadline):
            return True
        self.folder.cleanup()
        target = now - LAG_S
        pending = set(self.folder.open_months())
        first = first_data(self.history)
        if first is not None and first < target:
            done = set(self.folder.frozen()) | self.folder.skipped()
            span = months_between(Month.of(first, self.timezone), Month.of(target, self.timezone))
            pending |= {month for month in span if month not in done}
        return any(not self._advance(month, target, deadline, now) for month in sorted(pending))

    def _run_build(self, deadline: float) -> bool:
        """Continue the zip build until ``deadline``; return whether it finished."""
        build = self._build
        if build is None:
            return True
        if not build.run(deadline):
            return False
        self._build = None
        LOGGER.info("archive: %s frozen (complete: %s)", build.month, build.manifest["complete"])
        return True

    def _quarantine(self, month: Month, path: Path, why: str, now: float) -> None:
        """Move a damaged working copy aside, so it is rebuilt from the live history.

        Parameters
        ----------
        month
            Month of the damaged copy.
        path
            Damaged working copy.
        why
            What was found wrong with it.
        now
            Current Unix time.
        """
        moved = quarantine(path)
        LOGGER.error(
            "archive: the working copy of %s is damaged (%s); moved to %s, rebuilding it "
            "from history.db",
            month,
            why,
            moved.name,
        )
        self._raise(
            ALARM_REBUILT,
            f"the working copy of {month} was damaged ({why}); it was moved to "
            f"archive/{moved.name} and rebuilt from what history.db still holds, so days "
            "that retention already removed are missing from that month",
            now,
        )

    def _advance(self, month: Month, target: float, deadline: float, now: float) -> bool:
        """Bring a month's working copy up to ``target``, rebuilding a damaged one.

        Parameters
        ----------
        month
            Month to work on.
        target
            Unix time up to which the live history is copied.
        deadline
            ``time.monotonic()`` time at which to stop.
        now
            Current Unix time.
        """
        path = self.folder.open_path(month)
        if month not in self._checked:
            why = damaged(path) if path.exists() else None
            self._checked.add(month)
            if why is not None:
                self._quarantine(month, path, why, now)
        try:
            return self._fill(month, path, target, deadline, now)
        except sqlite3.OperationalError:
            raise
        except sqlite3.DatabaseError as exc:
            why = damaged(path) if path.exists() else None
            if why is None:
                raise
            LOGGER.warning("archive: %s failed on its working copy: %s", month, exc)
            self._quarantine(month, path, why, now)
            return False

    def _fill(self, month: Month, path: Path, target: float, deadline: float, now: float) -> bool:
        """Copy the live history of a month into its working copy, freezing it when complete.

        Parameters
        ----------
        month
            Month to work on.
        path
            Working copy of the month.
        target
            Unix time up to which the live history is copied.
        deadline
            ``time.monotonic()`` time at which to stop.
        now
            Current Unix time.
        """
        conn = open_month(path)
        closed = False
        try:
            meta = read_meta(conn)
            if "start" in meta:
                start, end = float(meta["start"]), float(meta["end"])
                timezone = meta.get("timezone", self.timezone)
                mark = float(meta["watermark"])
            else:
                timezone = self.timezone
                start, end = month.bounds(timezone)
                mark = start
                _set_meta(
                    conn,
                    {
                        "month": month,
                        "timezone": timezone,
                        "start": start,
                        "end": end,
                        "watermark": mark,
                    },
                )
            live = f"{self.history.resolve().as_uri()}?mode=ro"
            conn.execute("ATTACH DATABASE ? AS live", (live,))
            while mark < min(end, target):
                lo = max(start, mark - REWIND_S)
                hi = min(end, target, mark + CHUNK_S)
                self._copy(conn, lo, hi, target, hi)
                mark = hi
                if end > target:
                    self.state.archived_to = mark
                if time.monotonic() >= deadline and mark < min(end, target):
                    return False
            if target < end + REWIND_S:
                return True
            self._copy(conn, max(start, end - REWIND_S), end, target, end)
            conn.execute("DETACH DATABASE live")
            closed = True
            if not self._freeze(month, conn, path, timezone, (start, end), target, now):
                return False
            return self._run_build(deadline)
        finally:
            if not closed:
                conn.close()

    @staticmethod
    def _copy(conn: sqlite3.Connection, lo: float, hi: float, settled: float, mark: float) -> None:
        """Copy one window into the working copy and move its watermark, in one transaction.

        Parameters
        ----------
        conn
            Open connection to the working copy with the live history attached.
        lo
            Start of the window, Unix time (inclusive).
        hi
            End of the window, Unix time (exclusive).
        settled
            Unix time before which rollup buckets are final.
        mark
            Watermark to store: the time up to which the copy is complete.
        """
        conn.execute("BEGIN")
        try:
            copy_window(conn, lo, hi, settled)
            _set_meta(conn, {"watermark": mark})
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise

    def _freeze(
        self,
        month: Month,
        conn: sqlite3.Connection,
        path: Path,
        timezone: str,
        bounds: tuple[float, float],
        created: float,
        now: float,
    ) -> bool:
        """Check the finished working copy and start its :class:`ZipBuild`.

        Parameters
        ----------
        month
            Month that ended.
        conn
            Open connection to its working copy.
        path
            Working copy file.
        timezone
            Timezone the month's days follow.
        bounds
            Start and end of the month as Unix times.
        created
            Unix time recorded as the manifest's creation time.
        now
            Current Unix time.

        Returns
        -------
        bool
            ``False`` when the copy was damaged and moved aside (it is rebuilt next
            time); ``True`` otherwise (its zip build started, or it holds no data).
        """
        try:
            why = damage(conn)
            if why is None:
                source = self.config_source
                manifest = month_manifest(
                    conn,
                    month,
                    timezone,
                    bounds,
                    created=created,
                    frozen=True,
                    config=source is not None,
                )
                empty = not any(item["rows"] for item in manifest["coverage"].values())
                config = None
                if not empty and source is not None:
                    config = source(bounds[0], bounds[1], used_versions(conn))
        finally:
            conn.close()
        if why is not None:
            self._quarantine(month, path, why, now)
            return False
        if empty:
            self.folder.remember("empty", [month])
            LOGGER.info("archive: %s holds no data; nothing to freeze", month)
            path.unlink(missing_ok=True)
            path.with_name(path.name + "-journal").unlink(missing_ok=True)
            return True
        needed = self.min_free_bytes + path.stat().st_size
        free = self._disk_free(self.folder.path)
        if free < needed:
            raise OSError(
                f"freezing {month} needs {needed // 2**20} MB free, {free // 2**20} MB left"
            )
        self._build = ZipBuild(
            month, path, self.folder.frozen_path(month), manifest, config, self.zip_slice
        )
        return True


def open_month_manifest(
    path: Path, month: Month, timezone: str, created: float, *, config: bool
) -> dict[str, Any]:
    """Return the manifest of an open month's working copy (``frozen`` false).

    Parameters
    ----------
    path
        Working copy of the month.
    month
        Month the copy belongs to.
    timezone
        Timezone used when the copy records none.
    created
        Unix time recorded as the manifest's creation time.
    config
        Whether the zip will carry a configuration file.
    """
    conn = read_only(path)
    try:
        meta = read_meta(conn)
        zone = meta.get("timezone", timezone)
        bounds = (
            (float(meta["start"]), float(meta["end"])) if "start" in meta else month.bounds(zone)
        )
        until = float(meta["watermark"]) if "watermark" in meta else created
        return month_manifest(
            conn, month, zone, bounds, created=created, frozen=False, config=config, until=until
        )
    finally:
        conn.close()


def write_open_month(
    source: Path,
    folder: Path,
    month: Month,
    timezone: str,
    created: float,
    config_source: ConfigSource | None,
) -> Path:
    """Write a zip of an open month as it stands into ``folder`` and return its path.

    Parameters
    ----------
    source
        Working copy of the open month.
    folder
        Folder to write the zip into.
    month
        Month of the copy.
    timezone
        Timezone used when the copy records none.
    created
        Unix time recorded as the manifest's creation time.
    config_source
        Provides the configuration to include; ``None`` for none.
    """
    copy = folder / "history.db"
    backup_to(source, copy)
    config = None
    if config_source is not None:
        conn = sqlite3.connect(copy)
        try:
            meta = read_meta(conn)
            versions = used_versions(conn)
        finally:
            conn.close()
        zone = meta.get("timezone", timezone)
        start, end = (
            (float(meta["start"]), float(meta["end"])) if "start" in meta else month.bounds(zone)
        )
        config = config_source(start, end, versions)
    manifest = open_month_manifest(copy, month, timezone, created, config=config is not None)
    target = folder / f"{month}{FROZEN_SUFFIX}"
    write_month_zip(copy, target, manifest, config)
    copy.unlink()
    return target


def bundle_manifest(
    kind: str,
    period: str,
    months: Sequence[Month],
    found: Mapping[Month, tuple[Path, dict[str, Any] | None]],
    timezone: str,
    created: float,
) -> dict[str, Any]:
    """Return the combined manifest of a year or season.

    Parameters
    ----------
    kind
        ``year`` or ``season``.
    period
        ``2026`` or ``2026/27``.
    months
        Every month of the period.
    found
        The finished months present: file and manifest.
    timezone
        Time zone of the bounds.
    created
        When the bundle is written.
    """
    items = []
    for month in months:
        if month not in found:
            continue
        path, manifest = found[month]
        cover = (manifest or {}).get("coverage", {})
        minute = cover.get("60", {})
        items.append(
            {
                "period": str(month),
                "file": path.name,
                "bytes": path.stat().st_size,
                "complete": bool((manifest or {}).get("complete")),
                "days": minute.get("days"),
                "days_total": len(month.days()),
            }
        )
    present = [Month.parse(item["period"]) for item in items]
    start = months[0].bounds(timezone)[0]
    end = months[-1].bounds(timezone)[1]
    return {
        "ovenbird_archive": ARCHIVE_FORMAT,
        "kind": kind,
        "period": period,
        "timezone": timezone,
        "from": iso_from_unix(start),
        "to": iso_from_unix(end),
        "app_version": __version__,
        "created_at": iso_from_unix(created),
        "months": items,
        "missing_months": [str(month) for month in months if month not in found],
        "coverage": {
            "months": len(items),
            "of": len(months),
            "first": str(present[0]) if present else None,
            "last": str(present[-1]) if present else None,
        },
        "partial": len(items) < len(months) or not all(item["complete"] for item in items),
        "notice": ARCHIVE_NOTICE,
    }


def write_bundle(target: Path, files: Sequence[Path], manifest: Mapping[str, Any]) -> None:
    """Write a zip of month files (stored as they are) and the combined manifest."""
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as zf:
        for path in files:
            zf.write(path, path.name)
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2) + "\n",
            compress_type=zipfile.ZIP_DEFLATED,
        )


def month_item(
    folder: ArchiveFolder, month: Month, path: Path, *, frozen: bool, timezone: str
) -> dict[str, Any]:
    """Return one entry of ``months`` in ``GET api/v1/archive``.

    Parameters
    ----------
    folder
        Archive folder the month is in.
    month
        Month described.
    path
        File of the month.
    frozen
        Whether the month is finished and frozen.
    timezone
        Timezone the days of the month follow.
    """
    size = path.stat().st_size
    item: dict[str, Any] = {
        "period": str(month),
        "state": "frozen" if frozen else "open",
        "bytes": size,
        "days_total": len(month.days()),
    }
    if frozen:
        manifest = folder.manifest(month) or {}
        cover = manifest.get("coverage", {})
        minute = cover.get("60", {})
        decisions = cover.get("decisions", {})
        item.update(
            {
                "from": manifest.get("from"),
                "to": manifest.get("to"),
                "complete": bool(manifest.get("complete")),
                "days": minute.get("days"),
                "decision_days": decisions.get("days"),
                "missing_days": len(minute.get("missing_days", [])),
                "created_at": manifest.get("created_at"),
                "archived_to": manifest.get("to"),
            }
        )
        return item
    conn = read_only(path)
    try:
        meta = read_meta(conn)
    finally:
        conn.close()
    zone = meta.get("timezone", timezone)
    start, end = (
        (float(meta["start"]), float(meta["end"])) if "start" in meta else month.bounds(zone)
    )
    item.update(
        {
            "from": iso_from_unix(start),
            "to": iso_from_unix(end),
            "complete": None,
            "days": None,
            "decision_days": None,
            "missing_days": None,
            "created_at": None,
            "archived_to": (
                iso_from_unix(float(meta["watermark"])) if "watermark" in meta else None
            ),
        }
    )
    return item


def _group(
    kind: str, period: str, ident: str, months: Sequence[Month], items: Mapping[Month, Any]
) -> dict[str, Any] | None:
    """Return one download group (a year or all months) over the months present, or ``None``.

    Parameters
    ----------
    kind
        Group kind, ``year`` or ``all``.
    period
        Period text of the group.
    ident
        Group id.
    months
        Months the group covers.
    items
        Month entries by month.
    """
    present = [items[month] for month in months if month in items]
    frozen = [item for item in present if item["state"] == "frozen"]
    if not present:
        return None
    return {
        "id": ident,
        "kind": kind,
        "period": period,
        "months": [item["period"] for item in frozen],
        "open_months": [item["period"] for item in present if item["state"] == "open"],
        "of": len(months),
        "bytes": sum(item["bytes"] for item in frozen),
        "complete": len(frozen) == len(months) and all(item["complete"] for item in frozen),
        "first": frozen[0]["period"] if frozen else None,
        "last": frozen[-1]["period"] if frozen else None,
    }


def listing(folder: ArchiveFolder, timezone: str) -> dict[str, Any]:
    """Return the stored months and their years and seasons (newest first).

    Returns
    -------
    dict
        ``months``, ``years``, ``seasons``, ``total_bytes`` and ``bytes_per_year``
        (the finished months' size per day with 1 min data, times 365; ``None``
        without one).
    """
    items: dict[Month, dict[str, Any]] = {}
    for month, path in folder.frozen().items():
        with contextlib.suppress(OSError):
            items[month] = month_item(folder, month, path, frozen=True, timezone=timezone)
    for month, path in folder.open_months().items():
        if month in items:
            continue
        with contextlib.suppress(OSError, sqlite3.Error):
            items[month] = month_item(folder, month, path, frozen=False, timezone=timezone)
    ordered = dict(sorted(items.items()))
    years = sorted({month.year for month in ordered}, reverse=True)
    seasons = sorted({month.season for month in ordered}, reverse=True)
    frozen = [item for item in ordered.values() if item["state"] == "frozen"]
    covered = sum(item["days"] or 0 for item in frozen)
    return {
        "months": list(reversed(ordered.values())),
        "years": [
            group
            for year in years
            if (group := _group("year", str(year), str(year), year_months(year), ordered))
        ],
        "seasons": [
            group
            for start in seasons
            if (
                group := _group(
                    "season",
                    season_label(start),
                    season_id(start),
                    season_months(start),
                    ordered,
                )
            )
        ],
        "total_bytes": sum(item["bytes"] for item in ordered.values()),
        "bytes_per_year": round(sum(item["bytes"] for item in frozen) / covered * 365)
        if covered
        else None,
    }
