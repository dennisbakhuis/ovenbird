from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ovenbird_sim.learn import models as store

pytestmark = pytest.mark.skipif(store.FCNTL is None, reason="needs fcntl")


def child(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-P", "-m", "ovenbird_sim.learn", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_help_runs_as_the_service_starts_it(tmp_path: Path) -> None:
    (tmp_path / "json.py").write_text("raise SystemExit(99)\n")
    result = child("--help", cwd=tmp_path)
    assert result.returncode == 0
    assert "--low-priority" in result.stdout


def test_low_priority_lowers_nice_and_caps_cpu(tmp_path: Path) -> None:
    code = (
        "import os, resource;"
        "from ovenbird_sim.learn.__main__ import apply_low_priority;"
        "apply_low_priority(900);"
        "print(os.nice(0), resource.getrlimit(resource.RLIMIT_CPU)[0])"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-P", "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    nice, cpu = result.stdout.split()
    assert int(nice) >= 15
    assert int(cpu) == 900


def test_a_second_learner_exits_75_and_leaves_the_status_alone(tmp_path: Path) -> None:
    models = tmp_path / "models"
    with store.learner_lock(models) as held:
        assert held
        result = child(
            "--history",
            str(tmp_path / "h.db"),
            "--config",
            str(tmp_path / "c.json"),
            "--models",
            str(models),
            "--low-priority",
            "600",
            cwd=tmp_path,
        )
    assert result.returncode == 75
    assert not (models / store.STATUS).exists()
    with store.learner_lock(models) as held:
        assert held


def test_the_lock_is_free_after_the_holder_dies(tmp_path: Path) -> None:
    models = tmp_path / "models"
    code = (
        "import sys, time, pathlib;"
        "from ovenbird_sim.learn import models as m;"
        "cm = m.learner_lock(pathlib.Path(sys.argv[1])); cm.__enter__();"
        "print('held', flush=True); time.sleep(60)"
    )
    holder = subprocess.Popen(  # noqa: S603
        [sys.executable, "-P", "-c", code, str(models)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        with store.learner_lock(models) as held:
            assert not held
    finally:
        holder.kill()
        holder.wait()
    with store.learner_lock(models) as held:
        assert held


def test_the_lock_file_is_never_followed(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    target = tmp_path / "elsewhere"
    target.write_text("x")
    (models / store.LOCK).symlink_to(target)
    with pytest.raises(OSError, match="symbolic"), store.learner_lock(models):
        pass


def write_model(models: Path, day: str, extra: str = "") -> None:
    for kind in ("house", "insight", "series"):
        (models / f"{kind}-{day}{extra}.json").write_text("{}")


def test_prune_keeps_the_champion_the_previous_champion_and_the_newest(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    days = [f"2026{m:02d}{d:02d}" for m in (1, 2, 3, 4) for d in range(1, 11)]
    for day in days:
        write_model(models, day)
    write_model(models, days[0], "-2")
    store.write_json(models / store.CURRENT, {"model": f"house-{days[0]}"})
    store.write_json(
        models / store.INDEX,
        {
            "runs": [
                {"model": f"house-{days[1]}", "promoted": True},
                {"model": f"house-{days[0]}", "promoted": True},
                {"model": f"house-{days[2]}", "promoted": False},
            ]
        },
    )
    (models / "notes.json").write_text("{}")
    (models / "house-bad.json").write_text("{}")
    removed = store.prune(models)
    left = {p.name for p in models.iterdir()}
    assert len(removed) % 3 == 0
    assert {store.CURRENT, store.INDEX, "notes.json", "house-bad.json"} <= left
    for protected in (days[0], days[1]):
        assert f"house-{protected}.json" in left
        assert f"series-{protected}.json" in left
    assert f"insight-{days[0]}-2.json" not in left
    for newest in days[-30:]:
        assert f"insight-{newest}.json" in left
    assert f"house-{days[2]}.json" not in left


def test_prune_never_follows_links(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    for index in range(3):
        write_model(models, f"2026010{index + 1}")
    (models / "house-20250101.json").symlink_to(outside)
    store.prune(models, keep=1)
    assert outside.exists()
    assert (models / "house-20250101.json").is_symlink()
    assert not (models / "house-20260101.json").exists()
    assert (models / "house-20260103.json").exists()


def test_a_run_prunes_inside_the_lock_and_keeps_the_status(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (tmp_path / "c.json").write_text(json.dumps({}))
    result = child(
        "--history",
        str(tmp_path / "missing.db"),
        "--config",
        str(tmp_path / "c.json"),
        "--models",
        str(models),
        cwd=tmp_path,
    )
    assert result.returncode in (0, 1)
    assert (models / store.LOCK).exists()
    assert os.access(models / store.LOCK, os.R_OK)
