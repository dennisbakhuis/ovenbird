"""Provenance of an evaluation run: canonical config JSON, its hash, versions, git commit."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import shutil
import subprocess
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from enum import Enum
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from ovenbird_core.control.record import DECISION_SCHEMA_VERSION, JsonValue

REPO_ROOT: Final = Path(__file__).resolve().parents[5]
GIT_TIMEOUT_S: Final = 10.0
NO_CLAIMS_BANNER: Final = "decision given recorded state — no outcome claims"


def to_jsonable(value: Any) -> JsonValue:
    """Convert dataclasses, enums, sets and times to plain JSON values (deterministically).

    Parameters
    ----------
    value
        Any configuration object.

    Returns
    -------
    JsonValue
        Its JSON form; sets are sorted, mappings keyed by strings, non-finite
        floats become strings.
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        items = [to_jsonable(v) for v in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, list | tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def config_hash(config: JsonValue) -> str:
    """SHA-256 of the canonical JSON form of ``config`` (first 16 hex digits)."""
    text = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_hash(path: Path) -> str:
    """SHA-256 of a file's bytes (first 16 hex digits)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def package_version(name: str) -> str:
    """Installed version of a distribution, ``"unknown"`` when not installed."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def git_commit(root: Path = REPO_ROOT) -> dict[str, JsonValue]:
    """Return the checked-out commit and whether the work tree has changes.

    Parameters
    ----------
    root
        Repository root.

    Returns
    -------
    dict
        ``commit`` (``"unknown"`` without git) and ``dirty`` (``None`` when unknown).
    """
    git = shutil.which("git")
    if git is None:
        return {"commit": "unknown", "dirty": None}
    try:
        head = subprocess.run(  # noqa: S603
            [git, "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=True,
        ).stdout.strip()
        status = subprocess.run(  # noqa: S603
            [git, "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=True,
        ).stdout
    except OSError, subprocess.SubprocessError:
        return {"commit": "unknown", "dirty": None}
    return {"commit": head, "dirty": bool(status.strip())}


def controller_identity(controller: object) -> dict[str, JsonValue]:
    """Name, version and configuration hash of a controller.

    Parameters
    ----------
    controller
        A controller dataclass (its fields are its configuration).

    Returns
    -------
    dict
        ``name``, ``version``, ``config`` and ``config_hash``.
    """
    config = to_jsonable(controller)
    name = getattr(controller, "name", type(controller).__name__)
    version = getattr(controller, "version", None)
    core = package_version("ovenbird-core")
    sim = package_version("ovenbird-sim")
    label = (
        f"{version} (ovenbird-sim {sim})" if isinstance(version, str) else f"ovenbird-core {core}"
    )
    return {
        "name": str(name),
        "class": type(controller).__name__,
        "version": label,
        "decision_schema": DECISION_SCHEMA_VERSION,
        "config": config,
        "config_hash": config_hash(config),
    }


def utc_iso(t: float) -> str:
    """ISO-8601 UTC text of unix seconds."""
    return datetime.fromtimestamp(t, UTC).isoformat()
