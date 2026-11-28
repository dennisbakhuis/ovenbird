import json
from dataclasses import replace
from pathlib import Path

import pytest

from ovenbird_sim.model import BuildingParams, HeatPumpParams, PlantParams, io


def test_params_round_trip(tmp_path: Path) -> None:
    """Plant parameters survive saving and loading, with NaN notes stored as null."""
    params = PlantParams(
        replace(HeatPumpParams(), k_o=9.5), replace(BuildingParams(), h_air_out=210.0)
    )
    path = io.save(tmp_path / "models" / "p.json", params, {"note": float("nan")})
    assert io.load(path) == params
    assert json.loads(path.read_text())["note"] is None


def test_another_schema_is_refused(tmp_path: Path) -> None:
    """A file with another schema identifier is refused."""
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"schema": "other/1", "params": {}}))
    with pytest.raises(ValueError, match="unexpected schema"):
        io.load(path)
