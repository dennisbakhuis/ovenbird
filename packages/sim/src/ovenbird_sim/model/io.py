"""Read and write plant parameters as JSON (the ``--params`` file of the simulator)."""

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
    """Return ``value`` with non-finite floats replaced by ``None`` (strict JSON)."""
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
    """Write parameters plus any extra sections to ``path`` (directories created).

    Parameters
    ----------
    path
        Output file.
    params
        Plant parameters.
    extra
        Additional JSON-serialisable sections.

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
