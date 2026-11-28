"""SQLite result database of the open-loop run.

Every table carries a ``run`` column, so one file can hold several runs (for example
several controllers). ``decisions.record`` holds exactly
:meth:`~ovenbird_core.control.DecisionRecord.to_json_dict` serialised with sorted
keys — the format of the live decision log. ``meta`` holds JSON values.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Final, Self

from ovenbird_core.control.protocol import StepResult
from ovenbird_core.control.record import JsonValue

RESULT_SCHEMA_VERSION: Final = 1
BATCH: Final = 5000

SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
    run TEXT NOT NULL, tick INTEGER NOT NULL, t REAL NOT NULL, wall TEXT NOT NULL,
    controller TEXT NOT NULL, ladder TEXT NOT NULL, reason TEXT NOT NULL,
    setpoint INTEGER, pre_round REAL, binding TEXT, record TEXT NOT NULL,
    PRIMARY KEY (run, tick)
);
CREATE TABLE IF NOT EXISTS intents (
    run TEXT NOT NULL, tick INTEGER NOT NULL, kind TEXT NOT NULL, value INTEGER NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inputs (
    run TEXT NOT NULL, tick INTEGER NOT NULL, signal TEXT NOT NULL, value TEXT,
    age REAL, fresh INTEGER NOT NULL, source TEXT
);
CREATE TABLE IF NOT EXISTS reference (
    run TEXT NOT NULL, tick INTEGER NOT NULL, recorded_setpoint INTEGER,
    recorded_fresh INTEGER NOT NULL, last_command INTEGER, last_command_t REAL,
    PRIMARY KEY (run, tick)
);
CREATE TABLE IF NOT EXISTS runs (
    run TEXT PRIMARY KEY, controller TEXT NOT NULL, variant TEXT NOT NULL,
    replicate INTEGER, combo TEXT, config_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily (
    run TEXT NOT NULL, day TEXT NOT NULL, kpi TEXT NOT NULL, value REAL,
    PRIMARY KEY (run, day, kpi)
);
CREATE TABLE IF NOT EXISTS totals (
    run TEXT NOT NULL, kpi TEXT NOT NULL, value REAL, PRIMARY KEY (run, kpi)
);
CREATE TABLE IF NOT EXISTS trajectory (
    run TEXT NOT NULL, tick INTEGER NOT NULL, t REAL NOT NULL, setpoint INTEGER,
    room_c REAL, outlet_c REAL, heat_w REAL, elec_w REAL, running INTEGER,
    defrost INTEGER, reason TEXT, PRIMARY KEY (run, tick)
);
CREATE TABLE IF NOT EXISTS gate (
    run TEXT NOT NULL, criterion TEXT NOT NULL, simulated REAL, recorded REAL,
    error REAL, bound REAL, passed INTEGER NOT NULL, unit TEXT,
    PRIMARY KEY (run, criterion)
);
CREATE TABLE IF NOT EXISTS differences (
    kpi TEXT PRIMARY KEY, point REAL, lo REAL, hi REAL, n INTEGER, status TEXT NOT NULL,
    reasons TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contributions (
    kpi TEXT NOT NULL, term TEXT NOT NULL, value REAL, PRIMARY KEY (kpi, term)
);
"""


def dump(value: JsonValue) -> str:
    """Canonical compact JSON text (sorted keys, no NaN)."""
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


class ResultDB:
    """Writer of one result database (replaces an existing file).

    Parameters
    ----------
    path
        Database file.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        self.path = path
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode = OFF")
        self._db.execute("PRAGMA synchronous = OFF")
        self._db.executescript(SCHEMA)
        self._pending: dict[str, list[tuple[object, ...]]] = {}

    def __enter__(self) -> Self:
        """Return the writer."""
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """Flush and close."""
        self.close()

    def set_meta(self, values: Mapping[str, JsonValue]) -> None:
        """Store metadata entries (JSON values)."""
        self._db.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            [(key, dump(value)) for key, value in values.items()],
        )

    def add(self, table: str, row: tuple[object, ...]) -> None:
        """Queue one row for ``table`` (written in batches)."""
        rows = self._pending.setdefault(table, [])
        rows.append(row)
        if len(rows) >= BATCH:
            self._flush(table)

    def add_many(self, table: str, rows: Iterable[tuple[object, ...]]) -> None:
        """Queue several rows for ``table``."""
        for row in rows:
            self.add(table, row)

    def add_step(
        self,
        run: str,
        tick: int,
        result: StepResult[object],
        *,
        inputs: bool = True,
    ) -> None:
        """Store one controller tick: the decision record, its intents and inputs.

        Parameters
        ----------
        run
            Run id.
        tick
            Tick index.
        result
            The controller's step result.
        inputs
            Also store the inputs used as rows of ``inputs``.
        """
        record = result.decision
        data = record.to_json_dict()
        at = record.at
        self.add(
            "decisions",
            (
                run,
                tick,
                at.wall.timestamp(),
                at.wall.isoformat(),
                record.controller,
                record.ladder.value,
                record.reason.value,
                record.setpoint,
                record.pre_round,
                record.binding,
                dump(data),
            ),
        )
        for intent in result.intents:
            self.add("intents", (run, tick, intent.kind.value, intent.value, intent.reason.value))
        if inputs:
            for ref in record.inputs_used:
                self.add(
                    "inputs",
                    (
                        run,
                        tick,
                        ref.signal,
                        None if ref.value is None else dump(ref.value),
                        ref.age,
                        int(ref.fresh),
                        ref.source,
                    ),
                )

    def _flush(self, table: str) -> None:
        """Insert the buffered rows of ``table`` into the database and clear the buffer."""
        rows = self._pending.pop(table, [])
        if not rows:
            return
        marks = ", ".join("?" for _ in rows[0])
        self._db.executemany(f"INSERT INTO {table} VALUES ({marks})", rows)  # noqa: S608

    def flush(self) -> None:
        """Write every queued row."""
        for table in list(self._pending):
            self._flush(table)
        self._db.commit()

    def close(self) -> None:
        """Flush and close the database."""
        self.flush()
        self._db.close()


def read_table(path: Path, table: str, order: Sequence[str] = ()) -> list[tuple[object, ...]]:
    """Read every row of ``table`` (optionally ordered), for tests and reports."""
    db = sqlite3.connect(path)
    try:
        clause = f" ORDER BY {', '.join(order)}" if order else ""
        return list(db.execute(f"SELECT * FROM {table}{clause}"))  # noqa: S608
    finally:
        db.close()


def read_meta(path: Path) -> dict[str, JsonValue]:
    """Read the ``meta`` table as decoded JSON values."""
    return {str(key): json.loads(str(value)) for key, value in read_table(path, "meta")}
