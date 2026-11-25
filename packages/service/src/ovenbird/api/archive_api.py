"""Yearly archive endpoints: the frozen months and their downloads per month, year and season.

``GET archive`` (what is stored, sizes and coverage) is open to every role, like the
storage report. The downloads and ``POST archive/delete`` need ``admin``: the files
hold the full measurement history (see :data:`~ovenbird.history.archive.ARCHIVE_NOTICE`).
A month that is frozen is served as its file; the open month and the bundles of a year
or heating season are built in the data directory, one at a time, and removed after
the download.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ovenbird.api.auth import Role
from ovenbird.api.data_api import DataDeps
from ovenbird.api.deps import bound, read_json, require_role
from ovenbird.api.export import download_name
from ovenbird.api.models.base import returns
from ovenbird.api.models.data import ArchiveDeleteResult, ArchiveStatus
from ovenbird.clock import iso_from_unix
from ovenbird.config import Settings
from ovenbird.history.archive import (
    ARCHIVE_NOTICE,
    BUILD_PREFIX,
    ArchiveError,
    ArchiveFolder,
    Month,
    bundle_manifest,
    listing,
    parse_season,
    parse_year,
    read_zip_manifest,
    season_id,
    season_label,
    season_months,
    write_bundle,
    write_open_month,
    year_months,
)
from ovenbird.payloads import Json


def _current(deps: DataDeps) -> Settings:
    return deps.config.settings if deps.config is not None else deps.settings


def _folder(deps: DataDeps) -> ArchiveFolder:
    writer = deps.writer
    if writer is not None and writer.archiver is not None:
        return writer.archiver.folder
    return ArchiveFolder(deps.settings.archive_dir)


def _state(deps: DataDeps) -> Json | None:
    writer = deps.writer
    if writer is None or writer.archiver is None:
        return None
    state = writer.archiver.state
    return {
        "last_run_at": None if state.last_run_at is None else iso_from_unix(state.last_run_at),
        "error": state.error,
        "behind": state.behind,
        "archived_to": None if state.archived_to is None else iso_from_unix(state.archived_to),
    }


def archive_status(deps: DataDeps) -> Json:
    """``GET archive``: whether the archive runs, the stored months, years and seasons."""
    settings = _current(deps)
    return {
        "enabled": settings.history_archive_enabled,
        "timezone": settings.control_timezone,
        "state": _state(deps),
        **listing(_folder(deps), settings.control_timezone),
        "notice": ARCHIVE_NOTICE,
    }


def _month(text: str) -> Month:
    try:
        return Month.parse(text)
    except ArchiveError as exc:
        raise HTTPException(400, str(exc)) from None


def _zip_response(path: Path, name: str, folder: Path | None = None) -> FileResponse:
    return FileResponse(
        path,
        media_type="application/zip",
        filename=name,
        headers={"Cache-Control": "no-store"},
        background=None
        if folder is None
        else BackgroundTask(shutil.rmtree, folder, ignore_errors=True),
    )


async def _built(
    deps: DataDeps, needed: int, build: Callable[[Path], Path], name: str
) -> FileResponse:
    settings = deps.settings
    if shutil.disk_usage(settings.data_dir).free < needed + settings.history_min_free_mb * 2**20:
        raise HTTPException(507, "not enough free space in the data directory for the download")
    if not deps.archive_lock.acquire(blocking=False):
        raise HTTPException(409, "an archive is being built; try again when it is done")
    folder = Path(tempfile.mkdtemp(prefix=BUILD_PREFIX, dir=settings.data_dir))
    try:
        target = await asyncio.to_thread(build, folder)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        deps.archive_lock.release()
    return _zip_response(target, name, folder)


async def download_month(deps: DataDeps, month: str, request: Request) -> FileResponse:
    """``GET archive/months/{month}``: one month's zip (the open month as it stands)."""
    require_role(request, deps.settings, Role.ADMIN)
    chosen = _month(month)
    folder = _folder(deps)
    frozen = folder.frozen_path(chosen)
    if frozen.exists():
        return _zip_response(frozen, download_name("archive", str(chosen), "zip"))
    working = folder.open_path(chosen)
    if not working.exists():
        raise HTTPException(404, f"{chosen} is not in the archive")
    settings = _current(deps)
    config = deps.config.archive_config if deps.config is not None else None
    created = deps.runtime.clock().wall.timestamp()

    def build(target: Path) -> Path:
        return write_open_month(working, target, chosen, settings.control_timezone, created, config)

    return await _built(
        deps,
        2 * working.stat().st_size,
        build,
        download_name("archive", f"{chosen}-partial", "zip"),
    )


async def _bundle(
    deps: DataDeps, kind: str, period: str, ident: str, months: Sequence[Month]
) -> FileResponse:
    folder = _folder(deps)
    frozen = folder.frozen()
    files = [frozen[month] for month in months if month in frozen]
    if not files:
        raise HTTPException(404, f"no frozen month of {period} in the archive")
    timezone = _current(deps).control_timezone
    created = deps.runtime.clock().wall.timestamp()

    def build(target: Path) -> Path:
        found = {
            month: (frozen[month], read_zip_manifest(frozen[month]))
            for month in months
            if month in frozen
        }
        manifest = bundle_manifest(kind, period, months, found, timezone, created)
        path = target / f"{ident}.zip"
        write_bundle(path, files, manifest)
        return path

    return await _built(
        deps,
        sum(path.stat().st_size for path in files),
        build,
        download_name("archive", ident if kind == "year" else f"season-{ident}", "zip"),
    )


async def download_year(deps: DataDeps, year: str, request: Request) -> FileResponse:
    """``GET archive/years/{year}``: the frozen months of a calendar year and a manifest."""
    require_role(request, deps.settings, Role.ADMIN)
    try:
        number = parse_year(year)
    except ArchiveError as exc:
        raise HTTPException(400, str(exc)) from None
    return await _bundle(deps, "year", str(number), str(number), year_months(number))


async def download_season(deps: DataDeps, season: str, request: Request) -> FileResponse:
    """``GET archive/seasons/{season}``: the frozen months of a heating season (Aug-Jul)."""
    require_role(request, deps.settings, Role.ADMIN)
    try:
        start = parse_season(season)
    except ArchiveError as exc:
        raise HTTPException(400, str(exc)) from None
    return await _bundle(
        deps, "season", season_label(start), season_id(start), season_months(start)
    )


async def delete_archive(deps: DataDeps, request: Request) -> Json:
    """``POST archive/delete``: delete a frozen month or every frozen month of a year."""
    who = require_role(request, deps.settings, Role.ADMIN, deps.audit)
    body = await read_json(request)
    period = body.get("period")
    if not isinstance(period, str):
        raise HTTPException(400, "period must be a month (YYYY-MM) or a year (YYYY)")
    folder = _folder(deps)
    try:
        months = [Month.parse(period)] if "-" in period else year_months(parse_year(period))
    except ArchiveError as exc:
        raise HTTPException(400, str(exc)) from None
    frozen = await asyncio.to_thread(folder.frozen)
    if len(months) == 1 and months[0] not in frozen and folder.open_path(months[0]).exists():
        raise HTTPException(409, f"{period} is still being archived; delete it once it is frozen")
    if not any(month in frozen for month in months):
        raise HTTPException(404, f"no frozen month of {period} in the archive")
    deleted = await asyncio.to_thread(folder.delete, months)
    if deps.config is not None:
        deps.config.audit(who.actor, "archive_delete", {"period": period, "deleted": deleted})
    return {"deleted": deleted, "archive": await asyncio.to_thread(archive_status, deps)}


def build_archive_router(deps: DataDeps) -> APIRouter:
    """Return the archive routes without prefix (the caller adds ``/api/v1``)."""
    router = APIRouter()
    router.get("/archive", **returns(ArchiveStatus))(bound(archive_status, deps))
    router.get("/archive/months/{month}", response_model=None)(bound(download_month, deps))
    router.get("/archive/years/{year}", response_model=None)(bound(download_year, deps))
    router.get("/archive/seasons/{season}", response_model=None)(bound(download_season, deps))
    router.post("/archive/delete", **returns(ArchiveDeleteResult))(bound(delete_archive, deps))
    return router
