"""Bodies of the data routes (:mod:`ovenbird.api.data_api`, :mod:`ovenbird.api.archive_api`).

``history/signals``, ``history/storage``, ``history/compact``, ``archive`` and
``archive/delete``. The exports (``export/series``, ``export/journal/{kind}``,
``export/archive``) and the archive downloads are files and not modelled here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.api.models.base import ApiModel, Number

type ResolutionId = Literal["raw", "60", "900", "3600", "journal", "forecast"]
type SignalKindName = Literal["number", "enum", "bool"]
type AutoVacuumName = Literal["none", "full", "incremental"]
type PresetName = Literal["short", "standard", "long", "unlimited"]
type ArchiveMonthState = Literal["frozen", "open"]
type ArchiveGroupKind = Literal["year", "season"]


class SignalRange(ApiModel):
    """The stored range of one signal at one resolution (``step`` 0 is raw)."""

    step: int
    first: str
    last: str
    points: int


class StoredSignal(ApiModel):
    """One signal with history: id, unit, kind and its range per resolution."""

    id: str
    unit: str | None
    kind: SignalKindName
    resolutions: list[SignalRange]


class HistorySignals(ApiModel):
    """``GET history/signals``: every signal with stored history."""

    signals: list[StoredSignal]


class StorageFiles(ApiModel):
    """Sizes in bytes of the files in the data directory and its free space."""

    database: int
    wal: int
    snapshot: int | None
    free: int | None


class StorageTable(ApiModel):
    """One table or index of ``history.db``."""

    name: str
    bytes: int
    rows: int | None


class StorageResolution(ApiModel):
    """What one resolution holds and what it costs per day."""

    id: ResolutionId
    retention_days: Number | None
    rows: int
    oldest: str | None
    newest: str | None
    bytes: int | None
    bytes_per_day: Number | None


class Compaction(ApiModel):
    """The last compaction of ``history.db`` (``POST history/compact``)."""

    pending: bool
    running: bool
    last_at: str | None
    freed_bytes: int | None
    error: str | None


class RetentionPreset(ApiModel):
    """One simple retention choice: its settings and the size it would come to."""

    id: PresetName
    values: dict[str, Number]
    projected_bytes: int | None
    growth_bytes_per_year: int | None


class HistoryStorage(ApiModel):
    """``GET history/storage``: sizes, ranges, the projection and the compaction state."""

    files: StorageFiles
    tables: list[StorageTable]
    resolutions: list[StorageResolution]
    projected_bytes: int | None
    growth_bytes_per_year: int | None
    reclaimable_bytes: int
    auto_vacuum: AutoVacuumName
    presets: list[RetentionPreset]
    preset: PresetName | None
    compaction: Compaction | None


class CompactResult(ApiModel):
    """``POST history/compact``: whether the request was queued, and the state."""

    accepted: bool
    compaction: Compaction


class ArchiveRun(ApiModel):
    """What the archive's last step did (``null`` without a history writer)."""

    last_run_at: str | None
    error: str | None
    behind: bool
    archived_to: str | None


class ArchiveMonth(ApiModel):
    """One stored month: frozen (final) or open (being built)."""

    period: str
    state: ArchiveMonthState
    bytes: int
    days_total: int
    from_: str | None = Field(alias="from")
    to: str | None
    complete: bool | None
    days: int | None
    decision_days: int | None
    missing_days: int | None
    created_at: str | None
    archived_to: str | None


class ArchiveGroup(ApiModel):
    """A calendar year or heating season with stored months."""

    id: str
    kind: ArchiveGroupKind
    period: str
    months: list[str]
    open_months: list[str]
    of: int
    bytes: int
    complete: bool
    first: str | None
    last: str | None


class ArchiveStatus(ApiModel):
    """``GET archive``: whether the archive runs, what it holds and what it costs."""

    enabled: bool
    timezone: str
    state: ArchiveRun | None
    months: list[ArchiveMonth]
    years: list[ArchiveGroup]
    seasons: list[ArchiveGroup]
    total_bytes: int
    bytes_per_year: int | None
    notice: str


class ArchiveDeleteResult(ApiModel):
    """``POST archive/delete``: the months removed and the archive afterwards."""

    deleted: list[str]
    archive: ArchiveStatus
