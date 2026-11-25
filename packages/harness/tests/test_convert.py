"""The conversion of a recording into history.db: the Replay identity check reproduces it."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from ovenbird.configstore.preview import run_open_loop
from ovenbird.history.journal import decisions_between, query_commands
from ovenbird_core.control import OvenbirdConfig
from ovenbird_harness.convert import (
    RECORDED_STATUS,
    ConvertError,
    ConvertOptions,
    build_settings,
    check_output,
    convert,
    main,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "packages/core/tests/fixtures/synthetic/2026-01-06.jsonl.gz"
SEED = ROOT / "dev/config-seed.json"
DAY = date(2026, 1, 6)
DAY_START = 1767657600.0
DAY_END = DAY_START + 86_400.0
ENV_DATA_DIR = "OVENBIRD_DATA_DIR"


@pytest.fixture
def capture(tmp_path: Path) -> Path:
    folder = tmp_path / "capture"
    folder.mkdir()
    shutil.copy(FIXTURE, folder / FIXTURE.name)
    return folder


def _options(capture: Path, out: Path, *, force: bool = False) -> ConvertOptions:
    return ConvertOptions(capture=capture, out=out, start=DAY, end=DAY, config=SEED, force=force)


def _converted(capture: Path, out: Path) -> Path:
    settings, values = build_settings(SEED)
    return convert(_options(capture, out), settings, values).history_path


def test_the_identity_check_reproduces_every_recorded_setpoint(
    capture: Path, tmp_path: Path
) -> None:
    settings, values = build_settings(SEED)
    result = convert(_options(capture, tmp_path / "out"), settings, values)
    assert result.decisions >= 100
    assert len(result.days) == 1

    def config_of(version: int | None) -> OvenbirdConfig | None:
        return settings.controller_config()

    replay = run_open_loop(
        result.history_path, settings, None, settings, config_of, (DAY_START, DAY_END)
    )

    assert replay["identity_ticks"] > 0
    assert replay["identity_ok"] is True, replay["identity_first_mismatch"]
    assert replay["ticks"] == result.decisions
    assert replay["skipped"] == 0
    assert len(decisions_between(result.history_path, DAY_START, DAY_END)) == result.decisions


def test_the_samples_and_rollups_are_the_services(capture: Path, tmp_path: Path) -> None:
    path = _converted(capture, tmp_path / "out")
    with sqlite3.connect(path) as db:
        names = {row[0] for row in db.execute("SELECT name FROM signal")}
        assert {
            "main/Z1_Water_Target_Temp",
            "main/Outside_Temp",
            "derived/heat_delivered_w",
            "room_temperature",
        } <= names
        minute = db.execute(
            "SELECT COUNT(*) FROM rollup r JOIN signal s ON s.id = r.signal_id "
            "WHERE r.step = 60 AND s.name = 'main/Z1_Water_Target_Temp'"
        ).fetchone()[0]
        assert minute > 0
        steps = {row[0] for row in db.execute("SELECT DISTINCT step FROM rollup")}
        assert steps == {60, 900, 3600}
        assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] > 0


def test_recorded_commands_are_not_ovenbirds_writes(capture: Path, tmp_path: Path) -> None:
    path = _converted(capture, tmp_path / "out")
    rows = query_commands(path, DAY_START, DAY_END, 100)
    assert {row.kind for row in rows} == {"water_setpoint", "max_pump_duty"}
    assert {row.status for row in rows} == {RECORDED_STATUS}
    assert all("recorded from the capture" in row.detail for row in rows)
    with sqlite3.connect(path) as db:
        counted = db.execute(
            "SELECT COUNT(*) FROM command WHERE status IN ('sent', 'verified')"
        ).fetchone()[0]
    assert counted == 0


def test_the_effective_seed_is_written_next_to_the_database(capture: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _converted(capture, out)
    written = json.loads((out / "config-seed.json").read_text(encoding="utf-8"))
    expected = json.loads(SEED.read_text(encoding="utf-8"))["values"]
    assert written["ovenbird_config"] == 1
    assert written["values"] == expected


def test_an_existing_database_needs_force(capture: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    _converted(capture, out)
    with pytest.raises(ConvertError, match="--force"):
        check_output(out, force=False)
    settings, values = build_settings(SEED)
    again = convert(_options(capture, out, force=True), settings, values)
    assert again.decisions > 0


def test_the_production_data_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "service"))
    with pytest.raises(ConvertError, match="data directory"):
        check_output(tmp_path / "service", force=True)


def test_the_command_line_converts_and_refuses(
    capture: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = [
        *("--capture", str(capture)),
        *("--from", "2026-01-06", "--to", "2026-01-06"),
        *("--config", str(SEED)),
        *("--out", str(tmp_path / "out")),
    ]
    assert main(argv) == 0
    assert "per recorded day" in capsys.readouterr().out
    assert main(argv) == 1
    assert "--force" in capsys.readouterr().err
    assert main([*argv, "--force", "--config-version", "1"]) == 0
