"""Control journal in ``history.db``: decisions, commands, alarms and controller state.

Tables ``decision``, ``command``, ``alarm`` (alarm and hold transitions) and
``control_state`` (one row per key, replaced on every write: the controller state
that survives a restart).

Rows are written by the history writer thread (see :mod:`ovenbird.history.writer`)
and read by the API through read-only connections. A decision row stores the
controller's :class:`~ovenbird_core.control.DecisionRecord` JSON exactly as
:meth:`~ovenbird_core.control.DecisionRecord.to_json_dict` produces it, plus the
arbiter's decisions and the command events of that tick; the three texts are kept
compressed in one BLOB (:mod:`ovenbird.history.packing`) and read back unchanged.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.history.packing import DecisionPacker, unpacker
from ovenbird.history.schema import connect
from ovenbird.sql import sql

MAX_LIMIT: Final = 5000
MAX_REPLAY: Final = 20_000

HOLD_CODE: Final = "command_hold"
HOLD_RELEASED: Final = "released"
DECISION_COLUMNS: Final = (
    "ts, controller, mode, ladder, reason, setpoint, config_version, dictionary_id, body"
)
TEXT_DECISION_COLUMNS: Final = (
    "ts, controller, mode, ladder, reason, setpoint, config_version, record, arbiter, commands"
)
LEGACY_DECISION_COLUMNS: Final = (
    "ts, controller, mode, ladder, reason, setpoint, NULL, record, arbiter, commands"
)
EXPORT_BATCH: Final = 500
SERIES_STEPS: Final = (0, 300, 900, 3600)
TICK_S: Final = 60.0
MAX_SERIES_POINTS: Final = 1500
MAX_RAW_SERIES: Final = 5000
OTHER_TERMS: Final = ("boost", "override")
SERIES_TERMS: Final = ("curve", "room_feedback", "plan", "start_ramp", "cycling_floor")
STOVE_TERM: Final = "stove"
COMMAND_COLUMNS: Final = "ts, kind, value, status, attempt, topic, payload, detail"
ALARM_COLUMNS: Final = "ts, code, severity, event, message, detail"


@dataclass(frozen=True, slots=True)
class DecisionRow:
    """One controller tick as stored.

    Parameters
    ----------
    ts
        Wall-clock unix seconds of the tick.
    controller, mode, ladder, reason
        Summary columns of the record.
    setpoint
        Desired water setpoint.
    record
        Decision record JSON text.
    arbiter
        JSON list of the arbiter's decisions.
    commands
        JSON list of the command events of the tick.
    config_version
        Configuration version the tick ran with (``None`` before the store existed).
    """

    ts: float
    controller: str
    mode: str
    ladder: str
    reason: str
    setpoint: int | None
    record: str
    arbiter: str
    commands: str
    config_version: int | None = None

    def payload(self) -> dict[str, Any]:
        """Return the API form (see ``docs/api-v1.md``)."""
        record = json.loads(self.record)
        return {
            "at": iso_from_unix(self.ts),
            "controller": self.controller,
            "mode": self.mode,
            "ladder": self.ladder,
            "reason": self.reason,
            "setpoint": self.setpoint,
            "note": record.get("note"),
            "arbiter": json.loads(self.arbiter),
            "commands": json.loads(self.commands),
            "config_version": self.config_version,
            "record": record,
        }


@dataclass(frozen=True, slots=True)
class CommandRow:
    """One command event as stored.

    Parameters
    ----------
    ts
        Wall-clock unix seconds.
    kind, value, status, attempt, topic, payload, detail
        Event fields.
    """

    ts: float
    kind: str
    value: int
    status: str
    attempt: int
    topic: str | None
    payload: str | None
    detail: str

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "at": iso_from_unix(self.ts),
            "kind": self.kind,
            "value": self.value,
            "status": self.status,
            "attempt": self.attempt,
            "topic": self.topic,
            "payload": self.payload,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class AlarmRow:
    """One alarm or hold transition as stored.

    Parameters
    ----------
    ts
        Wall-clock unix seconds.
    code
        Alarm code, or ``command_hold``.
    severity
        ``info``, ``warning`` or ``critical``.
    event
        ``raised``, ``cleared``, ``started``, ``expired`` or ``released``.
    message
        Human explanation.
    detail
        JSON object text.
    """

    ts: float
    code: str
    severity: str
    event: str
    message: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "at": iso_from_unix(self.ts),
            "code": self.code,
            "severity": self.severity,
            "event": self.event,
            "message": self.message,
            "detail": json.loads(self.detail),
        }


@dataclass(frozen=True, slots=True)
class StateRow:
    """One ``control_state`` entry.

    Parameters
    ----------
    key
        Entry name (``controller``).
    ts
        Wall-clock unix seconds of the write.
    value
        JSON text.
    """

    key: str
    ts: float
    value: str


def write_journal(
    conn: sqlite3.Connection,
    decisions: Sequence[DecisionRow],
    commands: Sequence[CommandRow],
    alarms: Sequence[AlarmRow] = (),
    states: Sequence[StateRow] = (),
    packer: DecisionPacker | None = None,
) -> int:
    """Insert rows in one transaction; returns the number of rows written.

    Of several state rows with the same key only the last one is kept. ``packer``
    keeps the decision dictionary between calls (a fresh one reads the newest
    stored dictionary).

    Parameters
    ----------
    conn
        Open history database connection.
    decisions
        Decision rows to insert.
    commands
        Command rows to insert.
    alarms
        Alarm rows to insert.
    states
        State rows to upsert.
    packer
        Decision packer keeping the compression dictionary between calls.
    """
    latest = {row.key: row for row in states}
    if not decisions and not commands and not alarms and not latest:
        return 0
    packing = packer or DecisionPacker()
    conn.execute("BEGIN")
    try:
        packed = []
        for d in decisions:
            dictionary_id, body = packing.pack(conn, d.ts, d.record, d.arbiter, d.commands)
            packed.append(
                (
                    d.ts,
                    d.controller,
                    d.mode,
                    d.ladder,
                    d.reason,
                    d.setpoint,
                    d.config_version,
                    dictionary_id,
                    body,
                )
            )
        conn.executemany(
            sql(
                "INSERT INTO decision ({columns}) VALUES ({marks})",
                columns=DECISION_COLUMNS,
                marks=9,
            ),
            packed,
        )
        conn.executemany(
            sql(
                "INSERT INTO command ({columns}) VALUES ({marks})", columns=COMMAND_COLUMNS, marks=8
            ),
            [
                (c.ts, c.kind, c.value, c.status, c.attempt, c.topic, c.payload, c.detail)
                for c in commands
            ],
        )
        conn.executemany(
            sql("INSERT INTO alarm ({columns}) VALUES ({marks})", columns=ALARM_COLUMNS, marks=6),
            [(a.ts, a.code, a.severity, a.event, a.message, a.detail) for a in alarms],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO control_state (key, ts, value) VALUES (?, ?, ?)",
            [(row.key, row.ts, row.value) for row in latest.values()],
        )
        conn.execute("COMMIT")
    except BaseException:
        packing.forget()
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return len(decisions) + len(commands) + len(alarms) + len(latest)


def delete_journal_before(conn: sqlite3.Connection, cutoff: float) -> int:
    """Delete decision, command and alarm rows older than ``cutoff``; returns rows deleted.

    The command-hold rows since the last release (:data:`HOLD_CODE`, event
    :data:`HOLD_RELEASED`) stay whatever their age: a restart rebuilds the hold and its
    escalation count from them, so a latched hold is never forgotten. Decision
    dictionaries no row uses any more are dropped as well (the newest one always stays).
    """
    deleted = conn.execute("DELETE FROM decision WHERE ts < ?", (cutoff,)).rowcount
    deleted += conn.execute("DELETE FROM command WHERE ts < ?", (cutoff,)).rowcount
    deleted += conn.execute(
        "DELETE FROM alarm WHERE ts < ? AND NOT (code = ? AND ts >= coalesce("
        "(SELECT max(ts) FROM alarm WHERE code = ? AND event = ?), -1e308))",
        (cutoff, HOLD_CODE, HOLD_CODE, HOLD_RELEASED),
    ).rowcount
    if deleted:
        conn.execute(
            "DELETE FROM decision_dictionary "
            "WHERE id < (SELECT max(id) FROM decision_dictionary) "
            "AND id NOT IN (SELECT DISTINCT dictionary_id FROM decision "
            "WHERE dictionary_id IS NOT NULL)"
        )
    return deleted


def _open(path: Path, table: str) -> sqlite3.Connection | None:
    """Return a read-only connection when the file has the table, else ``None``."""
    if not path.exists():
        return None
    conn = connect(path, read_only=True)
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if found is None:
        conn.close()
        return None
    return conn


def _decision_columns(conn: sqlite3.Connection) -> str:
    """Return the decision column list the database's schema generation has."""
    names = {row[1] for row in conn.execute("PRAGMA table_info(decision)")}
    if "body" in names:
        return DECISION_COLUMNS
    return TEXT_DECISION_COLUMNS if "config_version" in names else LEGACY_DECISION_COLUMNS


def decision_rows(conn: sqlite3.Connection, rows: Sequence[Sequence[Any]]) -> list[DecisionRow]:
    """Turn rows selected with the decision columns into decision rows, texts unpacked.

    Parameters
    ----------
    conn
        The connection the rows were read with (for the dictionaries).
    rows
        Selected rows in the order to keep.

    Returns
    -------
    list of DecisionRow
        One per row.
    """
    unpack = unpacker(conn)
    found: list[DecisionRow] = []
    for row in rows:
        ts, controller, mode, ladder, reason, setpoint, config_version, *rest = row
        if len(rest) == 2:
            record, arbiter, commands = unpack(rest[1], rest[0])
        else:
            record, arbiter, commands = rest
        found.append(
            DecisionRow(
                ts,
                controller,
                mode,
                ladder,
                reason,
                setpoint,
                record,
                arbiter,
                commands,
                config_version,
            )
        )
    return found


def query_decisions(path: Path, start: float, end: float, limit: int) -> list[DecisionRow]:
    """Return the newest ``limit`` decisions in ``[start, end)``, oldest first.

    Parameters
    ----------
    path
        History database file.
    start
        Start of the window, Unix time (inclusive).
    end
        End of the window, Unix time (exclusive).
    limit
        Maximum number of rows.
    """
    conn = _open(path, "decision")
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM decision WHERE ts >= ? AND ts < ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                columns=_decision_columns(conn),
            ),
            (start, end, min(limit, MAX_LIMIT)),
        ).fetchall()
        return decision_rows(conn, rows[::-1])
    finally:
        conn.close()


def iter_decisions(
    path: Path, start: float, end: float, batch: int = EXPORT_BATCH
) -> Iterator[DecisionRow]:
    """Yield every decision in ``[start, end)``, oldest first, reading ``batch`` rows at a time.

    Each batch is its own short read, so a slow consumer never holds the database.

    Parameters
    ----------
    path
        History database file.
    start
        Start of the window, Unix time (inclusive).
    end
        End of the window, Unix time (exclusive).
    batch
        Rows per read.
    """
    conn = _open(path, "decision")
    if conn is None:
        return
    try:
        select = _decision_columns(conn)
        after: tuple[float, int] = (start, -1)
        while True:
            rows = conn.execute(
                sql(
                    "SELECT {columns}, id FROM decision WHERE ts >= ? AND ts < ? "
                    "AND (ts > ? OR (ts = ? AND id > ?)) ORDER BY ts, id LIMIT ?",
                    columns=select,
                ),
                (start, end, after[0], after[0], after[1], batch),
            ).fetchall()
            if not rows:
                return
            after = (float(rows[-1][0]), int(rows[-1][-1]))
            yield from decision_rows(conn, [row[:-1] for row in rows])
            if len(rows) < batch:
                return
    finally:
        conn.close()


def decisions_between(
    path: Path, start: float, end: float, limit: int = MAX_REPLAY
) -> list[DecisionRow]:
    """Return every decision in ``[start, end)`` (at most the newest ``limit``), oldest first.

    Parameters
    ----------
    path
        History database file.
    start
        Start of the window, Unix time (inclusive).
    end
        End of the window, Unix time (exclusive).
    limit
        Maximum number of rows.
    """
    conn = _open(path, "decision")
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM decision WHERE ts >= ? AND ts < ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                columns=_decision_columns(conn),
            ),
            (start, end, limit),
        ).fetchall()
        return decision_rows(conn, rows[::-1])
    finally:
        conn.close()


def decision_before(path: Path, ts: float) -> DecisionRow | None:
    """Return the newest decision before ``ts``, if any."""
    conn = _open(path, "decision")
    if conn is None:
        return None
    try:
        row = conn.execute(
            sql(
                "SELECT {columns} FROM decision WHERE ts < ? ORDER BY ts DESC, id DESC LIMIT 1",
                columns=_decision_columns(conn),
            ),
            (ts,),
        ).fetchone()
        return None if row is None else decision_rows(conn, [row])[0]
    finally:
        conn.close()


def decision_state_series(
    path: Path, key: str, start: float, end: float, step: int
) -> list[tuple[float, float]]:
    """Return one numeric controller-state value (last tick per ``step`` bucket) over a window.

    Parameters
    ----------
    path
        History database.
    key
        Key of the decision's ``controller_state`` (``outside_filtered_c``).
    start, end
        Window in unix seconds.
    step
        Bucket length in seconds (positive).

    Returns
    -------
    list of tuple
        ``(bucket start, value)`` for every bucket with a numeric value, oldest first.
    """
    conn = _open(path, "decision")
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM decision "
                "WHERE id IN (SELECT MAX(id) FROM decision WHERE ts >= ? AND ts < ? "
                "GROUP BY CAST(ts / ? AS INTEGER)) ORDER BY ts, id",
                columns=_decision_columns(conn),
            ),
            (start, end, step),
        ).fetchall()
        decisions = decision_rows(conn, rows)
    finally:
        conn.close()
    found: list[tuple[float, float]] = []
    for row in decisions:
        state = json.loads(row.record).get("controller_state") or {}
        value = state.get(key) if isinstance(state, dict) else None
        if isinstance(value, int | float) and not isinstance(value, bool):
            found.append((float(int(row.ts / step) * step), float(value)))
    return found


def latest_decision(path: Path) -> DecisionRow | None:
    """Return the most recent decision, if any."""
    conn = _open(path, "decision")
    if conn is None:
        return None
    try:
        row = conn.execute(
            sql(
                "SELECT {columns} FROM decision ORDER BY ts DESC, id DESC LIMIT 1",
                columns=_decision_columns(conn),
            )
        ).fetchone()
        return None if row is None else decision_rows(conn, [row])[0]
    finally:
        conn.close()


def series_step(start: float, end: float) -> int:
    """Return the finest series step that keeps ``[start, end)`` within 1,500 points."""
    for step in SERIES_STEPS:
        if (end - start) / (step or TICK_S) <= MAX_SERIES_POINTS:
            return step
    return SERIES_STEPS[-1]


def query_decision_series(path: Path, start: float, end: float, step: int) -> dict[str, list[Any]]:
    """Return the decision terms in ``[start, end)`` as columns, oldest first.

    Parameters
    ----------
    path
        History database.
    start, end
        Window in unix seconds.
    step
        ``0`` for every tick (the newest 5,000), or 300/900/3600 for the last tick
        of each bucket.

    Returns
    -------
    dict
        One list per column of ``GET api/v1/decisions/series`` (without ``from``,
        ``to`` and ``step``); ``at`` holds unix seconds.

    Raises
    ------
    ValueError
        For a step that is not one of 0, 300, 900 and 3600.
    """
    if step not in SERIES_STEPS:
        raise ValueError(f"step must be one of {', '.join(map(str, SERIES_STEPS))}")
    columns: dict[str, list[Any]] = {name: [] for name in SERIES_COLUMNS}
    conn = _open(path, "decision")
    if conn is None:
        return columns
    select = _decision_columns(conn)
    try:
        if step == 0:
            rows = conn.execute(
                sql(
                    "SELECT {columns} FROM decision WHERE ts >= ? AND ts < ? "
                    "ORDER BY ts DESC, id DESC LIMIT ?",
                    columns=select,
                ),
                (start, end, MAX_RAW_SERIES),
            ).fetchall()
            rows.reverse()
        else:
            rows = conn.execute(
                sql(
                    "SELECT {columns} FROM decision WHERE id IN ("
                    "SELECT MAX(id) FROM decision WHERE ts >= ? AND ts < ? "
                    "GROUP BY CAST(ts / ? AS INTEGER)) ORDER BY ts, id",
                    columns=select,
                ),
                (start, end, step),
            ).fetchall()
        decisions = decision_rows(conn, rows)
    finally:
        conn.close()
    for row in decisions:
        _append_series(columns, row)
    return columns


SERIES_COLUMNS: Final = (
    "at",
    "setpoint",
    "pre_round",
    *SERIES_TERMS,
    STOVE_TERM,
    "other",
    "safety_delta",
    "safety_low",
    "safety_high",
    "reason",
    "binding",
    "ladder",
    "config_version",
)


def _term_values(record: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Return the ``(raw, value)`` of every term of a decision record by name."""
    found: dict[str, tuple[Any, Any]] = {}
    for term in record.get("terms") or ():
        if isinstance(term, dict) and isinstance(term.get("name"), str):
            found[term["name"]] = (term.get("raw"), term.get("value"))
    return found


def _append_series(columns: dict[str, list[Any]], row: DecisionRow) -> None:
    """Append one decision's values to the series columns.

    Parameters
    ----------
    columns
        Series columns by name, appended to in place.
    row
        Decision row to take the values from.
    """
    record = json.loads(row.record)
    terms = _term_values(record)
    state = record.get("controller_state") or {}
    controlled = "safety" in terms
    columns["at"].append(row.ts)
    columns["setpoint"].append(row.setpoint)
    columns["pre_round"].append(record.get("pre_round"))
    for name in SERIES_TERMS:
        columns[name].append(terms[name][1] if name in terms else None)
    stove = terms[STOVE_TERM][1] if STOVE_TERM in terms else 0.0
    columns[STOVE_TERM].append(stove if controlled else None)
    others = [terms[name][1] for name in OTHER_TERMS if name in terms]
    columns["other"].append(sum(others) if controlled else None)
    safety = terms.get("safety")
    delta = None
    if safety is not None and safety[0] is not None and safety[1] is not None:
        delta = safety[1] - safety[0]
    columns["safety_delta"].append(delta)
    columns["safety_low"].append(state.get("safety_low_c") if controlled else None)
    columns["safety_high"].append(state.get("safety_high_c") if controlled else None)
    columns["reason"].append(row.reason)
    columns["binding"].append(record.get("binding"))
    columns["ladder"].append(row.ladder)
    columns["config_version"].append(row.config_version)


def query_commands(path: Path, start: float, end: float, limit: int) -> list[CommandRow]:
    """Return the newest ``limit`` command events in ``[start, end)``, oldest first.

    Parameters
    ----------
    path
        History database file.
    start
        Start of the window, Unix time (inclusive).
    end
        End of the window, Unix time (exclusive).
    limit
        Maximum number of rows.
    """
    conn = _open(path, "command")
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM command WHERE ts >= ? AND ts < ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                columns=COMMAND_COLUMNS,
            ),
            (start, end, min(limit, MAX_LIMIT)),
        ).fetchall()
    finally:
        conn.close()
    return [CommandRow(*row) for row in reversed(rows)]


def query_alarms(path: Path, start: float, end: float, limit: int) -> list[AlarmRow]:
    """Return the newest ``limit`` alarm transitions in ``[start, end)``, oldest first.

    Parameters
    ----------
    path
        History database file.
    start
        Start of the window, Unix time (inclusive).
    end
        End of the window, Unix time (exclusive).
    limit
        Maximum number of rows.
    """
    conn = _open(path, "alarm")
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM alarm WHERE ts >= ? AND ts < ? "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                columns=ALARM_COLUMNS,
            ),
            (start, end, min(limit, MAX_LIMIT)),
        ).fetchall()
    finally:
        conn.close()
    return [AlarmRow(*row) for row in reversed(rows)]


def alarms_since(path: Path, code: str, start: float) -> list[AlarmRow]:
    """Return every transition of ``code`` at or after ``start``, oldest first."""
    conn = _open(path, "alarm")
    if conn is None:
        return []
    try:
        rows = conn.execute(
            sql(
                "SELECT {columns} FROM alarm WHERE code = ? AND ts >= ? ORDER BY ts, id",
                columns=ALARM_COLUMNS,
            ),
            (code, start),
        ).fetchall()
    finally:
        conn.close()
    return [AlarmRow(*row) for row in rows]


def count_sent(path: Path, start: float, end: float) -> int:
    """Return the number of ``sent`` command events in ``[start, end)``."""
    conn = _open(path, "command")
    if conn is None:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM command WHERE status = 'sent' AND ts >= ? AND ts < ?",
            (start, end),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0])


def command_events_of(
    path: Path, kinds: Sequence[str], start: float, end: float, status: str | None = None
) -> list[CommandRow]:
    """Return the command events of ``kinds`` in ``[start, end)``, oldest first.

    Parameters
    ----------
    path
        History database.
    kinds
        Command kinds (``heat_delta``, ...).
    start, end
        Window in unix seconds.
    status
        Only events with this status, when given.

    Returns
    -------
    list of CommandRow
        At most :data:`MAX_LIMIT` rows (the newest).
    """
    conn = _open(path, "command")
    if conn is None or not kinds:
        if conn is not None:
            conn.close()
        return []
    query = sql(
        "SELECT {columns} FROM command WHERE kind IN ({marks}) AND ts >= ? AND ts < ?",
        columns=COMMAND_COLUMNS,
        marks=len(kinds),
    )
    params: list[Any] = [*kinds, start, end]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    try:
        rows = conn.execute(
            query + " ORDER BY ts DESC, id DESC LIMIT ?", (*params, MAX_LIMIT)
        ).fetchall()
    finally:
        conn.close()
    return [CommandRow(*row) for row in reversed(rows)]


def read_state(path: Path, key: str) -> StateRow | None:
    """Return the ``control_state`` entry ``key``, if stored."""
    conn = _open(path, "control_state")
    if conn is None:
        return None
    try:
        row = conn.execute(
            "SELECT key, ts, value FROM control_state WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else StateRow(*row)
