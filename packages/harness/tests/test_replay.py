from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

import pytest

from ovenbird_harness.compare import WindowKpis, judge
from ovenbird_harness.fullrun import RunConfig, board_args
from ovenbird_harness.replay import Recording, compare_rows, override, replay, run_service
from ovenbird_harness.settings import harness_settings
from ovenbird_harness.testing import REFERENCE_START
from ovenbird_harness.validate import ha_config, main, mqtt_config, replay_check
from ovenbird_sim.heishamon.__main__ import build_board

pytestmark = pytest.mark.slow


def test_exact_replay_of_the_real_service(tmp_path: Path) -> None:
    config = mqtt_config(REFERENCE_START, None, None, tmp_path)
    result = replay_check(config, 120.0, 6.0, tmp_path)
    assert result["passed"], result
    assert result["recorded"] >= 8
    assert {"tick", "adapter", "message"} <= set(result["event_kinds"])


def test_exact_replay_on_the_home_assistant_path(tmp_path: Path) -> None:
    config = ha_config(REFERENCE_START, None, None, tmp_path)
    result = replay_check(config, 120.0, 6.0, tmp_path, ha=True)
    assert result["passed"], result
    assert result["path"] == "ha/on_change"
    assert {"ha_open", "ha_expect", "ha", "tick"} <= set(result["event_kinds"])


def test_override_refuses_a_missing_method() -> None:
    class Target:
        def tick(self) -> None:
            return None

    target = Target()
    override(target, "tick", lambda: None)
    with pytest.raises(AttributeError, match="no method 'tock'"):
        override(target, "tock", lambda: None)


def test_a_recording_without_ticks_is_refused() -> None:
    with pytest.raises(ValueError, match="adapter, message, tick"):
        Recording().check()


def test_validate_does_not_write_into_the_captures(monkeypatch: pytest.MonkeyPatch) -> None:
    written: list[Path] = []

    def fake_compare(config: RunConfig, hours: float, speed: float) -> dict[str, object]:
        written.append(config.out)
        return {"passed": True, "hours": hours}

    monkeypatch.setattr("ovenbird_harness.validate.compare", fake_compare)
    assert main(["--skip-replay"]) == 0
    assert written
    assert "capture" not in written[0].parts
    assert (written[0] / "validate.json").exists()


def test_replay_detects_a_changed_stream(tmp_path: Path) -> None:
    config = mqtt_config(REFERENCE_START, None, None, tmp_path)
    settings = harness_settings(
        tmp_path / "recorded", config.profile, clock_speed=120.0, clock_start=config.start
    )
    board = build_board(board_args(config))
    _, recording = asyncio.run(run_service(settings, board, 6.0, record=True))
    assert recording is not None
    rows = replay(settings, recording, tmp_path / "same")
    assert compare_rows(recording.rows, rows, len(recording.events)).passed
    shifted = [
        dataclasses.replace(event, at=type(event.at)(event.at.monotonic + 30.0, event.at.wall))
        if event.kind == "message" and "Outside_Temp" in event.data.topic
        else event
        for event in recording.events
    ]
    changed = dataclasses.replace(recording, events=shifted)
    rows = replay(settings, changed, tmp_path / "changed")
    result = compare_rows(recording.rows, rows, len(shifted))
    assert not result.passed
    assert result.first_difference is not None


def kpis(
    starts: float, feedback: float, room: float, *, days: float = 2.0, defrosts: int = 3
) -> WindowKpis:
    return WindowKpis(
        days,
        starts,
        {"schedule_curve_feedback": feedback, "curve_only": 1.0 - feedback},
        {"30": 0.5, "31": 0.5},
        room,
        2880,
        round(starts * days),
        defrosts,
    )


def test_judge_uses_the_spread_of_the_repeats_and_floors() -> None:
    same = judge(kpis(5.0, 0.9, 21.0), kpis(5.0, 0.9, 21.0), kpis(5.0, 0.9, 21.0))
    assert same["passed"]
    far = judge(kpis(9.0, 0.5, 20.4), kpis(5.0, 0.9, 21.0), kpis(5.0, 0.9, 21.0))
    assert not far["passed"]
    assert not far["kpis"]["starts_per_day"]["passed"]
    assert not far["kpis"]["ladder_shares"]["passed"]
    assert not far["kpis"]["room_mean_c"]["passed"]
    wide = judge(kpis(9.0, 0.9, 21.0), kpis(5.0, 0.9, 21.0), kpis(8.0, 0.9, 21.0))
    assert wide["kpis"]["starts_per_day"]["tolerance"] == 6.0
    assert wide["kpis"]["starts_per_day"]["passed"]
    assert same["kpis"]["room_mean_c"]["tolerance"] == 0.02
    assert same["kpis"]["ladder_shares"]["tolerance"] == 0.01
    assert same["kpis"]["setpoint_histogram"]["tolerance"] == 0.02
    near = judge(kpis(5.0, 0.88, 21.0), kpis(5.0, 0.9, 21.0), kpis(5.0, 0.9, 21.0))
    assert not near["kpis"]["ladder_shares"]["passed"]


def test_judge_requires_a_window_that_exercises_the_plant() -> None:
    short = judge(kpis(5.0, 0.9, 21.0, days=0.5), kpis(5.0, 0.9, 21.0), kpis(5.0, 0.9, 21.0))
    assert not short["passed"]
    assert "b1" in short["kpis"]["coverage"]["short"]
    calm = judge(kpis(5.0, 0.9, 21.0, defrosts=0), kpis(5.0, 0.9, 21.0), kpis(5.0, 0.9, 21.0))
    assert not calm["kpis"]["coverage"]["passed"]
    few = judge(kpis(3.0, 0.9, 21.0), kpis(3.0, 0.9, 21.0), kpis(3.0, 0.9, 21.0))
    assert not few["kpis"]["coverage"]["passed"]
