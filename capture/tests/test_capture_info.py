from __future__ import annotations

import json
from pathlib import Path

import pytest

from climate_manager_capture.capture import CaptureReader, CaptureWriter, Record
from climate_manager_capture.capture_info import (
    analyse,
    main,
    render_catalogue,
    render_text,
    to_json,
)
from climate_manager_capture.synthetic import (
    BASE,
    GAP_AT_S,
    GAP_LENGTH_S,
    NODE_RED_SETPOINT,
    START,
)
from climate_manager_capture.testing import FakeClock


def test_analyse_synthetic(synthetic_reader: CaptureReader) -> None:
    report = analyse(synthetic_reader)
    assert report.base == BASE
    assert report.first == START
    assert report.problems == []
    assert report.gap_count == 1
    gap_start, gap_end = report.gaps[0]
    assert gap_start - START < GAP_AT_S
    assert gap_end - START >= GAP_AT_S + GAP_LENGTH_S
    assert report.online_cadence_s == pytest.approx(5.0)
    assert report.lwt_transitions[0][1] == "Offline"
    assert report.lwt_transitions[1][1] == "Online"
    assert report.dump_interval_s is not None
    assert 290 < report.dump_interval_s < 400
    assert report.capture_topics == {
        "climate_manager_capture/room_temp": 1,
        "climate_manager_capture/room_setpoint": 1,
    }
    command = report.commands["SetZ1HeatRequestTemperature"]
    assert command.count == 1
    assert command.unmatched == 0
    assert 0 < command.latencies[0] <= 5.0
    setpoint = report.topics[f"{BASE}/main/Z1_Heat_Request_Temp"]
    assert setpoint.distinct == ["35", str(NODE_RED_SETPOINT)]
    outside = report.topics[f"{BASE}/main/Outside_Temp"]
    assert outside.changes == 2
    assert outside.mean_change_interval is not None
    assert outside.mean_change_interval > 500
    assert report.retained_bursts >= 1


def test_renderers(synthetic_reader: CaptureReader) -> None:
    report = analyse(synthetic_reader)
    text = render_text(report)
    assert "validation   ok" in text
    assert "SetZ1HeatRequestTemperature" in text
    catalogue = render_catalogue(report)
    assert f"{BASE}/main/  (" in catalogue
    payload = json.loads(to_json(report))
    assert payload["records"] == report.records
    assert "_last_payload" not in next(iter(payload["topics"].values()))


def test_problems_flagged(tmp_path: Path) -> None:
    writer = CaptureWriter(tmp_path, "bad", clock=FakeClock(0))
    writer.write(Record(0, "other/thing", "1"))
    writer.write(Record(7200, "other/thing", "2"))
    writer.close()
    report = analyse(CaptureReader(tmp_path / "bad"))
    assert any("no main/*" in p for p in report.problems)
    assert any("no LWT" in p for p in report.problems)
    assert any("gap longer" in p for p in report.problems)


def test_cli_exit_codes(
    synthetic_capture: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(synthetic_capture), "--from", "+5m", "--to", "+20m", "--catalogue"]) == 0
    out = capsys.readouterr().out
    assert "topic catalogue" in out
    writer = CaptureWriter(tmp_path, "bad", clock=FakeClock(0))
    writer.write(Record(0, "x", "1"))
    writer.close()
    assert main([str(tmp_path / "bad"), "--json"]) == 1
