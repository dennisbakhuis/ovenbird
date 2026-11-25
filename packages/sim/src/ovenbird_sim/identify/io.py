"""Read and write fitted plant parameters as JSON."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams

SCHEMA = "ovenbird.plant-params/1"


def _clean(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def params_to_dict(params: PlantParams) -> dict[str, dict[str, float]]:
    """Plain dictionaries of both parameter layers."""
    return {"heat_pump": asdict(params.heat_pump), "building": asdict(params.building)}


def params_from_dict(data: dict[str, Any]) -> PlantParams:
    """Build parameters from :func:`params_to_dict` output (unknown keys are ignored)."""
    hp_names = {f.name for f in fields(HeatPumpParams)}
    b_names = {f.name for f in fields(BuildingParams)}
    hp = HeatPumpParams(**{k: float(v) for k, v in data["heat_pump"].items() if k in hp_names})
    b = BuildingParams(**{k: float(v) for k, v in data["building"].items() if k in b_names})
    return PlantParams(hp, b)


def save(path: Path, params: PlantParams, extra: dict[str, Any] | None = None) -> Path:
    """Write parameters plus any report sections to ``path`` (directories created).

    Parameters
    ----------
    path
        Output file.
    params
        Fitted parameters.
    extra
        Additional JSON-serialisable sections (intervals, validation, provenance).

    Returns
    -------
    Path
        The written path.
    """
    payload: dict[str, Any] = {"schema": SCHEMA, "params": params_to_dict(params)}
    payload.update(extra or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(payload), indent=2, sort_keys=False), encoding="utf-8")
    return path


def train_path(path: Path) -> Path:
    """Return the train-only parameter file written next to ``path``."""
    return path.with_name(f"{path.stem}_train{path.suffix}")


def fold_path(path: Path, index: int) -> Path:
    """Return the train-only file of rolling-origin fold ``index`` (0: the latest)."""
    base = train_path(path)
    return base if index == 0 else base.with_name(f"{base.stem}_{index + 1}{base.suffix}")


def fold_paths(path: Path) -> list[Path]:
    """Existing train-only files next to ``path``, latest fold first."""
    out: list[Path] = []
    while (candidate := fold_path(path, len(out))).exists():
        out.append(candidate)
    return out


def load_report(path: Path) -> dict[str, Any]:
    """Read the report sections stored with the parameters."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def load(path: Path) -> PlantParams:
    """Read parameters written by :func:`save`.

    Raises
    ------
    ValueError
        When the file has another schema.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"unexpected schema {payload.get('schema')!r}")
    return params_from_dict(payload["params"])
