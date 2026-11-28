from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from ovenbird.api.ws import Channel
from ovenbird.config import Settings
from ovenbird.configstore import Actor
from ovenbird.control.alarms import AlarmCode
from ovenbird.mqtt import MqttIngest
from ovenbird.service import Service, build_service
from ovenbird.testing import FakeClock, pump_messages
from ovenbird_core.control import IntentKind

PUBLISH: dict[str, Any] = {
    "control_mode": "auto",
    "allow_commands": True,
    "mqtt_host": "mosquitto",
    "command_brokers": ("mosquitto",),
}
ADMIN = Actor("admin from 127.0.0.1", "127.0.0.1")
RAISED_CURVE = [[-10.0, 39.0], [0.0, 36.0], [15.0, 25.0]]


class Rig:
    """A built service with a fake clock, MQTT ingest and helpers to tick and reconfigure."""

    def __init__(self, service: Service, clock: FakeClock) -> None:
        """Attach the fake clock to the service runtime and create the MQTT ingest."""
        self.service = service
        self.clock = clock
        self.service.runtime.clock = clock
        self.ingest = MqttIngest(service.settings, service.runtime)

    @property
    def config(self) -> Any:
        """Return the service's configuration manager."""
        assert self.service.config is not None
        return self.service.config

    def feed(self, **overrides: str) -> None:
        """Ingest one set of simulated pump MQTT messages, with optional topic payload overrides."""
        for message in pump_messages(**overrides):
            self.ingest.ingest(message)

    def tick(self, seconds: float = 60.0, **overrides: str) -> Any:
        """Advance the clock, feed the pump messages and run one control tick, returning its row."""
        self.clock.advance(seconds)
        self.feed(**overrides)
        return self.service.control.tick()

    def apply(self, **changes: Any) -> dict[str, Any]:
        """Apply config changes as admin, acknowledging every validation warning."""
        config = self.config
        warnings = [w.code for w in config.validate(changes).warnings]
        return dict(config.apply(config.version or 0, changes, ADMIN, acknowledge=warnings))


def rig(make_settings: Callable[..., Settings], **overrides: Any) -> Rig:
    """Build a publishing service from the settings with a fake clock on its config store."""
    clock = FakeClock()
    service = build_service(make_settings(**{**PUBLISH, **overrides}))
    service.config.clock = clock  # type: ignore[union-attr]
    return Rig(service, clock)


def test_apply_takes_effect_at_the_next_tick_through_deadband_and_dwell(
    make_settings: Callable[..., Settings],
) -> None:
    """A config change takes effect only at the next tick, through deadband and dwell."""
    run = rig(make_settings)
    first = run.tick()
    assert first.setpoint == 32
    assert first.config_version is None
    state_before = run.service.control.state
    run.clock.advance(61.0)
    result = run.apply(control_curve=RAISED_CURVE, control_dwell_s=900)
    assert result["version"] == 1
    assert run.service.control.reconfigure_pending
    assert run.service.control.config_version is None
    second = run.tick()
    record = json.loads(second.record)
    assert second.config_version == 1
    assert run.service.control.config_version == 1
    assert record["pre_round"] == pytest.approx(33.8)
    assert second.setpoint == 32
    assert record["binding"] == "dwell"
    assert run.service.control.state.last_change_at == state_before.last_change_at
    run.clock.advance(900.0)
    third = run.tick()
    assert third.setpoint == 34
    assert third.config_version == 1
    applied = run.config.store.get(1)
    assert applied is not None
    assert applied.applied_ts is not None


def test_lower_maximum_moves_adapter_clamp_and_monitor(
    make_settings: Callable[..., Settings],
) -> None:
    """A lower maximum supply moves the adapter clamp and the safety monitor at the next tick."""
    run = rig(make_settings)
    run.tick()
    adapter = run.service.control.adapter
    monitor = run.service.control.safety
    assert adapter is not None
    assert monitor is not None
    assert adapter.config.setpoint_range == (20, 40)
    run.clock.advance(61.0)
    run.apply(control_max_supply_c=31.0, control_min_setpoint_c=22.0)
    assert adapter.config.setpoint_range == (20, 40)
    row = run.tick()
    assert adapter.config.setpoint_range == (22, 31)
    assert monitor.config.max_supply_c == 31.0
    assert row.setpoint == 31
    assert json.loads(row.record)["binding"] == "safety_max"
    queued = adapter.status()["queued"]
    assert queued.get(IntentKind.WATER_SETPOINT.value) in {None, 31}


def test_defrost_low_flow_setting_reaches_the_monitor_at_the_next_tick(
    make_settings: Callable[..., Settings],
) -> None:
    """The defrost low-flow setting reaches the safety monitor at the next tick and is validated."""
    run = rig(make_settings)
    run.tick()
    monitor = run.service.control.safety
    assert monitor is not None
    initial = monitor.config
    assert initial.defrost_low_flow == "auto"
    run.clock.advance(61.0)
    run.apply(safety_defrost_low_flow="log")
    row = run.tick()
    assert row.config_version == 1
    assert monitor.config.defrost_low_flow == "log"
    with pytest.raises(ValueError, match="safety_defrost_low_flow"):
        make_settings(safety_defrost_low_flow="sometimes")


def test_a_new_configuration_is_announced_on_the_websocket(
    make_settings: Callable[..., Settings],
) -> None:
    """Applying a new configuration pushes a config message to websocket channels."""
    run = rig(make_settings)
    channel = Channel()
    app: Any = run.service.server.config.app
    broadcaster = app.state.broadcaster
    broadcaster.channels.add(channel)
    run.tick()
    run.clock.advance(61.0)
    run.apply(control_comfort_c=21.5)
    run.tick()
    message = json.loads(channel.pending["config"])
    assert message == {
        "type": "config",
        "data": {"version": 1, "applied_at": "2027-01-15T08:03:01Z"},
    }


def test_room_signal_change_resubscribes_home_assistant(
    make_settings: Callable[..., Settings],
) -> None:
    """Changing the room signal re-subscribes the Home Assistant component to the new entity."""
    run = rig(
        make_settings,
        ha_url="http://ha.local:8123",
        ha_token="token",
        ha_entities=("sensor.a_temperature",),
    )
    ha = next(c for c in run.service.components if c.name == "ha")
    hook = run.service.control.reconfigure_hooks
    assert len(hook) == 5
    run.tick()
    run.clock.advance(61.0)
    run.apply(control_room_signal="ha/sensor.b_temperature")
    run.tick()
    owner = ha.run.__self__  # type: ignore[attr-defined]
    assert owner.entities == ("sensor.a_temperature", "sensor.b_temperature")
    assert run.service.control.room_signal == "ha/sensor.b_temperature"


def test_retention_change_reaches_the_history_writer_at_the_next_tick(
    make_settings: Callable[..., Settings],
) -> None:
    """Retention changes reach the history writer at the next tick, with zero meaning forever."""
    run = rig(make_settings)
    writer = run.service.writer
    assert writer.retention.raw_days == 14.0
    assert writer.journal_days == 30.0
    run.tick()
    run.clock.advance(61.0)
    result = run.apply(history_raw_days=0, history_1h_days=730, history_decision_days=7)
    assert result["version"] == 1
    assert writer.retention.raw_days == 14.0
    run.tick()
    assert writer.retention.raw_days is None
    assert writer.retention.hour_days == 730.0
    assert writer.journal_days == 7.0


def test_retention_soft_range_warns_but_forever_does_not(
    make_settings: Callable[..., Settings],
) -> None:
    """A retention below the soft minimum warns, while zero (forever) does not."""
    run = rig(make_settings)
    warnings = run.config.validate({"history_raw_days": 0, "history_1m_days": 2}).warnings
    assert [(w.field, w.code) for w in warnings] == [("history_1m_days", "below_soft_min")]


def test_pause_stops_queueing_and_publishing_until_resume(
    make_settings: Callable[..., Settings],
) -> None:
    """Pausing sends the controller to shadow without commands, and resuming restores auto."""
    run = rig(make_settings, simulation=False)
    adapter = run.service.control.adapter
    assert adapter is not None
    run.config.pause(ADMIN, "checking")
    row = run.tick()
    assert row.mode == "shadow"
    assert row.commands == "[]"
    assert '"action":"send"' in row.arbiter
    status = run.service.control.status()
    assert status["publishing"] is False
    assert status["mode"] == "shadow"
    assert status["configured_mode"] == "auto"
    assert status["refusals"] == ["control is paused"]
    store = run.service.runtime.store
    now = run.clock()
    assert adapter.tick(now, lambda s: store.view(s, now), store.heishamon_status(now)) is None
    assert adapter.status()["queued"] == {}
    run.config.resume(ADMIN)
    resumed = run.tick()
    assert resumed.mode == "auto"
    assert '"status":"queued"' in resumed.commands


def test_lost_store_starts_in_shadow_until_acknowledged(
    make_settings: Callable[..., Settings],
) -> None:
    """A lost config store starts the controller in shadow with an alarm until acknowledged."""
    settings = make_settings(**PUBLISH)
    first = build_service(settings)
    assert first.config is not None
    first.config.apply(0, {"control_comfort_c": 21.5}, ADMIN)
    first.config.close()
    for name in ("config.db", "config.db-wal", "config.db-shm", "config.snapshot.db"):
        (settings.data_dir / name).unlink(missing_ok=True)
    service = build_service(settings)
    run = Rig(service, FakeClock())
    assert run.config.hold.reset_pending
    assert service.control.alarms.is_active(AlarmCode.CONFIG_RESET)
    assert service.settings.control_comfort_c == 21.0
    row = run.tick()
    assert row.mode == "shadow"
    assert row.commands == "[]"
    assert service.control.status()["reset_pending"] is True
    run.config.reset_ack(ADMIN)
    assert not service.control.alarms.is_active(AlarmCode.CONFIG_RESET)
    after = run.tick()
    assert after.mode == "auto"
    assert '"status":"queued"' in after.commands
