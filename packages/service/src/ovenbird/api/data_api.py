"""Data endpoints: what history holds, its storage and compaction, and the bulk exports.

``GET history/signals``, ``GET history/storage``, the series and journal exports
and their streams are open to every role (as the history and journal endpoints
are); ``POST history/compact`` and ``GET export/archive`` need ``admin``. The
exports stream CSV or newline-delimited JSON a day (series) or a few hundred rows
(journals) at a time, gzip-encoded when the client accepts it, with no cap on the
range. The archive is a zip of a fresh online-backup copy of ``history.db``, the
configuration export (secrets are never part of it) and ``manifest.json``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import shutil
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from ovenbird import __version__
from ovenbird.api.auth import Role
from ovenbird.api.deps import RefusalAudit, bound, read_json, require_role
from ovenbird.api.export import (
    JOURNAL_COLUMNS,
    StreamFormat,
    accepts_gzip,
    csv_line,
    download_name,
    ndjson_line,
    stream_response,
)
from ovenbird.api.models.base import returns
from ovenbird.api.models.data import CompactResult, HistorySignals, HistoryStorage
from ovenbird.clock import iso_from_unix
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.history.archive import ARCHIVE_FORMAT, ARCHIVE_NOTICE, BUILD_PREFIX
from ovenbird.history.export import (
    ALARM_COLUMNS,
    COMMAND_COLUMNS,
    FORECAST_COLUMNS,
    Point,
    SignalInfo,
    data_range,
    iter_rows,
    resolve_signals,
    series_chunks,
    signal_inventory,
)
from ovenbird.history.journal import AlarmRow, CommandRow, iter_decisions
from ovenbird.history.query import HistoryQueryError
from ovenbird.history.schema import connect, user_version
from ovenbird.history.snapshot import backup_to
from ovenbird.history.storage import storage_report
from ovenbird.history.writer import HistoryWriter
from ovenbird.payloads import Json
from ovenbird.runtime import Runtime

STORAGE_TTL_S: Final = 30.0
STEP_IDS: Final = {"raw": 0, "60": 60, "900": 900, "3600": 3600}

type StepName = Literal["raw", "60", "900", "3600"]
type LayoutName = Literal["long", "wide"]
type JournalKind = Literal["decisions", "commands", "alarms", "forecast"]
type Parse = Callable[[str, str], datetime]


@dataclass
class DataDeps:
    """What the data handlers need.

    Parameters
    ----------
    runtime
        Service clock and staleness policy.
    settings
        Paths, roles and request rules.
    config
        Configuration manager (archive's configuration export, audit, live retention).
    writer
        History writer (retention in effect, compaction); ``None`` in tests and the
        contract app.
    audit
        Records refused state-changing requests.
    parse
        Parses a ``from``/``to`` query parameter.
    """

    runtime: Runtime
    settings: Settings
    config: ConfigManager | None
    writer: HistoryWriter | None
    audit: RefusalAudit
    parse: Parse
    archive_lock: threading.Lock = field(default_factory=threading.Lock)
    _storage: tuple[float, Any, Json] | None = None


def bounds(deps: DataDeps, start: str | None, end: str | None) -> tuple[float, float]:
    """Resolve an export window: from the beginning and up to now by default.

    Raises
    ------
    HTTPException
        400 for unparsable or reversed bounds.
    """
    until = deps.parse(end, "to") if end is not None else deps.runtime.clock().wall
    since = deps.parse(start, "from").timestamp() if start is not None else 0.0
    if since >= until.timestamp():
        raise HTTPException(400, "from must be before to")
    return since, until.timestamp()


def compaction_payload(writer: HistoryWriter) -> Json:
    """Return the compaction state of the writer."""
    state = writer.compaction
    return {
        "pending": state.pending,
        "running": state.running,
        "last_at": None if state.last_at is None else iso_from_unix(state.last_at),
        "freed_bytes": state.freed_bytes,
        "error": state.error,
    }


def history_signals(deps: DataDeps) -> Json:
    """``GET history/signals``: every signal with stored history and its range per resolution."""
    return {"signals": signal_inventory(deps.settings.history_path)}


def history_storage(deps: DataDeps) -> Json:
    """``GET history/storage``: database size per table and resolution, and the projection.

    Parameters
    ----------
    deps
        Data dependencies.
    """
    settings = deps.config.settings if deps.config is not None else deps.settings
    writer = deps.writer
    marker = None if writer is None else (writer.compaction.last_at, writer.retention)
    now = time.monotonic()
    cached = deps._storage
    if cached is not None and cached[1] == marker and now - cached[0] < STORAGE_TTL_S:
        body = dict(cached[2])
    else:
        if writer is not None:
            retention, journal_days = writer.retention, writer.journal_days
            snapshot = writer.snapshot_path
        else:
            retention, journal_days = settings.history_retention(), settings.history_journal_days()
            snapshot = settings.snapshot_path if settings.history_snapshot_hours else None
        try:
            free: int | None = shutil.disk_usage(settings.data_dir).free
        except OSError:
            free = None
        body = storage_report(settings.history_path, snapshot, retention, journal_days, free)
        deps._storage = (now, marker, body)
    body["compaction"] = compaction_payload(writer) if writer is not None else None
    return body


async def history_compact(deps: DataDeps, request: Request) -> Json:
    """``POST history/compact``: compact ``history.db`` now (the writer pauses meanwhile)."""
    who = require_role(request, deps.settings, Role.ADMIN, deps.audit)
    await read_json(request)
    writer = deps.writer
    if writer is None:
        raise HTTPException(409, "this service does not write history")
    accepted = writer.request_compaction()
    if accepted and deps.config is not None:
        deps.config.audit(who.actor, "history_compact", {})
    deps._storage = None
    return {"accepted": accepted, "compaction": compaction_payload(writer)}


def _signal_list(signals: str) -> list[str] | None:
    """Return the signal ids named by the ``signals`` query value, or ``None`` for ``all``."""
    if signals.strip() == "all":
        return None
    names = list(dict.fromkeys(part.strip() for part in signals.split(",") if part.strip()))
    if not names:
        raise HTTPException(400, "signals must be 'all' or name at least one signal id")
    return names


def series_lines(
    signals: Sequence[SignalInfo],
    chunks: Iterable[list[Point]],
    step: int,
    layout: LayoutName,
    output: StreamFormat,
) -> Iterator[str]:
    """Return the text lines of a series export.

    Parameters
    ----------
    signals
        Exported signals (the order of the wide columns).
    chunks
        Points per day (:func:`~ovenbird.history.export.series_chunks`).
    step
        0 (raw) or a rollup step; rollups carry ``min`` and ``max`` in the long layout.
    layout
        ``long`` (one line per value) or ``wide`` (one line per time, a column per signal).
    output
        ``csv`` or ``ndjson``.
    """
    names = [info.name for info in signals]
    units = [info.unit for info in signals]
    extremes = step > 0
    if output == "csv":
        if layout == "long":
            yield csv_line(["at", "signal", "unit", "value", *(("min", "max") if extremes else ())])
        else:
            yield csv_line(["at", *names])
    for points in chunks:
        if layout == "long":
            for point in points:
                at = iso_from_unix(point.ts)
                if output == "csv":
                    tail = (point.minimum, point.maximum) if extremes else ()
                    yield csv_line(
                        [at, names[point.signal], units[point.signal], point.value, *tail]
                    )
                else:
                    item: Json = {
                        "at": at,
                        "signal": names[point.signal],
                        "unit": units[point.signal],
                        "value": point.value,
                    }
                    if extremes:
                        item["min"], item["max"] = point.minimum, point.maximum
                    yield ndjson_line(item)
            continue
        for ts, group in itertools.groupby(points, key=lambda point: point.ts):
            values = {point.signal: point.value for point in group}
            at = iso_from_unix(ts)
            if output == "csv":
                yield csv_line([at, *(values.get(index) for index in range(len(names)))])
            else:
                yield ndjson_line({"at": at, "values": {names[i]: v for i, v in values.items()}})


def export_series(
    deps: DataDeps,
    request: Request,
    signals: Annotated[str, Query()] = "all",
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
    step: Annotated[StepName, Query()] = "900",
    layout: Annotated[LayoutName, Query()] = "long",
    output: Annotated[StreamFormat, Query(alias="format")] = "csv",
) -> Response:
    """``GET export/series``: signal history as a streamed CSV or NDJSON download.

    Parameters
    ----------
    deps
        Data dependencies.
    request
        Incoming request (its ``Accept-Encoding`` selects gzip).
    signals
        ``all`` or comma-separated signal ids.
    start, end
        Period bounds (ISO 8601); defaults apply when omitted.
    step
        Bucket width in seconds.
    layout
        ``long`` (one row per value) or ``wide`` (one column per signal).
    output
        ``csv`` or ``ndjson``.
    """
    path = deps.settings.history_path
    t0, t1 = bounds(deps, start, end)
    seconds = STEP_IDS[step]
    try:
        chosen = resolve_signals(path, _signal_list(signals))
        data_range(path, chosen, seconds)
    except HistoryQueryError as exc:
        raise HTTPException(400, str(exc)) from None
    chunks = series_chunks(path, chosen, t0, t1, seconds, deps.runtime.store.policy)
    lines = series_lines(chosen, chunks, seconds, layout, output)
    name = download_name(f"series-{step}-{layout}", iso_from_unix(t0), output)
    return stream_response(
        lines, output, name, gzip=accepts_gzip(request.headers.get("accept-encoding"))
    )


def journal_items(path: Path, kind: JournalKind, start: float, end: float) -> Iterator[Json]:
    """Yield the API form of every journal row of ``kind`` in ``[start, end)``, oldest first.

    Parameters
    ----------
    path
        History database.
    kind
        Journal to read.
    start, end
        Half-open period, Unix seconds.
    """
    if kind == "decisions":
        for decision in iter_decisions(path, start, end):
            yield decision.payload()
    elif kind == "commands":
        for row in iter_rows(path, "command", COMMAND_COLUMNS, ("ts", "id"), start, end):
            yield CommandRow(*row).to_json()
    elif kind == "alarms":
        for row in iter_rows(path, "alarm", ALARM_COLUMNS, ("ts", "id"), start, end):
            yield AlarmRow(*row).to_json()
    else:
        keys = ("issued_ts", "target_ts")
        for issued, target, *values in iter_rows(
            path, "forecast", FORECAST_COLUMNS, keys, start, end
        ):
            yield {
                "issued_at": iso_from_unix(issued),
                "target_at": iso_from_unix(target),
                **dict(zip(FORECAST_COLUMNS[2:], values, strict=True)),
            }


def journal_lines(items: Iterable[Json], kind: JournalKind, output: StreamFormat) -> Iterator[str]:
    """Return the text lines of a journal export (CSV leaves out the decision record)."""
    if output == "ndjson":
        for item in items:
            yield ndjson_line(item)
        return
    columns = JOURNAL_COLUMNS[kind]
    yield csv_line(columns)
    for item in items:
        yield csv_line([item.get(name) for name in columns])


def export_journal(
    deps: DataDeps,
    request: Request,
    kind: JournalKind,
    start: Annotated[str | None, Query(alias="from")] = None,
    end: Annotated[str | None, Query(alias="to")] = None,
    output: Annotated[StreamFormat, Query(alias="format")] = "csv",
) -> Response:
    """``GET export/journal/{kind}``: decisions, commands, alarms or forecasts, streamed.

    Parameters
    ----------
    deps
        Data dependencies.
    request
        Incoming request (its ``Accept-Encoding`` selects gzip).
    kind
        Journal to export.
    start, end
        Period bounds (ISO 8601); defaults apply when omitted.
    output
        ``csv`` or ``ndjson``.
    """
    t0, t1 = bounds(deps, start, end)
    items = journal_items(deps.settings.history_path, kind, t0, t1)
    name = download_name(kind, iso_from_unix(t0), output)
    return stream_response(
        journal_lines(items, kind, output),
        output,
        name,
        gzip=accepts_gzip(request.headers.get("accept-encoding")),
    )


def manifest(path: Path, deps: DataDeps, copy: Path) -> Json:
    """Return ``manifest.json`` of an archive whose database copy is ``copy``."""
    conn = connect(copy, read_only=True)
    try:
        schema = user_version(conn)
    finally:
        conn.close()
    signals = signal_inventory(copy)
    firsts = [r["first"] for s in signals for r in s["resolutions"]]
    lasts = [r["last"] for s in signals for r in s["resolutions"]]
    return {
        "ovenbird_archive": ARCHIVE_FORMAT,
        "app_version": __version__,
        "created_at": iso_from_unix(deps.runtime.clock().wall.timestamp()),
        "history_schema": schema,
        "range": {"from": min(firsts) if firsts else None, "to": max(lasts) if lasts else None},
        "signals": [{"id": s["id"], "unit": s["unit"], "kind": s["kind"]} for s in signals],
        "files": ["history.db", "manifest.json"]
        + (["config.json"] if deps.config is not None else []),
        "source": path.name,
        "notice": ARCHIVE_NOTICE,
    }


def build_archive(deps: DataDeps, folder: Path) -> Path:
    """Write the archive zip into ``folder`` and return its path."""
    path = deps.settings.history_path
    copy = folder / "history.db"
    backup_to(path, copy)
    target = folder / "archive.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(copy, "history.db")
        if deps.config is not None:
            zf.writestr("config.json", json.dumps(deps.config.export(), indent=2) + "\n")
        zf.writestr("manifest.json", json.dumps(manifest(path, deps, copy), indent=2) + "\n")
    copy.unlink()
    return target


async def export_archive(deps: DataDeps, request: Request) -> Response:
    """``GET export/archive``: a fresh copy of ``history.db``, the configuration and a manifest.

    Parameters
    ----------
    deps
        Data dependencies.
    request
        Incoming request (admin only).
    """
    require_role(request, deps.settings, Role.ADMIN)
    settings = deps.settings
    path = settings.history_path
    if not path.exists():
        raise HTTPException(404, "there is no history yet")
    needed = 2 * path.stat().st_size + settings.history_min_free_mb * 2**20
    if shutil.disk_usage(settings.data_dir).free < needed:
        raise HTTPException(507, "not enough free space in the data directory for an archive")
    if not deps.archive_lock.acquire(blocking=False):
        raise HTTPException(409, "an archive is being built; try again when it is done")
    folder = Path(tempfile.mkdtemp(prefix=BUILD_PREFIX, dir=settings.data_dir))
    try:
        target = await asyncio.to_thread(build_archive, deps, folder)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        deps.archive_lock.release()
    stamp = iso_from_unix(deps.runtime.clock().wall.timestamp())
    return FileResponse(
        target,
        media_type="application/zip",
        filename=download_name("archive", stamp, "zip"),
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(shutil.rmtree, folder, ignore_errors=True),
    )


def build_data_router(deps: DataDeps) -> APIRouter:
    """Return the data routes without prefix (the caller adds ``/api/v1``)."""
    router = APIRouter()
    router.get("/history/signals", **returns(HistorySignals))(bound(history_signals, deps))
    router.get("/history/storage", **returns(HistoryStorage))(bound(history_storage, deps))
    router.post("/history/compact", status_code=202, **returns(CompactResult))(
        bound(history_compact, deps)
    )
    router.get("/export/series", response_model=None)(bound(export_series, deps))
    router.get("/export/journal/{kind}", response_model=None)(bound(export_journal, deps))
    router.get("/export/archive", response_model=None)(bound(export_archive, deps))
    return router
