"""Configuration preview: open-loop run over recorded decisions and the identity check."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ovenbird.config import Settings
from ovenbird.configstore.preview import run_open_loop, valid_hours
from ovenbird.history.packing import pack
from ovenbird.testing import record_decisions

START = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
TICK_S = 60.0
ROOM = "room_temperature"
INPUTS = [{"topic": "climate/room", "signal": ROOM, "unit": "°C"}]
CURVE = [[-10.0, 39.0], [0.0, 34.0], [15.0, 25.0]]


def span(ticks: int) -> tuple[float, float]:
    """Return the start and end timestamps covering the given number of ticks."""
    start = START.timestamp()
    return start, start + ticks * TICK_S


@pytest.fixture
def curve_only(make_settings: Callable[..., Settings]) -> Callable[..., Settings]:
    """Fixture returning a settings factory with feedback, ramp, cycling and pump duty disabled."""

    def factory(**overrides: Any) -> Settings:
        """Build settings with only the heating curve active, plus overrides."""
        values: dict[str, Any] = {
            "control_feedback_enabled": False,
            "control_ramp_enabled": False,
            "control_cycling_enabled": False,
            "control_pump_duty": False,
        }
        values.update(overrides)
        return make_settings(**values)

    return factory


def test_identity_reproduces_every_recorded_setpoint(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """Replaying with the active settings reproduces every recorded setpoint."""
    settings = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM, control_comfort_c=21.5)
    path = tmp_path / "history.db"
    records = record_decisions(path, settings, 1440)
    config = settings.controller_config()
    result = run_open_loop(path, settings, 1, settings, lambda _: config, span(1440))
    assert result["ticks"] == 1440
    assert result["skipped"] == 0
    assert result["identity_ok"] is True
    assert result["identity_ticks"] == 1440
    assert result["open_loop"] is True
    assert result["series"]["candidate"] == [r.setpoint for r in records]
    assert result["series"]["recorded"] == result["series"]["candidate"]
    assert result["summary"]["mean_diff_k"] == 0.0
    assert result["summary"]["changes_recorded"] == result["summary"]["changes_candidate"]


def test_identity_follows_restarts_and_reseeds_at_a_version_change(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """The identity check follows controller restarts and reseeds at config version changes."""
    settings = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM)
    path = tmp_path / "history.db"
    record_decisions(path, settings, 900, version_at=300, restart_at=600)
    config = settings.controller_config()
    result = run_open_loop(path, settings, 2, settings, lambda _: config, span(900))
    assert result["identity_ok"] is True
    assert result["identity_ticks"] == 600


def test_a_wrong_active_configuration_fails_the_identity_check(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """A different active config fails the identity check and names the first mismatch."""
    settings = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM)
    other = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM, control_comfort_c=23.0)
    path = tmp_path / "history.db"
    record_decisions(path, settings, 600)
    result = run_open_loop(path, other, 1, other, lambda _: other.controller_config(), span(600))
    assert result["identity_ok"] is False
    assert result["identity_mismatches"] > 0
    assert result["identity_first_mismatch"] is not None


def test_a_shifted_curve_shifts_the_candidate_by_hand(
    tmp_path: Path, curve_only: Callable[..., Settings]
) -> None:
    """Raising the curve by 1 K raises the candidate pre-rounding values by 1 K."""
    active = curve_only()
    shifted = curve_only(control_curve=[[x, w + 1.0] for x, w in CURVE])
    path = tmp_path / "history.db"
    records = record_decisions(path, active, 720)
    config = active.controller_config()
    result = run_open_loop(path, active, 1, shifted, lambda _: config, span(720))
    assert result["identity_ok"] is True
    pre = result["series"]["candidate_pre_round"]
    expected = [None if r.pre_round is None else r.pre_round + 1.0 for r in records]
    pairs = [(a, b) for a, b in zip(pre, expected, strict=True) if b is not None]
    assert pairs
    assert all(a is not None and abs(a - b) <= 0.0051 for a, b in pairs)
    candidate = [v for v in result["series"]["candidate"] if v is not None]
    recorded = [v for v in result["series"]["recorded"] if v is not None]
    assert sum(candidate) / len(candidate) > sum(recorded) / len(recorded) + 0.5
    summary = result["summary"]
    assert summary["max_diff_k"] >= 1
    assert summary["budget"] == shifted.command_daily_budget
    assert set(summary["ladder"]) <= {"curve_only", "hold", "refuse"}


def test_a_changed_room_signal_is_named_as_a_limitation(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """A changed room signal is reported as a preview limitation and falls back to curve-only."""
    settings = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM)
    other = make_settings(mqtt_inputs=INPUTS)
    path = tmp_path / "history.db"
    record_decisions(path, settings, 120)
    config = settings.controller_config()
    result = run_open_loop(path, settings, 1, other, lambda _: config, span(120))
    assert result["limitations"]
    assert set(result["summary"]["ladder"]) <= {"curve_only", "hold", "refuse"}


def test_unreadable_rows_are_skipped(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """Rows that cannot be decoded are counted as skipped and left out of the series."""
    settings = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM)
    path = tmp_path / "history.db"
    record_decisions(path, settings, 60)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE decision SET dictionary_id = NULL, body = ? WHERE id = 30",
            (pack('{"schema": 9}', "[]", "[]", None),),
        )
    config = settings.controller_config()
    result = run_open_loop(path, settings, 1, settings, lambda _: config, span(60))
    assert result["ticks"] == 60
    assert result["skipped"] == 1
    assert len(result["series"]["at"]) == 59


def test_seventy_two_hours_preview_within_five_seconds(
    tmp_path: Path, make_settings: Callable[..., Settings]
) -> None:
    """A 72-hour preview finishes within five seconds."""
    settings = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM)
    candidate = make_settings(mqtt_inputs=INPUTS, control_room_signal=ROOM, control_comfort_c=22)
    path = tmp_path / "history.db"
    record_decisions(path, settings, 72 * 60)
    config = settings.controller_config()
    began = time.perf_counter()
    result = run_open_loop(path, settings, 1, candidate, lambda _: config, span(72 * 60))
    took = time.perf_counter() - began
    assert result["ticks"] == 4320
    assert result["identity_ok"] is True
    assert took < 5.0, f"{took:.2f} s"


def test_an_empty_history_gives_an_empty_open_loop_run(
    make_settings: Callable[..., Settings],
) -> None:
    """An empty history yields zero ticks and a passing identity check."""
    settings = make_settings()
    config = settings.controller_config()
    result = run_open_loop(
        settings.history_path, settings, None, settings, lambda _: config, span(60)
    )
    assert result["ticks"] == 0
    assert result["identity_ok"] is True
    assert result["series"]["at"] == []


@pytest.mark.parametrize(
    ("raw", "hours"), [(24, 24.0), (1, 1.0), (72, 72.0), (0.5, None), (73, None), ("24", None)]
)
def test_hours_bounds(raw: Any, hours: float | None) -> None:
    """Preview hours are accepted between 1 and 72 and anything else gives None."""
    assert valid_hours(raw) == hours
