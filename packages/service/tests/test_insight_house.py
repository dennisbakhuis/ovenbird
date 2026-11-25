from __future__ import annotations

import json
import math
import os
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.history.database import HEAT_SIGNAL, Sample
from ovenbird.insight import house
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock
from ovenbird_core import HeishaSignal, Instant, Reading, SourceKind

TOKEN = "operate-token-" + "x" * 24
PASSWORD = "pw-123"
MARK = {"X-Ovenbird-Request": "1"}
BEARER = {"Authorization": f"Bearer {TOKEN}"}
MODEL = "house-20261113"
CURVE = [[-10.0, 39.0], [0.0, 34.0], [15.0, 25.0]]
PROPOSED = [[-10.0, 38.0], [0.0, 33.5], [15.0, 25.0]]


def insight(*, credible: bool = True) -> dict[str, Any]:
    return {
        "schema": "ovenbird.house-insight/1",
        "model": MODEL,
        "ua": {"w_per_k": 145.0, "interval_90": [136.0, 156.0], "source": "rc_model"},
        "time_constant_h": {"value": 50.0, "interval_90": [45.0, 60.0]},
        "credibility": {
            "credible": credible,
            "message": None if credible else "insufficient data: 4 more cold days needed",
        },
        "score": {"state": "stale value from the learner"},
        "proposal": {
            "based_on_curve": CURVE,
            "curve": PROPOSED,
            "credible": credible,
            "points": [{"outside_c": o, "water_c": w} for o, w in PROPOSED],
        },
    }


def write_models(root: Path, *, credible: bool = True) -> Path:
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    (models / f"{MODEL}.json").write_text("{}", encoding="utf-8")
    (models / "insight-20261113.json").write_text(json.dumps(insight(credible=credible)))
    (models / "current.json").write_text(
        json.dumps(
            {
                "model": MODEL,
                "house": f"{MODEL}.json",
                "insight": "insight-20261113.json",
                "promoted_at": "2026-11-13T18:00:00+00:00",
            }
        )
    )
    runs = [
        {
            "model": "house-20261106",
            "data_to": "2026-11-06T18:00:00+00:00",
            "promoted": True,
            "ua_w_per_k": 340.0,
            "ua_interval_90": [300.0, 380.0],
            "credible": False,
        },
        {
            "model": "house-20261110",
            "data_to": "2026-11-10T18:00:00+00:00",
            "promoted": False,
            "ua_w_per_k": 400.0,
        },
        {
            "model": MODEL,
            "data_to": "2026-11-13T18:00:00+00:00",
            "promoted": True,
            "ua_w_per_k": 145.0,
            "ua_interval_90": [136.0, 156.0],
            "credible": True,
            "challenger_room_rmse_k": 0.4,
        },
    ]
    (models / "index.json").write_text(json.dumps({"runs": runs}))
    (models / "status.json").write_text(json.dumps({"at": "x", "outcome": "promoted"}))
    return models


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(operate_token=TOKEN, house_floor_area_m2=130.0)


def client_for(settings: Settings) -> tuple[TestClient, ConfigManager]:
    clock = FakeClock()
    manager = ConfigManager.open(settings, clock, locked={})
    app = create_app(Runtime(clock=clock), manager.settings, config=manager)
    return TestClient(app), manager


def test_score_constants_match_the_learner() -> None:
    score = pytest.importorskip("ovenbird_sim.learn.score")
    assert house.BANDS == score.BANDS
    assert house.DESIGN_INDOOR_C == score.DESIGN_INDOOR_C
    assert house.DESIGN_OUTSIDE_C == score.DESIGN_OUTSIDE_C
    for w in (10.0, 30.0, 59.9, 80.0, 124.9, 500.0):
        assert house.band(w) == score.band(w)
    assert house.score(145.0, [136.0, 156.0], 130.0, credible=True) == score.score(
        145.0, (136.0, 156.0), 130.0, credible=True
    )


@pytest.mark.parametrize(
    ("w_per_m2", "letter"),
    [(0.0, "A"), (29.9, "A"), (30.0, "B"), (45.0, "C"), (60.0, "D"), (99.9, "E"), (125.0, "G")],
)
def test_bands(w_per_m2: float, letter: str) -> None:
    assert house.band(w_per_m2) == letter


def test_score_states() -> None:
    ready = house.score(145.0, [136.0, 156.0], 130.0, credible=True)
    assert ready["state"] == "ready"
    assert ready["heat_loss_w"] == round(145.0 * 30)
    assert math.isclose(ready["w_per_m2"], 33.5)
    assert ready["band"] == "B"
    assert ready["interval_90"] == [31.4, 36.0]
    assert ready["band_interval"] == ["B", "B"]
    assert ready["indicative"] is True
    assert "not the official energielabel" in ready["note"].lower()
    assert house.score(145.0, None, None, credible=True)["state"] == "no_floor_area"
    learning = house.score(145.0, None, 130.0, credible=False, message="4 more cold days")
    assert learning["state"] == "learning"
    assert "w_per_m2" not in learning
    assert learning["message"] == "4 more cold days"


def test_house_not_run_and_learning(settings: Settings) -> None:
    client, _ = client_for(settings)
    with client:
        response = client.get("/api/v1/insight/house")
        assert response.status_code == 200
        assert response.json()["state"] == "not_run"
        assert response.json()["learner"]["last_run_at"] is None
        models = settings.data_dir / "models"
        (models / "status.json").write_text(
            json.dumps({"at": "x", "outcome": "learning", "missing": ["9 more days"]})
        )
        response = client.get("/api/v1/insight/house")
    assert response.status_code == 200
    assert response.json()["state"] == "learning"
    assert response.json()["missing"] == ["9 more days"]


def test_house_payload_recomputes_score_and_flags_stale_proposal(settings: Settings) -> None:
    write_models(settings.data_dir)
    client, _ = client_for(settings)
    with client:
        body = client.get("/api/v1/insight/house").json()
    assert body["state"] == "ready"
    assert body["champion"]["model"] == MODEL
    assert body["score"]["state"] == "ready"
    assert body["score"]["band"] == "B"
    assert body["score"]["floor_area_m2"] == 130.0
    assert body["proposal"]["current_curve"] == CURVE
    assert body["proposal"]["stale"] is False


def test_house_score_without_floor_area_or_credibility(
    make_settings: Callable[..., Settings],
) -> None:
    plain = make_settings()
    write_models(plain.data_dir, credible=False)
    client, _ = client_for(plain)
    with client:
        body = client.get("/api/v1/insight/house").json()
    assert body["score"]["state"] == "learning"
    assert body["score"]["message"] == "insufficient data: 4 more cold days needed"


def test_house_history_lists_promoted_models(settings: Settings) -> None:
    write_models(settings.data_dir)
    client, _ = client_for(settings)
    with client:
        body = client.get("/api/v1/insight/house/history").json()
    assert [m["model"] for m in body["models"]] == ["house-20261106", MODEL]
    assert [m["champion"] for m in body["models"]] == [False, True]
    assert body["models"][0]["score"]["state"] == "learning"
    assert body["models"][1]["score"]["band"] == "B"


def test_proposal_draft_is_validated_not_applied(settings: Settings) -> None:
    write_models(settings.data_dir)
    client, manager = client_for(settings)
    with client:
        refused = client.post("/api/v1/insight/house/proposal/draft", json={})
        response = client.post(
            "/api/v1/insight/house/proposal/draft", json={}, headers={**BEARER, **MARK}
        )
    assert refused.status_code in (401, 403)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "Suggested by the house model"
    assert body["changes"] == {"control_curve": PROPOSED}
    assert body["validation"]["valid"] is True
    assert body["stale"] is False
    assert manager.version is None
    assert manager.store.latest() is None


def test_proposal_draft_without_champion(settings: Settings) -> None:
    client, _ = client_for(settings)
    with client:
        response = client.post(
            "/api/v1/insight/house/proposal/draft", json={}, headers={**BEARER, **MARK}
        )
    assert response.status_code == 404


def test_learner_config_is_written_and_has_no_secrets(settings: Settings) -> None:
    client_for(settings)
    written = json.loads((settings.data_dir / "learner" / "learner-config.json").read_text())
    effective = written["effective"]
    assert effective["house_floor_area_m2"] == 130.0
    assert effective["control_curve"] == CURVE
    assert "control_timezone" in effective
    assert not any(name.endswith(("token", "password")) for name in effective)


class Sink:
    def __init__(self) -> None:
        self.samples: list[Sample] = []

    def offer(self, sample: Sample) -> None:
        self.samples.append(sample)

    def healthy(self) -> bool:
        return True

    def starting(self) -> bool:
        return False


def test_loop_heat_is_stored_with_every_heat_input() -> None:
    clock = FakeClock()
    sink = Sink()
    runtime = Runtime(clock=clock, history=sink)
    values = {
        HeishaSignal.COMPRESSOR_FREQ: (30, "Hz"),
        HeishaSignal.THREEWAY_VALVE_STATE: (0, None),
        HeishaSignal.PUMP_FLOW: (15.0, "l/min"),
        HeishaSignal.INLET_TEMP: (28.0, "°C"),
        HeishaSignal.OUTLET_TEMP: (32.0, "°C"),
    }
    for signal, (value, unit) in values.items():
        now: Instant = clock()
        runtime.apply(Reading(signal, value, unit, now, SourceKind.HEISHAMON))
    heat = [s for s in sink.samples if s.signal == HEAT_SIGNAL]
    assert len(heat) == len(values)
    assert heat[-1].value == pytest.approx(15.0 / 60.0 * 0.996 * 4180.0 * 4.0, abs=0.1)
    assert heat[-1].unit == "W"
    assert heat[-1].max_hold > 0
    assert heat[0].value is None


def write_insight(models: Path, payload: str) -> None:
    (models / "insight-20261113.json").unlink()
    (models / "insight-20261113.json").write_text(payload)


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ('{"ua": {"w_per_k": NaN}, "credibility": {"credible": true}}', "NaN"),
        ('{"ua": {"w_per_k": Infinity}, "credibility": {"credible": true}}', "Infinity"),
        ('{"ua": {"w_per_k": 100, "interval_90": ["a", "b"]}}', "ua.interval_90"),
        ('{"ua": {"w_per_k": "lots"}}', "ua.w_per_k"),
        ('{"credibility": {"credible": "yes"}}', "credibility.credible"),
        ('{"proposal": {"curve": [[1, 2, 3]]}}', "proposal.curve"),
        ('{"limits": "' + "x" * 5000 + '"}', "text too long"),
        ("[1, 2]", "not an object"),
        ("{not json", "invalid JSON"),
    ],
)
def test_a_bad_insight_is_not_served(settings: Settings, payload: str, why: str) -> None:
    models = write_models(settings.data_dir)
    write_insight(models, payload)
    status, body = house.house_payload(models, settings)
    assert status == 200
    assert body["state"] == "learning"
    assert why in body["missing"][0]
    json.dumps(body, allow_nan=False)


def test_a_linked_insight_is_refused(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    secret = settings.data_dir / "options.json"
    secret.write_text(json.dumps({"mqtt_password": "hunter2hunter2"}))
    (models / "insight-20261113.json").unlink()
    (models / "insight-20261113.json").symlink_to(secret.resolve())
    status, body = house.house_payload(models, settings)
    assert status == 200
    assert body["state"] == "learning"
    assert "hunter2" not in json.dumps(body)
    assert "cannot open" in body["missing"][0]
    for name in ("current.json", "status.json", "index.json"):
        (models / name).unlink()
        (models / name).symlink_to(secret.resolve())
    assert house.last_run(models) is None
    assert house.history_payload(models, settings)["models"] == []


def test_a_linked_models_directory_is_not_read(settings: Settings, tmp_path: Path) -> None:
    elsewhere = write_models(tmp_path / "elsewhere")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    link = settings.data_dir / "linked"
    link.symlink_to(elsewhere)
    status, body = house.house_payload(link, settings)
    assert (status, body["state"]) == (200, "not_run")


def test_an_oversized_or_special_file_is_refused(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    write_insight(models, json.dumps({"limits": ["x" * 1000] * 5000}))
    _, body = house.house_payload(models, settings)
    assert body["state"] == "learning"
    assert "larger than" in body["missing"][0]
    (models / "insight-20261113.json").unlink()
    os.mkfifo(models / "insight-20261113.json")
    _, body = house.house_payload(models, settings)
    assert "not a regular file" in body["missing"][0]


def test_only_allow_listed_insight_keys_are_served(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    payload = insight() | {"injected": {"mqtt_password": "x"}}
    write_insight(models, json.dumps(payload))
    _, body = house.house_payload(models, settings)
    assert body["state"] == "ready"
    assert "injected" not in body
    assert body["ua"]["w_per_k"] == 145.0


def test_bad_history_runs_are_left_out(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    index = json.loads((models / "index.json").read_text())
    index["runs"][0]["ua_w_per_k"] = "many"
    (models / "index.json").write_text(json.dumps(index))
    body = house.history_payload(models, settings)
    assert [m["model"] for m in body["models"]] == [MODEL]


def test_the_learner_config_is_never_written_through_a_link(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    victim = settings.data_dir / "config.db"
    victim.write_bytes(b"precious")
    models = settings.data_dir / "models"
    models.mkdir(parents=True)
    (models / "learner-config.json.tmp").symlink_to(victim.resolve())
    (models / "learner-config.json").symlink_to(victim.resolve())
    target = house.write_learner_config(settings, 3)
    assert target == settings.data_dir / "learner" / "learner-config.json"
    assert victim.read_bytes() == b"precious"
    assert not (models / "learner-config.json").exists()
    assert not (models / "learner-config.json").is_symlink()
    assert json.loads(target.read_text())["version"] == 3
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert stat.S_IMODE((settings.data_dir / "learner").stat().st_mode) == 0o750
    assert stat.S_IMODE(models.stat().st_mode) == 0o2770


def test_the_history_snapshot_is_exported_for_the_learner(settings: Settings) -> None:
    assert house.export_history(settings) is None
    snapshot = settings.snapshot_path
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"one")
    exported = house.export_history(settings)
    assert exported == settings.data_dir / "learner" / "history.snapshot.db"
    assert exported.read_bytes() == b"one"
    assert os.stat(exported).st_ino == os.stat(snapshot).st_ino
    assert house.export_history(settings) == exported
    fresh = snapshot.with_name("fresh.tmp")
    fresh.write_bytes(b"two")
    os.replace(fresh, snapshot)
    assert house.export_history(settings) == exported
    assert exported.read_bytes() == b"two"
    assert [p.name for p in exported.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_the_export_copies_where_links_fail(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise PermissionError("no links here")

    settings.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    settings.snapshot_path.write_bytes(b"copy me")
    monkeypatch.setattr(os, "link", refuse)
    exported = house.export_history(settings)
    assert exported is not None
    assert exported.read_bytes() == b"copy me"
    assert os.stat(exported).st_ino != os.stat(settings.snapshot_path).st_ino
    assert stat.S_IMODE(exported.stat().st_mode) == 0o640


def test_a_learner_that_stopped_running_marks_the_model_stale(settings: Settings) -> None:
    models = write_models(settings.data_dir)
    now = datetime(2026, 11, 30, 12, tzinfo=UTC)
    (models / "status.json").write_text(
        json.dumps({"at": "2026-11-13T12:00:00+00:00", "outcome": "promoted", "interval_h": 168})
    )
    _, body = house.house_payload(models, settings, now)
    assert body["learner"] == {
        "last_run_at": "2026-11-13T12:00:00+00:00",
        "age_h": 408.0,
        "interval_h": 168.0,
        "stale_after_h": 336.0,
        "stale": True,
    }
    (models / "status.json").write_text(
        json.dumps({"at": "2026-11-29T12:00:00+00:00", "outcome": "promoted", "interval_h": 6})
    )
    _, body = house.house_payload(models, settings, now)
    assert body["learner"]["stale"] is True
    (models / "status.json").write_text(
        json.dumps({"at": "2026-11-29T12:00:00+00:00", "outcome": "promoted"})
    )
    _, body = house.house_payload(models, settings, now)
    assert body["learner"]["interval_h"] == 168.0
    assert body["learner"]["stale"] is False
