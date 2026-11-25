from __future__ import annotations

import base64
import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ovenbird.api.app import create_app
from ovenbird.config import Settings
from ovenbird.configstore import Actor, ConfigManager
from ovenbird.control.adapter import Command
from ovenbird.control.alarms import AlarmCode, AlarmEvent, AlarmEventKind, Severity
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.service import build_control
from ovenbird.system.facts import Facts
from ovenbird.testing import FakeClock, inbound, pump_messages
from ovenbird.trial.release import (
    LAST_KEY,
    SNAPSHOT_KEY,
    PumpSnapshot,
    ReleaseManager,
    ReleaseRefusedError,
)
from ovenbird_core.control import IntentKind

PUBLISH: dict[str, Any] = {
    "control_mode": "auto",
    "control_pump_duty": True,
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}
BASE = "panasonic_heat_pump"
ADMIN = "pw-123"
MARK = {"X-Ovenbird-Request": "1"}
ACTOR = Actor("admin from 10.0.0.2", "10.0.0.2")


def basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def no_sleep(_: float) -> None:
    return None


class Rig:
    def __init__(self, settings: Settings, facts: Facts | None = None) -> None:
        self.clock = FakeClock()
        self.runtime = Runtime(clock=self.clock)
        self.ingest = MqttIngest(settings, self.runtime)
        self.facts = facts if facts is not None else Facts()
        self.loop, _ = build_control(settings, self.runtime, None, sleep=no_sleep, facts=self.facts)
        adapter = self.loop.adapter
        assert adapter is not None
        self.adapter = adapter
        release = self.loop.release
        assert release is not None
        self.release: ReleaseManager = release
        self.sent: list[Command] = []

    def pump(self, **overrides: str) -> None:
        for message in pump_messages(BASE, **overrides):
            self.ingest.ingest(message)

    def report(self, name: str, value: str) -> None:
        self.ingest.ingest(inbound(f"{BASE}/main/{name}", value))

    def step_adapter(self) -> Command | None:
        now = self.clock()
        store = self.runtime.store
        command = self.adapter.tick(
            now, lambda signal: store.view(signal, now), store.heishamon_status(now)
        )
        if command is not None:
            self.adapter.published(command, now)
            self.sent.append(command)
        return command


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(**PUBLISH, http_host="0.0.0.0", admin_password=ADMIN)


def go_live(rig: Rig) -> PumpSnapshot:
    rig.pump(Z1_Water_Target_Temp="30", Max_Pump_Duty="159", Quiet_Mode_Level="0")
    rig.loop.tick()
    snapshot = rig.release.snapshot
    assert snapshot is not None
    return snapshot


def test_the_snapshot_is_taken_at_go_live_before_anything_is_sent(settings: Settings) -> None:
    rig = Rig(settings)
    snapshot = go_live(rig)
    assert snapshot.items == {"water_setpoint": 30, "max_pump_duty": 159, "quiet_mode": 0}
    assert snapshot.previous_mode is None
    assert snapshot.register == "setcurves_target_high"
    assert snapshot.facts["main/Heating_Mode"] == 1.0
    assert snapshot.complete
    assert rig.facts.get(SNAPSHOT_KEY)["items"]["water_setpoint"] == 30
    assert rig.sent == []
    body = snapshot.to_json()
    assert body["own_values_possible"] is False
    assert [item["kind"] for item in body["items"]] == [
        "water_setpoint",
        "max_pump_duty",
        "quiet_mode",
    ]


def test_a_stale_value_is_filled_in_later_and_a_resume_keeps_the_snapshot(
    settings: Settings,
) -> None:
    rig = Rig(settings)
    messages = [m for m in pump_messages(BASE) if not m.topic.endswith("Quiet_Mode_Level")]
    for message in messages:
        rig.ingest.ingest(message)
    rig.loop.tick()
    snapshot = rig.release.snapshot
    assert snapshot is not None
    assert snapshot.items["quiet_mode"] is None
    rig.clock.advance(60)
    rig.report("Quiet_Mode_Level", "2")
    rig.loop.tick()
    assert snapshot.items["quiet_mode"] == 2
    taken = snapshot.taken_at
    rig.loop.guard.hold.paused = True
    rig.clock.advance(60)
    rig.loop.tick()
    rig.loop.guard.hold.paused = False
    rig.report("Z1_Water_Target_Temp", "35")
    rig.clock.advance(60)
    rig.loop.tick()
    assert rig.release.snapshot is snapshot
    assert snapshot.taken_at == taken
    assert snapshot.items["water_setpoint"] == 30


def test_release_restores_through_the_adapter_and_then_pauses(settings: Settings) -> None:
    rig = Rig(settings)
    go_live(rig)
    rig.clock.advance(30)
    rig.pump(Z1_Water_Target_Temp="34", Max_Pump_Duty="159", Quiet_Mode_Level="0")
    run = rig.release.start(ACTOR, rehearsal=True, reason="practice")
    assert rig.loop.guard.hold.releasing
    assert not run.done
    items = {item.kind: item for item in run.items}
    assert items[IntentKind.WATER_SETPOINT].status == "queued"
    assert items[IntentKind.WATER_SETPOINT].target == 30
    assert items[IntentKind.MAX_PUMP_DUTY].status == "unchanged"
    assert items[IntentKind.QUIET_MODE].status == "not_managed"
    assert rig.adapter.view().queued == {IntentKind.WATER_SETPOINT: 30}
    rig.loop.tick()
    assert rig.loop.latest is not None
    assert rig.loop.latest["mode"] == "shadow"
    assert rig.adapter.view().queued == {IntentKind.WATER_SETPOINT: 30}
    command = rig.step_adapter()
    assert command is not None
    assert command.restore
    assert command.payload == '{"zone1":{"heat":{"target":{"high":30}}}}'
    rig.clock.advance(5)
    rig.report("Z1_Water_Target_Temp", "30")
    rig.clock.advance(5)
    rig.step_adapter()
    assert run.done
    assert run.ok
    body = run.to_json()
    assert body["outcome"] == "ok"
    assert body["duration_s"] == 10.0
    assert body["within_limit"] is True
    assert body["by"] == "admin: practice"
    hold = rig.loop.guard.hold
    assert hold.paused
    assert not hold.releasing
    assert rig.release.snapshot is not None
    assert rig.release.snapshot.released_at is not None
    assert rig.release.last_rehearsal() == body
    assert rig.facts.get(LAST_KEY) == body
    rig.clock.advance(10)
    assert rig.step_adapter() is None
    assert [c.value for c in rig.sent] == [30]


def test_a_new_go_live_after_a_release_takes_a_new_snapshot(settings: Settings) -> None:
    rig = Rig(settings)
    first = go_live(rig)
    run = rig.release.start(ACTOR, rehearsal=False, reason=None)
    assert run.done
    assert {item.status for item in run.items} == {"unchanged", "not_managed"}
    assert rig.loop.guard.hold.paused
    rig.clock.advance(60)
    rig.loop.tick()
    assert rig.release.snapshot is first
    rig.loop.guard.hold.paused = False
    rig.clock.advance(60)
    rig.pump(Z1_Water_Target_Temp="28")
    rig.loop.tick()
    second = rig.release.snapshot
    assert second is not None
    assert second is not first
    assert second.items["water_setpoint"] == 28
    assert second.previous_mode == "shadow"


def test_release_refusals(settings: Settings, make_settings: Callable[..., Settings]) -> None:
    rig = Rig(settings)
    with pytest.raises(ReleaseRefusedError) as missing:
        rig.release.start(ACTOR, rehearsal=False, reason=None)
    assert missing.value.code == "no_snapshot"
    go_live(rig)
    rig.pump(Z1_Water_Target_Temp="34")
    rig.release.start(ACTOR, rehearsal=False, reason=None)
    with pytest.raises(ReleaseRefusedError) as busy:
        rig.release.start(ACTOR, rehearsal=False, reason=None)
    assert busy.value.code == "in_progress"
    runtime = Runtime(clock=FakeClock())
    shadow, _ = build_control(make_settings(control_mode="shadow"), runtime, None, sleep=no_sleep)
    assert shadow.release is not None
    with pytest.raises(ReleaseRefusedError) as off:
        shadow.release.start(ACTOR, rehearsal=False, reason=None)
    assert off.value.code == "not_publishing"


def test_a_release_that_does_not_settle_times_out_and_still_pauses(settings: Settings) -> None:
    rig = Rig(settings)
    go_live(rig)
    rig.pump(Z1_Water_Target_Temp="34")
    run = rig.release.start(ACTOR, rehearsal=True, reason=None)
    rig.clock.advance(rig.release.timeout_s + 1)
    rig.release.poll(rig.clock())
    assert run.done
    assert not run.ok
    water = next(item for item in run.items if item.kind is IntentKind.WATER_SETPOINT)
    assert water.status == "timeout"
    assert rig.loop.guard.hold.paused
    rig.step_adapter()
    assert rig.adapter.view().queued == {}
    assert rig.sent == []


def test_release_from_a_pause_restores_and_stays_paused(settings: Settings) -> None:
    rig = Rig(settings)
    go_live(rig)
    rig.loop.guard.hold.paused = True
    rig.pump(Z1_Water_Target_Temp="33")
    run = rig.release.start(ACTOR, rehearsal=False, reason=None)
    assert run.paused_before
    assert not rig.loop.guard.hold.paused
    command = rig.step_adapter()
    assert command is not None
    assert command.value == 30
    rig.clock.advance(5)
    rig.report("Z1_Water_Target_Temp", "30")
    rig.step_adapter()
    assert run.done
    assert rig.loop.guard.hold.paused


def test_release_api_needs_admin_and_reports_the_run(
    settings: Settings, make_settings: Callable[..., Settings]
) -> None:
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    manager = ConfigManager.open(settings, clock)
    loop, _ = build_control(
        settings, runtime, None, sleep=no_sleep, hold=manager.hold, facts=Facts(manager.store)
    )
    manager.attach(loop, loop.alarms)
    assert loop.release is not None
    loop.release.config = manager
    ingest = MqttIngest(settings, runtime)
    for message in pump_messages(BASE, Z1_Water_Target_Temp="30"):
        ingest.ingest(message)
    admin = {**basic("admin", ADMIN), **MARK}
    with TestClient(create_app(runtime, settings, control=loop, config=manager)) as client:
        empty = client.get("/api/v1/control/snapshot", headers=basic("admin", ADMIN))
        assert empty.json() == {
            "snapshot": None,
            "armed": False,
            "publishing": True,
            "can_capture": False,
            "capture_refusal": "controlling",
        }
        refused = client.post("/api/v1/control/release", json={}, headers=admin)
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "no_snapshot"
        loop.tick()
        snap = client.get("/api/v1/control/snapshot", headers=basic("admin", ADMIN)).json()
        assert snap["armed"] is True
        assert snap["snapshot"]["items"][0]["value"] == 30
        ingest.ingest(inbound(f"{BASE}/main/Z1_Water_Target_Temp", "34"))
        unmarked = client.post("/api/v1/control/release", json={}, headers=basic("admin", ADMIN))
        assert unmarked.status_code == 403
        bad = client.post("/api/v1/control/release", json={"rehearsal": "yes"}, headers=admin)
        assert bad.status_code == 400
        started = client.post(
            "/api/v1/control/release", json={"rehearsal": True, "reason": "drill"}, headers=admin
        )
        assert started.status_code == 202
        body = started.json()
        assert body["release"]["done"] is False
        assert body["control"]["releasing"] is True
        assert body["control"]["mode"] == "shadow"
        resume = client.post("/api/v1/control/resume", json={}, headers=admin)
        assert resume.status_code == 409
        status = client.get("/api/v1/control/release", headers=basic("admin", ADMIN)).json()
        assert status["release"]["outcome"] == "running"
        assert manager.store.runtime_get("paused") == "release control"
        clock.advance(loop.release.timeout_s + 1)
        done = client.get("/api/v1/control/release", headers=basic("admin", ADMIN)).json()
        assert done["release"]["outcome"] == "incomplete"
        assert done["last_rehearsal"]["rehearsal"] is True
        clock.advance(1)
        audit = client.get("/api/v1/audit", headers=basic("admin", ADMIN)).json()["events"]
        actions = [(event["action"], event["detail"].get("phase")) for event in audit]
        assert ("mode_pause", None) in actions
        assert ("control_release", "started") in actions
        assert ("control_release", "finished") in actions
    assert manager.hold.paused


def test_the_envelope_rule_is_recognised_when_it_corrects_the_pump(
    make_settings: Callable[..., Settings],
) -> None:
    facts = Facts()
    rig = Rig(make_settings(**PUBLISH, envelope_rule_installed=True), facts)
    watch = rig.loop.envelope
    assert watch is not None
    assert watch.status()["envelope_rule"]["state"] == "declared"
    safety = rig.loop.controller.config.safety
    bounds = safety.bounds(5.0)
    inside = min(safety.fallback_values(5.0))
    rig.pump(Outside_Temp="5", Z1_Water_Target_Temp=str(round(bounds.high) + 6))
    rig.loop.tick()
    rig.clock.advance(60)
    rig.report("Z1_Water_Target_Temp", str(inside))
    rig.loop.tick()
    evidence = watch.evidence()
    assert evidence["count"] == 1
    assert evidence["last"]["to_c"] == inside
    status = watch.status()
    assert status["envelope_rule"]["state"] == "proven"
    assert status["envelope_now"]["outside_c"] == 5.0
    assert facts.get("envelope_rule")["count"] == 1
    rig.clock.advance(60)
    rig.report("Z1_Water_Target_Temp", str(inside + 1))
    rig.loop.tick()
    assert watch.evidence()["count"] == 1


def test_a_change_no_rule_explains_is_not_evidence(make_settings: Callable[..., Settings]) -> None:
    rig = Rig(make_settings(**PUBLISH, envelope_rule_installed=True))
    watch = rig.loop.envelope
    assert watch is not None
    safety = rig.loop.controller.config.safety
    bounds = safety.bounds(5.0)
    rule = min(safety.fallback_values(5.0))
    other = next(v for v in range(round(bounds.low), round(bounds.high)) if abs(v - rule) > 1)
    rig.pump(Outside_Temp="5", Z1_Water_Target_Temp=str(round(bounds.high) + 6))
    rig.loop.tick()
    rig.clock.advance(60)
    rig.report("Z1_Water_Target_Temp", str(other))
    rig.loop.tick()
    assert watch.evidence()["count"] == 0
    assert watch.status()["envelope_rule"]["state"] == "declared"


def test_node_red_writing_the_rule_value_in_shadow_is_not_evidence(
    make_settings: Callable[..., Settings],
) -> None:
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    facts = Facts()
    settings = make_settings(
        control_mode="shadow", envelope_rule_installed=True, control_pump_duty=True
    )
    loop, _ = build_control(settings, runtime, None, sleep=no_sleep, facts=facts)
    ingest = MqttIngest(settings, runtime)
    watch = loop.envelope
    assert watch is not None
    safety = loop.controller.config.safety
    rule = min(safety.fallback_values(5.0))
    high = round(safety.bounds(5.0).high)
    for message in pump_messages(BASE, Outside_Temp="5", Z1_Water_Target_Temp=str(high + 6)):
        ingest.ingest(message)
    loop.tick()
    clock.advance(60)
    ingest.ingest(inbound(f"{BASE}/main/Z1_Water_Target_Temp", str(rule)))
    loop.tick()
    assert watch.evidence()["count"] == 0


def test_the_adapters_recognised_rule_correction_proves_the_rule_once(
    make_settings: Callable[..., Settings],
) -> None:
    rig = Rig(make_settings(**PUBLISH, envelope_rule_installed=True))
    watch = rig.loop.envelope
    assert watch is not None
    assert rig.adapter.config.envelope_rule is rig.loop.controller.config.safety
    assert watch.status()["envelope_rule"]["adopted"] == 0
    detail = {
        "ovenbird_value": 38,
        "seen_value": 29,
        "outside_c": 10.0,
        "low_c": 23.0,
        "high_c": 34.0,
    }
    event = AlarmEvent(
        rig.clock(),
        "envelope_correction",
        Severity.INFO,
        AlarmEventKind.RECOGNISED,
        "rule correction",
        detail,
    )
    rig.loop.alarms.record(event)
    rig.clock.advance(60)
    rig.loop.alarms.record(event)
    evidence = watch.evidence()
    assert evidence["count"] == 1
    assert evidence["last"]["from_c"] == 38.0
    assert evidence["last"]["to_c"] == 29.0
    assert watch.status()["envelope_rule"]["state"] == "proven"


def test_a_command_in_flight_at_release_is_waited_for_and_then_restored(
    settings: Settings,
) -> None:
    rig = Rig(settings)
    go_live(rig)
    command = rig.step_adapter()
    assert command is not None
    assert command.kind is IntentKind.WATER_SETPOINT
    assert command.value != 30
    run = rig.release.start(ACTOR, rehearsal=False, reason=None)
    water = next(item for item in run.items if item.kind is IntentKind.WATER_SETPOINT)
    assert water.status == "queued"
    assert water.waited_for == command.value
    assert water.target == 30
    assert not run.done
    rig.clock.advance(3)
    rig.report("Z1_Water_Target_Temp", str(command.value))
    assert rig.step_adapter() is None
    assert not run.done
    rig.clock.advance(rig.adapter.config.min_spacing_s)
    restore = rig.step_adapter()
    assert restore is not None
    assert restore.restore
    assert restore.value == 30
    rig.clock.advance(3)
    rig.report("Z1_Water_Target_Temp", "30")
    rig.step_adapter()
    assert run.done
    assert run.ok
    assert rig.loop.guard.hold.paused
    assert [c.value for c in rig.sent] == [command.value, 30]


def test_the_release_does_not_finish_while_a_command_is_in_flight(settings: Settings) -> None:
    rig = Rig(settings)
    go_live(rig)
    command = rig.step_adapter()
    assert command is not None
    run = rig.release.start(ACTOR, rehearsal=False, reason=None)
    assert not run.done
    assert rig.adapter.in_flight == command


def test_the_restore_is_clamped_to_the_envelope_band(settings: Settings) -> None:
    rig = Rig(settings)
    go_live(rig)
    safety = rig.loop.controller.config.safety
    band = safety.bounds(-12.0)
    rig.clock.advance(30)
    rig.pump(Z1_Water_Target_Temp="36", Outside_Temp="-12")
    run = rig.release.start(ACTOR, rehearsal=False, reason=None)
    water = next(item for item in run.items if item.kind is IntentKind.WATER_SETPOINT)
    assert water.snapshot == 30
    assert water.target == band.low_int
    assert water.clamped is not None
    assert "envelope band" in water.clamped
    assert run.outside_c == -12.0
    body = run.to_json()
    assert body["items"][0]["clamped"] == water.clamped
    assert body["snapshot_age_s"] == 30.0
    snapshot = rig.release.snapshot_payload()["snapshot"]
    assert snapshot["outside_c"] == 3.0
    assert snapshot["stale"] is False


def test_an_incomplete_release_keeps_the_snapshot_for_the_resume(settings: Settings) -> None:
    rig = Rig(settings)
    first = go_live(rig)
    rig.clock.advance(30)
    rig.pump(Z1_Water_Target_Temp="34")
    run = rig.release.start(ACTOR, rehearsal=True, reason=None)
    rig.clock.advance(rig.release.timeout_s + 1)
    rig.release.poll(rig.clock())
    assert run.done
    assert not run.ok
    assert rig.release.snapshot is first
    assert first.released_at is None
    assert rig.release.snapshot_payload()["armed"] is True
    rig.loop.guard.hold.paused = False
    rig.clock.advance(60)
    rig.pump(Z1_Water_Target_Temp="34")
    rig.loop.tick()
    assert rig.release.snapshot is first
    assert first.items["water_setpoint"] == 30
    again = rig.release.start(ACTOR, rehearsal=False, reason="finish")
    water = next(item for item in again.items if item.kind is IntentKind.WATER_SETPOINT)
    assert water.target == 30


def test_a_crash_in_the_middle_of_a_release_leaves_a_trace(settings: Settings) -> None:
    clock = FakeClock()
    manager = ConfigManager.open(settings, clock)
    runtime = Runtime(clock=clock)
    loop, _ = build_control(
        settings, runtime, None, sleep=no_sleep, hold=manager.hold, facts=Facts(manager.store)
    )
    manager.attach(loop, loop.alarms)
    assert loop.release is not None
    loop.release.config = manager
    ingest = MqttIngest(settings, runtime)
    for message in pump_messages(BASE, Z1_Water_Target_Temp="30", Max_Pump_Duty="159"):
        ingest.ingest(message)
    loop.tick()
    clock.advance(30)
    ingest.ingest(inbound(f"{BASE}/main/Z1_Water_Target_Temp", "34"))
    run = loop.release.start(ACTOR, rehearsal=True, reason=None)
    assert not run.done
    manager.close()
    clock.advance(20)
    after = ConfigManager.open(settings, clock)
    try:
        assert after.hold.paused
        runtime2 = Runtime(clock=clock)
        loop2, _ = build_control(
            settings, runtime2, None, sleep=no_sleep, hold=after.hold, facts=Facts(after.store)
        )
        assert loop2.release is not None
        last = loop2.release.last()
        assert last is not None
        assert last["outcome"] == "interrupted"
        assert last["done"] is True
        assert last["by"] == "admin"
        assert loop2.release.last_rehearsal() is not None
        alarm = loop2.alarms.get(AlarmCode.RELEASE_INTERRUPTED)
        assert alarm is not None
        assert alarm.detail["unfinished"] == ["water_setpoint"]
        assert loop2.release.snapshot is not None
        assert loop2.release.snapshot.armed
    finally:
        after.close()


class FailingConfig:
    def __init__(self, manager: ConfigManager) -> None:
        self.manager = manager

    def store_pause(self, actor: Actor, reason: str) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    def audit(self, *args: Any) -> None:
        self.manager.audit(*args)


def test_a_storage_error_leaves_no_release_stuck(settings: Settings) -> None:
    rig = Rig(settings)
    go_live(rig)
    rig.pump(Z1_Water_Target_Temp="34")
    clock = FakeClock()
    manager = ConfigManager.open(settings, clock)
    try:
        rig.release.config = FailingConfig(manager)  # type: ignore[assignment]
        with pytest.raises(ReleaseRefusedError) as refused:
            rig.release.start(ACTOR, rehearsal=False, reason=None)
        assert refused.value.status == 503
        assert refused.value.code == "storage_failed"
        hold = rig.loop.guard.hold
        assert not hold.releasing
        assert not hold.paused
        assert rig.release.run is None
        rig.release.config = None
        run = rig.release.start(ACTOR, rehearsal=False, reason=None)
        assert not run.done
    finally:
        manager.close()


def test_a_snapshot_can_be_captured_and_dry_rehearsed_in_shadow(
    make_settings: Callable[..., Settings],
) -> None:
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    facts = Facts()
    shadow, _ = build_control(
        make_settings(control_mode="shadow", control_pump_duty=True),
        runtime,
        None,
        sleep=no_sleep,
        facts=facts,
    )
    release = shadow.release
    assert release is not None
    assert release.snapshot_payload()["can_capture"] is True
    ingest = MqttIngest(make_settings(control_mode="shadow", control_pump_duty=True), runtime)
    for message in pump_messages(BASE, Z1_Water_Target_Temp="31", Max_Pump_Duty="159"):
        ingest.ingest(message)
    snapshot = release.capture(ACTOR)
    assert snapshot.origin == "manual"
    assert snapshot.items["water_setpoint"] == 31
    assert snapshot.to_json(clock().wall)["by"] == "admin"
    with pytest.raises(ReleaseRefusedError) as wet:
        release.start(ACTOR, rehearsal=True, reason=None)
    assert wet.value.code == "not_publishing"
    clock.advance(60)
    ingest.ingest(inbound(f"{BASE}/main/Z1_Water_Target_Temp", "35"))
    run = release.start(ACTOR, rehearsal=True, reason=None, dry=True)
    assert run.done
    assert run.dry
    items = {item.kind: item for item in run.items}
    assert items[IntentKind.WATER_SETPOINT].status == "planned"
    assert items[IntentKind.WATER_SETPOINT].target == 31
    assert items[IntentKind.MAX_PUMP_DUTY].status == "unchanged"
    assert run.ok
    assert release.last_dry_rehearsal() == run.to_json()
    assert release.last_rehearsal() is None
    assert not shadow.guard.hold.paused
    assert not shadow.guard.hold.releasing
    assert snapshot.armed


def test_capture_is_refused_while_ovenbird_controls_and_go_live_replaces_it(
    settings: Settings,
) -> None:
    rig = Rig(settings)
    rig.loop.guard.hold.paused = True
    rig.pump(Z1_Water_Target_Temp="29", Max_Pump_Duty="159", Quiet_Mode_Level="0")
    manual = rig.release.capture(ACTOR)
    assert manual.origin == "manual"
    rig.loop.guard.hold.paused = False
    rig.clock.advance(60)
    rig.pump(Z1_Water_Target_Temp="30")
    rig.loop.tick()
    live = rig.release.snapshot
    assert live is not None
    assert live is not manual
    assert live.origin == "go_live"
    assert live.items["water_setpoint"] == 30
    with pytest.raises(ReleaseRefusedError) as controlling:
        rig.release.capture(ACTOR)
    assert controlling.value.code == "controlling"
    rig.loop.guard.hold.paused = True
    with pytest.raises(ReleaseRefusedError) as in_use:
        rig.release.capture(ACTOR)
    assert in_use.value.code == "in_use"


def test_snapshot_and_dry_release_endpoints(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(control_mode="shadow", http_host="0.0.0.0", admin_password=ADMIN)
    clock = FakeClock()
    runtime = Runtime(clock=clock)
    manager = ConfigManager.open(settings, clock)
    loop, _ = build_control(
        settings, runtime, None, sleep=no_sleep, hold=manager.hold, facts=Facts(manager.store)
    )
    manager.attach(loop, loop.alarms)
    assert loop.release is not None
    loop.release.config = manager
    ingest = MqttIngest(settings, runtime)
    for message in pump_messages(BASE, Z1_Water_Target_Temp="31"):
        ingest.ingest(message)
    admin = {**basic("admin", ADMIN), **MARK}
    with TestClient(create_app(runtime, settings, control=loop, config=manager)) as client:
        captured = client.post("/api/v1/control/snapshot", json={}, headers=admin)
        assert captured.status_code == 200
        body = captured.json()
        assert body["snapshot"]["origin"] == "manual"
        assert body["armed"] is True
        assert body["snapshot"]["age_s"] == 0.0
        bad = client.post("/api/v1/control/release", json={"dry": "yes"}, headers=admin)
        assert bad.status_code == 400
        planned = client.post(
            "/api/v1/control/release", json={"rehearsal": True, "dry": True}, headers=admin
        )
        assert planned.status_code == 200
        assert planned.json()["release"]["dry"] is True
        assert planned.json()["release"]["outcome"] == "ok"
        status = client.get("/api/v1/control/release", headers=basic("admin", ADMIN)).json()
        assert status["last_dry_rehearsal"]["dry"] is True
        assert status["release"] is None
        clock.advance(1)
        audit = client.get("/api/v1/audit", headers=basic("admin", ADMIN)).json()["events"]
        actions = {event["action"] for event in audit}
        assert {"snapshot_capture", "control_release"} <= actions
    manager.close()
