"""The models directory: versioned house models and insights, the champion, the run log.

Layout (all JSON, written atomically: a temporary file with a unique name, flushed
to disk, renamed over the target, and the directory synced)::

    models/
      house-<YYYYMMDD>.json     plant parameters + intervals, validation, credibility,
                                provenance (schema ovenbird.plant-params/1, so the
                                simulator can load it)
      insight-<YYYYMMDD>.json   what the House page shows (schema ovenbird.house-insight/1)
      series-<YYYYMMDD>.json    the last 14 days of the room, measured and predicted 24 h ahead
                                (schema ovenbird.house-series/1, :mod:`ovenbird_sim.learn.series`)
      current.json              the champion: {"model", "house", "insight", "promoted_at"}
      index.json                every run, promoted or not (UA, score, held-out errors)
      status.json               the last run: outcome, reasons, what is missing, runtime,
                                the interval of a repeating learner (``interval_h``)

The date is the last day of the data (service clock), so a rerun on the same data
replaces its own files, except the champion's: a challenger that lost on the
champion's day is written as ``house-<YYYYMMDD>-<n>``. The service reads
``current.json``, the champion's insight, ``index.json`` and ``status.json`` only
(regular files, never through a link, size-capped and checked against an allow-list).
The learner's inputs live elsewhere: ``learner-config.json`` and the history snapshot
are written by the service into its ``learner`` directory, which the learner only reads.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Final

CURRENT: Final = "current.json"
INDEX: Final = "index.json"
STATUS: Final = "status.json"
CONFIG: Final = "learner-config.json"
INSIGHT_SCHEMA: Final = "ovenbird.house-insight/1"


def clean(value: Any) -> Any:
    """Replace non-finite floats by ``None`` recursively (strict JSON)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [clean(v) for v in value]
    return value


def write_json(path: Path, payload: Any) -> Path:
    """Write ``payload`` as strict JSON to ``path`` atomically and durably.

    The text goes to a new temporary file next to ``path`` (unique name, created
    exclusively, so an existing link is never followed), is flushed and synced, then
    renamed over ``path``; the directory is synced so the rename survives a power cut.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(clean(payload), indent=2, allow_nan=False)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    _sync_dir(path.parent)
    return path


def _sync_dir(directory: Path) -> None:
    """Flush a directory entry change to disk (no-op where directories cannot be opened)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def read_json(path: Path) -> Any:
    """Read a JSON file, or ``None`` when it is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None


def model_name(day: str) -> str:
    """Return ``house-<YYYYMMDD>`` for an ISO date."""
    return "house-" + day.replace("-", "")


def free_name(models: Path, base: str, champion_name: str | None, *, promote: bool) -> str:
    """Return the model name to write: ``base``, unless that would overwrite the champion.

    A run that is not promoted on the champion's own day gets ``<base>-2``, ``-3``, ...
    so the champion's files are never replaced by a challenger that lost.
    """
    if promote or base != champion_name:
        return base
    n = 2
    while (models / f"{base}-{n}.json").exists():
        n += 1
    return f"{base}-{n}"


def insight_name(model: str) -> str:
    """Return the insight file name of a model name."""
    return model.replace("house-", "insight-", 1) + ".json"


def series_name(model: str) -> str:
    """Return the series file name of a model name."""
    return model.replace("house-", "series-", 1) + ".json"


def champion(models: Path) -> dict[str, Any] | None:
    """Return ``current.json`` with the champion's house file loaded as ``house``."""
    current = read_json(models / CURRENT)
    if not isinstance(current, dict):
        return None
    house = read_json(models / str(current.get("house", "")))
    if not isinstance(house, dict):
        return None
    return current | {"house_payload": house}


def promote(models: Path, model: str, at: str) -> None:
    """Point ``current.json`` at ``model``."""
    write_json(
        models / CURRENT,
        {
            "model": model,
            "house": f"{model}.json",
            "insight": insight_name(model),
            "promoted_at": at,
        },
    )


def append_index(models: Path, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Add (or replace, by model name) one run in ``index.json``; returns the index."""
    index = read_json(models / INDEX)
    runs = (
        [r for r in index.get("runs", []) if isinstance(r, dict)] if isinstance(index, dict) else []
    )
    runs = [r for r in runs if r.get("model") != entry.get("model")]
    runs.append(entry)
    runs.sort(key=lambda r: str(r.get("data_to", "")))
    write_json(models / INDEX, {"runs": runs})
    return runs


def index_runs(models: Path) -> list[dict[str, Any]]:
    """Return the runs recorded in ``index.json`` (oldest first)."""
    index = read_json(models / INDEX)
    if not isinstance(index, dict):
        return []
    return [r for r in index.get("runs", []) if isinstance(r, dict)]


def write_status(models: Path, status: dict[str, Any]) -> None:
    """Write ``status.json``."""
    write_json(models / STATUS, status)
