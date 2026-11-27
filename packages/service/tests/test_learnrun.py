from __future__ import annotations

import asyncio
import importlib.util
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.insight import house, learnrun
from ovenbird.insight.learnrun import (
    Child,
    LearnerRunningError,
    LearnerUnavailableError,
    LearnRunner,
)
from ovenbird.runtime import Runtime
from ovenbird.system.facts import Facts
from ovenbird.testing import FakeClock

AMS = ZoneInfo("Europe/Amsterdam")
NIGHT = datetime(2026, 11, 28, 2, 30, tzinfo=AMS).astimezone(UTC)
TOKEN = "operate-token-" + "x" * 24
MARK = {"X-Ovenbird-Request": "1"}
BEARER = {"Authorization": f"Bearer {TOKEN}"}


class Clock:
    """Wall and monotonic time that only the injected sleep advances."""

    def __init__(self, start: datetime) -> None:
        self.utc = start
        self.mono = 1000.0

    def now(self) -> datetime:
        return self.utc

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.utc += timedelta(seconds=seconds)
        self.mono += seconds

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)


class FakeChild:
    """A child that exits at once with ``code`` or hangs until it is stopped."""

    def __init__(
        self, code: int = 0, output: bytes = b"", *, hang: bool = False, obey_term: bool = True
    ) -> None:
        self.code = code
        self.obey_term = obey_term
        self.signals: list[str] = []
        self._pid = 4242
        self._stdout = asyncio.StreamReader()
        self._stdout.feed_data(output)
        self._done = asyncio.Event()
        if not hang:
            self._finish(code)

    @property
    def pid(self) -> int | None:
        return self._pid

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        return self._stdout

    def _finish(self, code: int) -> None:
        self.code = code
        self._stdout.feed_eof()
        self._done.set()

    async def wait(self) -> int:
        await self._done.wait()
        return self.code

    def terminate(self) -> None:
        self.signals.append("term")
        if self.obey_term:
            self._finish(-15)

    def kill(self) -> None:
        self.signals.append("kill")
        self._finish(-9)


class Rig:
    def __init__(self, settings: Settings, **options: Any) -> None:
        self.settings = settings
        self.clock = Clock(NIGHT)
        self.children: list[FakeChild] = []
        self.spawned: list[tuple[Sequence[str], Mapping[str, str]]] = []
        self.next_child: Callable[[], FakeChild] = FakeChild
        self.rss_bytes: int | None = None
        self.spawn_error: Exception | None = None
        self.exports = 0
        self.snapshot: Path | None = settings.data_dir / "snap"
        self.facts = Facts()
        self.runner = self.build(**options)

    def build(self, **options: Any) -> LearnRunner:
        return LearnRunner(
            lambda: self.settings,
            self.facts,
            available=options.pop("available", lambda: True),
            spawn=self.spawn,
            rss=lambda _pid: self.rss_bytes,
            now=self.clock.now,
            monotonic=self.clock.monotonic,
            sleep=self.clock.sleep,
            export=self.export,
        )

    async def spawn(self, argv: Sequence[str], env: Mapping[str, str]) -> Child:
        if self.spawn_error is not None:
            raise self.spawn_error
        self.spawned.append((argv, env))
        child = self.next_child()
        self.children.append(child)
        return child

    def export(self, _settings: Settings) -> Path | None:
        self.exports += 1
        return self.snapshot

    def status(self, *, ago_h: float, outcome: str = "promoted", **extra: Any) -> None:
        models = house.models_dir(self.settings)
        models.mkdir(parents=True, exist_ok=True)
        at = (self.clock.now() - timedelta(hours=ago_h)).isoformat(timespec="seconds")
        (models / "status.json").write_text(json.dumps({"at": at, "outcome": outcome, **extra}))

    async def tick(self) -> None:
        await self.runner.tick()
        if self.runner._task is not None:
            await self.runner._task

    async def until_spawned(self) -> None:
        for _ in range(200):
            if self.children:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("no child was spawned")

    async def finish(self) -> None:
        task = self.runner._task
        assert task is not None
        await task


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(control_timezone="Europe/Amsterdam", operate_token=TOKEN)


@pytest.fixture
def rig(settings: Settings) -> Rig:
    return Rig(settings)


async def after_start_delay(rig: Rig) -> None:
    rig.clock.advance(11 * 60)


async def test_a_run_spawns_the_fixed_command_with_a_limited_environment(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OVENBIRD_ADMIN_PASSWORD", "secret")
    rig.runner.start()
    await rig.finish()
    (argv, env), *_ = rig.spawned
    folder = house.learner_dir(rig.settings)
    assert list(argv)[1:] == [
        "-m",
        "ovenbird_sim.learn",
        "--history",
        str(folder / "history.snapshot.db"),
        "--config",
        str(folder / "learner-config.json"),
        "--models",
        str(house.models_dir(rig.settings)),
        "--building-only",
    ]
    assert env["OPENBLAS_NUM_THREADS"] == env["OMP_NUM_THREADS"] == env["MKL_NUM_THREADS"] == "1"
    assert "OVENBIRD_ADMIN_PASSWORD" not in env
    assert rig.exports == 1
    assert rig.runner.failure is None
    assert rig.runner.state == "idle"


async def test_unavailable_never_spawns(settings: Settings) -> None:
    rig = Rig(settings, available=lambda: False)
    rig.status(ago_h=1000)
    with pytest.raises(LearnerUnavailableError):
        rig.runner.start()
    await after_start_delay(rig)
    await rig.tick()
    assert rig.spawned == []
    body = rig.runner.payload()
    assert body["state"] == "unavailable"
    assert body["next_due_at"] is None


def test_learner_installed_reads_the_module_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    assert learnrun.learner_installed() is False

    def broken(_name: str) -> None:
        raise ModuleNotFoundError("no parent")

    monkeypatch.setattr(importlib.util, "find_spec", broken)
    assert learnrun.learner_installed() is False


async def test_nothing_starts_in_the_first_ten_minutes(rig: Rig) -> None:
    await rig.tick()
    assert rig.spawned == []
    rig.clock.advance(9 * 60)
    await rig.tick()
    assert rig.spawned == []
    rig.clock.advance(2 * 60)
    await rig.tick()
    assert len(rig.spawned) == 1


async def test_a_run_is_due_when_the_status_is_older_than_the_interval(rig: Rig) -> None:
    await after_start_delay(rig)
    rig.status(ago_h=24)
    await rig.tick()
    assert rig.spawned == []
    rig.status(ago_h=166)
    await rig.tick()
    assert rig.spawned == []
    rig.status(ago_h=167)
    await rig.tick()
    assert len(rig.spawned) == 1


async def test_a_missing_status_is_due(rig: Rig) -> None:
    await after_start_delay(rig)
    await rig.tick()
    assert len(rig.spawned) == 1


async def test_scheduled_runs_wait_for_the_night_window(rig: Rig) -> None:
    rig.status(ago_h=500)
    for hour in (1, 5, 12, 23):
        rig.clock.utc = datetime(2026, 11, 29, hour, 30, tzinfo=AMS).astimezone(UTC)
        rig.runner.born = rig.clock.utc - timedelta(days=1)
        await rig.tick()
    assert rig.spawned == []
    rig.clock.utc = datetime(2026, 11, 30, 4, 59, tzinfo=AMS).astimezone(UTC)
    await rig.tick()
    assert len(rig.spawned) == 1


async def test_run_now_ignores_the_window_and_the_schedule(rig: Rig) -> None:
    rig.clock.utc = datetime(2026, 11, 28, 14, tzinfo=AMS).astimezone(UTC)
    rig.status(ago_h=1)
    rig.runner.start()
    await rig.finish()
    assert len(rig.spawned) == 1


async def test_a_learning_outcome_is_retried_daily(rig: Rig) -> None:
    await after_start_delay(rig)
    rig.status(ago_h=20, outcome="learning", missing=["more data"])
    await rig.tick()
    assert rig.spawned == []
    rig.status(ago_h=23.5, outcome="learning")
    await rig.tick()
    assert len(rig.spawned) == 1


async def test_a_long_interval_is_still_retried_daily_when_learning(
    make_settings: Callable[..., Settings],
) -> None:
    rig = Rig(make_settings(control_timezone="Europe/Amsterdam", house_learn_interval_h=720.0))
    await after_start_delay(rig)
    rig.status(ago_h=30, outcome="learning")
    await rig.tick()
    assert len(rig.spawned) == 1


async def test_disabled_never_schedules_but_run_now_works(
    make_settings: Callable[..., Settings],
) -> None:
    rig = Rig(make_settings(control_timezone="Europe/Amsterdam", house_learn_enabled=False))
    await after_start_delay(rig)
    await rig.tick()
    assert rig.spawned == []
    body = rig.runner.payload()
    assert body["enabled"] is False
    assert body["next_due_at"] is None
    rig.runner.start()
    await rig.finish()
    assert len(rig.spawned) == 1


async def test_a_simulated_clock_never_schedules(
    make_settings: Callable[..., Settings],
) -> None:
    rig = Rig(make_settings(control_timezone="Europe/Amsterdam", clock_speed=60.0))
    await after_start_delay(rig)
    await rig.tick()
    assert rig.spawned == []


async def test_a_failure_backs_off_for_a_day_and_survives_a_restart(rig: Rig) -> None:
    await after_start_delay(rig)
    rig.spawn_error = FileNotFoundError("no python")
    await rig.tick()
    await rig.finish()
    failure = rig.runner.failure
    assert failure is not None
    assert failure.reason == "spawn"
    assert "no python" in failure.detail
    rig.spawn_error = None
    next_night = NIGHT + timedelta(days=1)
    rig.clock.utc = next_night
    await rig.tick()
    assert rig.spawned == []
    restarted = rig.build()
    restarted.born = next_night - timedelta(days=3)
    assert restarted.failure == failure
    await restarted.tick()
    assert rig.spawned == []
    rig.clock.utc = NIGHT + timedelta(days=2)
    await restarted.tick()
    assert restarted._task is not None
    await restarted._task
    assert len(rig.spawned) == 1


async def test_a_success_clears_the_failure(rig: Rig) -> None:
    rig.spawn_error = OSError("boom")
    rig.runner.start()
    await rig.finish()
    assert rig.runner.failure is not None
    rig.spawn_error = None
    rig.runner.start()
    await rig.finish()
    assert rig.runner.failure is None
    assert rig.facts.get(learnrun.FACT_KEY) is None
    assert rig.runner.payload()["failure"] is None


async def test_a_nonzero_exit_reports_the_tail_of_the_output(rig: Rig) -> None:
    noise = b"x" * 20000
    rig.next_child = lambda: FakeChild(1, noise + b"\nTraceback\nValueError: no data")
    rig.runner.start()
    await rig.finish()
    failure = rig.runner.failure
    assert failure is not None
    assert failure.reason == "exit"
    assert failure.detail.startswith("exit code 1")
    assert failure.detail.endswith("ValueError: no data")
    assert len(failure.detail) <= learnrun.MAX_DETAIL


async def test_a_run_past_the_timeout_is_terminated(rig: Rig) -> None:
    rig.next_child = lambda: FakeChild(hang=True, output=b"still fitting")
    rig.runner.start()
    await rig.finish()
    child = rig.children[0]
    assert child.signals == ["term"]
    failure = rig.runner.failure
    assert failure is not None
    assert failure.reason == "timeout"
    assert "still fitting" in failure.detail


async def test_a_child_that_ignores_terminate_is_killed(rig: Rig) -> None:
    rig.next_child = lambda: FakeChild(hang=True, obey_term=False)
    rig.runner.start()
    await rig.finish()
    assert rig.children[0].signals == ["term", "kill"]
    assert rig.runner.failure is not None
    assert rig.runner.failure.reason == "timeout"


async def test_a_child_above_the_memory_cap_is_stopped_early(rig: Rig) -> None:
    rig.next_child = lambda: FakeChild(hang=True)
    rig.rss_bytes = learnrun.MEMORY_CAP_BYTES + 1
    rig.runner.start()
    await rig.finish()
    failure = rig.runner.failure
    assert failure is not None
    assert failure.reason == "memory"
    assert rig.children[0].signals == ["term"]
    assert rig.clock.mono < 1000.0 + learnrun.TIMEOUT_S


async def test_a_missing_rss_reader_is_skipped(rig: Rig) -> None:
    rig.next_child = lambda: FakeChild(hang=True)
    rig.rss_bytes = None
    rig.runner.start()
    await rig.finish()
    assert rig.runner.failure is not None
    assert rig.runner.failure.reason == "timeout"


async def test_no_history_snapshot_is_a_failed_attempt_that_spawns_nothing(rig: Rig) -> None:
    rig.snapshot = None
    rig.runner.start()
    await rig.finish()
    assert rig.spawned == []
    assert rig.runner.failure is not None
    assert rig.runner.failure.reason == "spawn"


async def test_only_one_run_at_a_time(rig: Rig) -> None:
    rig.next_child = lambda: FakeChild(hang=True)
    rig.runner.start()
    assert rig.runner.state == "running"
    with pytest.raises(LearnerRunningError):
        rig.runner.start()
    await rig.runner.tick()
    body = rig.runner.payload()
    assert body["state"] == "running"
    assert body["started_at"] is not None
    await rig.finish()
    assert len(rig.spawned) == 1
    assert rig.runner.payload()["state"] == "idle"
    assert rig.runner.payload()["started_at"] is None


async def test_the_component_stops_a_running_child_when_cancelled(rig: Rig) -> None:
    rig.next_child = lambda: FakeChild(hang=True)
    rig.runner.start()
    await rig.until_spawned()
    runner = asyncio.create_task(rig.runner.run())
    await asyncio.sleep(0)
    runner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runner
    await asyncio.sleep(0)
    assert rig.runner.running is False
    assert rig.children[0].signals[-1] == "kill"


def test_the_night_window_follows_local_time_across_dst() -> None:
    assert learnrun.in_night_window(datetime(2026, 12, 1, 0, 30, tzinfo=UTC), AMS) is False
    assert learnrun.in_night_window(datetime(2026, 12, 1, 1, 0, tzinfo=UTC), AMS) is True
    assert learnrun.in_night_window(datetime(2026, 12, 1, 3, 59, tzinfo=UTC), AMS) is True
    assert learnrun.in_night_window(datetime(2026, 12, 1, 4, 0, tzinfo=UTC), AMS) is False
    assert learnrun.in_night_window(datetime(2026, 7, 1, 0, 0, tzinfo=UTC), AMS) is True
    assert learnrun.in_night_window(datetime(2026, 7, 1, 3, 0, tzinfo=UTC), AMS) is False
    late = datetime(2026, 12, 1, 12, tzinfo=UTC)
    assert learnrun.next_night_window(late, AMS) == datetime(2026, 12, 2, 1, tzinfo=UTC)
    early = datetime(2026, 12, 1, 0, 10, tzinfo=UTC)
    assert learnrun.next_night_window(early, AMS) == datetime(2026, 12, 1, 1, tzinfo=UTC)
    assert learnrun.next_night_window(NIGHT, AMS) == NIGHT


async def test_the_payload_names_the_next_due_time_and_the_last_run(rig: Rig) -> None:
    rig.clock.utc = datetime(2026, 11, 28, 12, tzinfo=AMS).astimezone(UTC)
    rig.status(ago_h=24, outcome="promoted", model="house-1", runtime_s=11.4, message="ok")
    body = rig.runner.payload()
    assert body["state"] == "idle"
    assert body["enabled"] is True
    assert body["interval_h"] == 168.0
    assert body["failure"] is None
    assert body["next_due_at"] == "2026-12-05T01:00:00Z"
    assert body["last"] == {
        "at": (rig.clock.now() - timedelta(hours=24)).isoformat(timespec="seconds"),
        "outcome": "promoted",
        "message": "ok",
        "runtime_s": 11.4,
        "model": "house-1",
    }


async def test_a_status_without_outcome_is_no_last_run(rig: Rig) -> None:
    models = house.models_dir(rig.settings)
    models.mkdir(parents=True)
    (models / "status.json").write_text(json.dumps({"at": "2026-11-01T00:00:00+00:00"}))
    assert rig.runner.payload()["last"] is None


def test_the_learner_health_uses_the_configured_interval_when_embedded(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(house_learn_interval_h=48.0)
    models = house.models_dir(settings)
    models.mkdir(parents=True)
    now = datetime(2026, 12, 1, tzinfo=UTC)
    at = (now - timedelta(hours=100)).isoformat()
    (models / "status.json").write_text(json.dumps({"at": at, "outcome": "promoted"}))
    _, own = house.house_payload(models, settings, now, embedded=True)
    assert own["learner"]["interval_h"] == 48.0
    assert own["learner"]["stale"] is True
    _, other = house.house_payload(models, settings, now)
    assert other["learner"]["interval_h"] == 168.0
    assert other["learner"]["stale"] is False
    (models / "status.json").write_text(
        json.dumps({"at": at, "outcome": "promoted", "interval_h": 6})
    )
    _, external = house.house_payload(models, settings, now, embedded=True)
    assert external["learner"]["interval_h"] == 6.0


def test_the_learner_fields_are_in_the_config_and_the_learner_file(settings: Settings) -> None:
    effective = house.learner_config(settings, None)["effective"]
    assert effective["house_learn_enabled"] is True
    assert effective["house_learn_interval_h"] == 168.0


def test_the_learner_ignores_the_new_config_keys() -> None:
    historydb = pytest.importorskip("ovenbird_sim.data.historydb")
    effective = {
        "house_learn_enabled": True,
        "house_learn_interval_h": 168.0,
        "control_timezone": "UTC",
    }
    config = historydb.effective_config({"effective": effective})
    assert historydb.roles_from_config(config).timezone == "UTC"


def api_client(settings: Settings, runner: LearnRunner | None) -> tuple[TestClient, ConfigManager]:
    clock = FakeClock()
    manager = ConfigManager.open(settings, clock, locked={})
    app = create_app(Runtime(clock=clock), manager.settings, config=manager, learn=runner)
    return TestClient(app), manager


def test_get_run_reports_the_state_without_a_runner(settings: Settings) -> None:
    client, _ = api_client(settings, None)
    with client:
        response = client.get("/api/v1/insight/house/run")
        refused = client.post("/api/v1/insight/house/run", json={}, headers={**BEARER, **MARK})
    assert response.status_code == 200
    assert response.json() == {
        "state": "unavailable",
        "enabled": True,
        "started_at": None,
        "next_due_at": None,
        "interval_h": 168.0,
        "last": None,
        "failure": None,
    }
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "learner_unavailable"
    assert refused.json()["detail"]["params"] == {}


def test_post_run_starts_a_run_and_refuses_a_second(settings: Settings) -> None:
    rig = Rig(settings)
    rig.next_child = lambda: FakeChild(hang=True)
    rig.runner.sleep = asyncio.sleep
    client, manager = api_client(settings, rig.runner)
    with client:
        started = client.post("/api/v1/insight/house/run", json={}, headers={**BEARER, **MARK})
        again = client.post("/api/v1/insight/house/run", json={}, headers={**BEARER, **MARK})
        shown = client.get("/api/v1/insight/house/run")
    assert started.status_code == 202, started.text
    assert started.json()["state"] == "running"
    assert started.json()["started_at"] is not None
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "learner_running"
    assert shown.json()["state"] == "running"
    actions = [event.action for event in manager.store.audit_events(0.0, 1e12, 50)]
    assert "house_learn_run" in actions


def test_run_endpoints_enforce_roles(settings: Settings) -> None:
    rig = Rig(settings)
    client, _ = api_client(settings, rig.runner)
    with client:
        assert client.get("/api/v1/insight/house/run").status_code == 200
        anonymous = client.post("/api/v1/insight/house/run", json={}, headers=MARK)
        no_mark = client.post("/api/v1/insight/house/run", json={}, headers=BEARER)
    assert anonymous.status_code in (401, 403)
    assert no_mark.status_code in (400, 401, 403)
    assert rig.spawned == []
