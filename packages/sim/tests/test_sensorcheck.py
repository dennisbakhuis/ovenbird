"""Offline sensor profile proposal on a small Datalake fixture."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ovenbird_sim.data import datalake as dl
from ovenbird_sim.sensorcheck import analyse, propose
from ovenbird_sim.sensorcheck.__main__ import main

START = datetime(2026, 10, 4, tzinfo=UTC)
ROOM = "sensor.living_temperature"
HUMIDITY = "sensor.living_humidity"
PERIODIC = "sensor.office_temperature"
HOUR = 3600.0


def write_entity(root: Path, entity: str, rows: list[tuple[float, str]]) -> None:
    folder = root / "states" / f"entity_id={entity}" / "year=2026" / "month=10"
    folder.mkdir(parents=True, exist_ok=True)
    stamps = [START + timedelta(seconds=t) for t, _ in rows]
    table = pa.table(
        {
            "state": [state for _, state in rows],
            "attributes": ['{"unit_of_measurement":"°C"}'] * len(rows),
            "last_changed": pa.array(stamps, pa.timestamp("us", tz="UTC")),
            "last_updated": pa.array(stamps, pa.timestamp("us", tz="UTC")),
            "ingested_at": pa.array(stamps, pa.timestamp("us", tz="UTC")),
        }
    )
    pq.write_table(table, folder / "part-0.parquet")


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    gaps_h = [1.0, 3.0, 0.5, 8.0, 2.0, 30.0, 1.5, 0.7, 12.0, 4.0, 2.5, 6.0]
    values = [21.0, 21.2, 21.4, 21.2, 21.0, 21.2, 21.4, 21.6, 21.4, 21.2, 21.4, 21.2, 21.0]
    t = 0.0
    rows = [(t, f"{values[0]:.1f}")]
    for gap, value in zip(gaps_h, values[1:], strict=True):
        t += gap * HOUR
        rows.append((t, f"{value:.1f}"))
    rows.insert(4, (rows[3][0] + 60.0, "unavailable"))
    rows.insert(5, (rows[4][0] + 60.0, rows[3][1]))
    write_entity(tmp_path, ROOM, rows)
    humidity = [(h * 2 * HOUR + 600.0, f"{50 + h % 3}") for h in range(40)]
    write_entity(tmp_path, HUMIDITY, humidity)
    periodic = [(k * 300.0, f"{20.0 + 0.03 * (k % 7):.2f}") for k in range(300)]
    write_entity(tmp_path, PERIODIC, periodic)
    return tmp_path


def test_on_change_sensor_with_liveness(lake: Path) -> None:
    states = dl.load_state(lake, ROOM)
    stats = analyse(states, ROOM, dl.load_state(lake, HUMIDITY), HUMIDITY)
    assert stats.step_k == pytest.approx(0.2)
    assert stats.step_share == 1.0
    assert stats.grid_offset_k == pytest.approx(0.0)
    assert stats.unavailable == 1
    assert stats.gaps.max == pytest.approx(30.0 * HOUR)
    assert stats.combined is not None
    assert stats.combined.max < 3 * HOUR
    proposal = propose(stats)
    assert proposal.profile == "on_change"
    assert proposal.step_k == pytest.approx(0.2)
    assert proposal.silence_limit_s == 12 * HOUR
    assert proposal.liveness == (f"ha/{HUMIDITY}",)
    assert proposal.coverage["with_liveness"] == 1.0
    assert proposal.coverage["sensor"] < 1.0
    settings = proposal.settings(f"ha/{ROOM}")
    assert settings["OVENBIRD_CONTROL_ROOM_PROFILE"] == "on_change"
    assert settings["OVENBIRD_CONTROL_ROOM_STEP_K"] == "0.2"
    assert settings["OVENBIRD_CONTROL_ROOM_LIVENESS_SIGNALS"] == f"ha/{HUMIDITY}"


def test_on_change_sensor_alone_needs_a_longer_limit(lake: Path) -> None:
    proposal = propose(analyse(dl.load_state(lake, ROOM), ROOM))
    assert proposal.silence_limit_s == 48 * HOUR
    assert proposal.liveness == ()
    assert proposal.coverage == {"sensor": 1.0}


def test_regular_sensor_is_periodic(lake: Path) -> None:
    proposal = propose(analyse(dl.load_state(lake, PERIODIC), PERIODIC))
    assert proposal.profile == "periodic"
    assert proposal.report_interval_s == 300.0
    assert proposal.silence_limit_s is None
    assert "OVENBIRD_CONTROL_ROOM_REPORT_INTERVAL_S" in proposal.settings(f"ha/{PERIODIC}")


def test_cli(lake: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--datalake", str(lake), "--entity", ROOM, "--liveness", HUMIDITY, "--json"])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["proposal"]["profile"] == "on_change"
    assert body["proposal"]["settings"]["OVENBIRD_CONTROL_ROOM_SILENCE_LIMIT_S"] == "43200"
    assert main(["--datalake", str(lake), "--entity", ROOM]) == 0
    assert "proposed profile: on_change" in capsys.readouterr().out
    assert main(["--datalake", str(lake), "--entity", "sensor.missing"]) == 1
