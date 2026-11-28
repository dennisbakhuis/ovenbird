"""The room sensor profile: settings, Home Assistant and MQTT link handling, alarms and status."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import SecretStr

from ovenbird.config import ConfigError, Settings, load_settings
from ovenbird.control import AlarmBoard, AlarmCode, ControlLoop, PublishGuard, controller_config
from ovenbird.control.monitors import MonitorConfig, MonitorStatus, evaluate, monitor_config
from ovenbird.control.persist import decode_state, encode_state
from ovenbird.ha import HaInput
from ovenbird.mqtt import MqttIngest
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock, FakeMqttClient, inbound, pump_messages
from ovenbird_core import Instant, SourceKind, StateStore, ha_reading
from ovenbird_core.control import Mode, OvenbirdController, OvenbirdState, RoomProfile

ROOM = "sensor.living_room_temperature"
HUMIDITY = "sensor.living_room_humidity"
ROOM_ID = f"ha/{ROOM}"
HUMIDITY_ID = f"ha/{HUMIDITY}"
HA = {"ha_url": "http://ha.local:8123", "ha_token": "token", "ha_entities": (ROOM,)}
OWNER = {
    **HA,
    "control_room_signal": ROOM_ID,
    "control_room_profile": "on_change",
    "control_room_liveness_signals": (HUMIDITY_ID,),
}
MQTT_ROOM = [
    {"topic": "sim/room", "signal": "room_temperature", "unit": "°C"},
    {"topic": "sim/humidity", "signal": "room_humidity", "unit": "%"},
]
HOUR = 3600.0


def iso(t: float) -> str:
    """Format an epoch timestamp as an ISO 8601 UTC string."""
    return datetime.fromtimestamp(t, UTC).isoformat()


class TestSettings:
    """Room profile and liveness settings: defaults, owner profile, environment and validation."""

    def test_defaults_keep_todays_behaviour(self, make_settings: Callable[..., Settings]) -> None:
        """Without a profile the room sensor stays periodic with default limits."""
        settings = make_settings(control_room_signal=ROOM_ID, **HA)
        profile = settings.room_profile()
        assert profile.kind is RoomProfile.PERIODIC
        assert profile.report_interval_s == 300.0
        assert profile.max_age_s == 1800.0
        assert profile.quantum_k == 0.1
        policy = settings.staleness_policy()
        assert policy.max_age(ROOM_ID, SourceKind.HA) == 1800.0
        assert policy.max_age(ROOM_ID, SourceKind.HA, link_up=False) == 1800.0
        assert policy.held == frozenset()

    def test_owner_profile(self, make_settings: Callable[..., Settings]) -> None:
        """The on-change profile allows a day-old value while the link is up."""
        settings = make_settings(**OWNER)
        policy = settings.staleness_policy()
        assert policy.max_age(ROOM_ID, SourceKind.HA) == 86_400.0
        assert policy.max_age(ROOM_ID, SourceKind.HA, link_up=False) == 1800.0
        assert policy.confirmed_by[ROOM_ID] == (HUMIDITY_ID,)
        assert settings.ha_subscriptions == (ROOM, HUMIDITY)
        assert controller_config(settings).room == settings.room_profile()
        assert settings.room_profile().quantum_k == 0.2

    def test_environment(
        self, make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Room profile settings can be given through environment variables."""
        monkeypatch.setenv("OVENBIRD_CONTROL_ROOM_PROFILE", "on_change")
        monkeypatch.setenv("OVENBIRD_CONTROL_ROOM_STEP_K", "0.25")
        monkeypatch.setenv("OVENBIRD_CONTROL_ROOM_SILENCE_LIMIT_S", "43200")
        monkeypatch.setenv(
            "OVENBIRD_CONTROL_ROOM_LIVENESS_SIGNALS", f"{HUMIDITY_ID}, ha/sensor.x_lqi"
        )
        monkeypatch.setenv("OVENBIRD_CONTROL_ROOM_CROSSCHECK_SIGNAL", "main/Room_Thermostat_Temp")
        settings = make_settings(control_room_signal=ROOM_ID, **HA)
        profile = settings.room_profile()
        assert profile.kind is RoomProfile.ON_CHANGE
        assert profile.quantum_k == 0.25
        assert profile.silence_limit_s == 43_200.0
        assert profile.liveness == (HUMIDITY_ID, "ha/sensor.x_lqi")
        assert profile.crosscheck == "main/Room_Thermostat_Temp"
        assert settings.ha_subscriptions == (ROOM, HUMIDITY, "sensor.x_lqi")

    def test_room_and_liveness_alone_satisfy_the_entity_list(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Room and liveness entities suffice as subscriptions without an entity list."""
        settings = make_settings(**{**OWNER, "ha_entities": ()})
        assert settings.ha_subscriptions == (ROOM, HUMIDITY)

    def test_mqtt_liveness(self, make_settings: Callable[..., Settings]) -> None:
        """MQTT liveness signals work without any Home Assistant subscription."""
        settings = make_settings(
            mqtt_inputs=MQTT_ROOM,
            control_room_signal="room_temperature",
            control_room_profile="on_change",
            control_room_liveness_signals="room_humidity",
        )
        assert settings.room_profile().liveness == ("room_humidity",)
        assert settings.ha_subscriptions == ()

    @pytest.mark.parametrize(
        ("overrides", "fragment"),
        [
            ({"control_room_profile": "sometimes"}, "control_room_profile"),
            ({"control_room_step_k": 0.0}, "control_room_step_k"),
            ({"control_room_step_k": 3.0}, "control_room_step_k"),
            ({"control_room_silence_limit_s": 600.0}, "control_room_silence_limit_s"),
            ({"control_room_report_interval_s": 1.0}, "control_room_report_interval_s"),
            ({"control_room_liveness_signals": (ROOM_ID,)}, "must not list the room signal"),
            ({"control_room_liveness_signals": ("room_humidity",)}, "liveness signal"),
            ({"control_room_liveness_signals": ("ha/Not An Entity",)}, "liveness signal"),
            ({"control_room_crosscheck_signal": "main/Nope"}, "crosscheck signal"),
            ({"control_room_crosscheck_signal": ROOM_ID}, "must differ"),
            ({"control_room_signal": "room_temperature"}, "room signal"),
            ({"control_room_signal": "ha/Not An Entity"}, "room signal"),
        ],
    )
    def test_rejected(
        self, make_settings: Callable[..., Settings], overrides: dict[str, Any], fragment: str
    ) -> None:
        """Invalid room profile settings are rejected with an error naming the problem."""
        with pytest.raises(ConfigError, match=fragment):
            make_settings(**{**OWNER, **overrides})

    def test_liveness_needs_a_room_signal(self, make_settings: Callable[..., Settings]) -> None:
        """Liveness signals without a room signal are rejected."""
        with pytest.raises(ConfigError, match="need control_room_signal"):
            make_settings(**HA, control_room_liveness_signals=(HUMIDITY_ID,))

    def test_ha_room_signal_needs_ha(self, make_settings: Callable[..., Settings]) -> None:
        """A Home Assistant room signal without Home Assistant is rejected."""
        with pytest.raises(ConfigError, match="room signal"):
            make_settings(mqtt_inputs=MQTT_ROOM, control_room_signal=ROOM_ID)

    def test_ha_liveness_needs_ha(self, make_settings: Callable[..., Settings]) -> None:
        """A Home Assistant liveness signal without Home Assistant is rejected."""
        with pytest.raises(ConfigError, match="liveness signal"):
            make_settings(
                mqtt_inputs=MQTT_ROOM,
                control_room_signal="room_temperature",
                control_room_liveness_signals=(HUMIDITY_ID,),
            )

    def test_empty_values_are_unset(self) -> None:
        """Blank crosscheck and liveness settings count as unset."""
        settings = load_settings(
            control_room_crosscheck_signal=" ", control_room_liveness_signals=""
        )
        assert settings.control_room_crosscheck_signal is None
        assert settings.control_room_liveness_signals == ()


def owner_runtime(settings: Settings, clock: FakeClock) -> Runtime:
    """Build a runtime with Home Assistant enabled and the staleness policy of ``settings``."""
    return Runtime(StateStore(settings.staleness_policy()), clock=clock, ha_enabled=True)


def full_state(entity: str, state: str, reported: float, changed: float) -> dict[str, Any]:
    """Build a Home Assistant state dict with separate reported and changed times."""
    return {
        "entity_id": entity,
        "state": state,
        "attributes": {},
        "last_changed": iso(changed),
        "last_updated": iso(changed),
        "last_reported": iso(reported),
    }


class TestHaLinkConditionalHold:
    """Holding the room value while the Home Assistant link is up."""

    def reread(self, client: HaInput, states: list[Any], success: bool = True) -> None:
        """Deliver the result of a full state re-read to the client."""
        message_id = client._next_id
        client._next_id += 1
        client._pending_reads.add(message_id)
        client.handle({"id": message_id, "type": "result", "success": success, "result": states})

    def test_hold_follows_the_link(self, make_settings: Callable[..., Settings]) -> None:
        """A held room value stays fresh while liveness and link hold, and stale otherwise."""
        settings = make_settings(**OWNER)
        clock = FakeClock()
        runtime = owner_runtime(settings, clock)
        client = HaInput(settings.ha_url or "", SecretStr("t"), settings.ha_subscriptions, runtime)
        now = clock().wall.timestamp()
        states = [
            full_state(ROOM, "22.1", reported=now - 2 * HOUR, changed=now - 5 * HOUR),
            full_state(HUMIDITY, "54", reported=now - 1200, changed=now - 1200),
        ]
        runtime.set_link(SourceKind.HA, up=True)
        self.reread(client, states)
        view = runtime.store.view(ROOM_ID, clock())
        assert view is not None
        assert view.fresh
        assert view.held == pytest.approx(5 * HOUR)
        assert view.age == pytest.approx(1200.0)
        assert view.alive_by == HUMIDITY_ID
        clock.advance(901.0)
        assert not runtime.store.is_fresh(ROOM_ID, clock())
        self.reread(client, [], success=False)
        assert not runtime.store.is_fresh(ROOM_ID, clock())
        self.reread(client, [])
        assert runtime.store.is_fresh(ROOM_ID, clock())
        runtime.set_link(SourceKind.HA, up=False)
        assert not runtime.store.is_fresh(ROOM_ID, clock())
        assert runtime.snapshot()["links"] == {"ha": False}

    async def test_session_end_drops_the_link(self, make_settings: Callable[..., Settings]) -> None:
        """Ending a Home Assistant session marks its link down."""
        settings = make_settings(**OWNER)
        runtime = owner_runtime(settings, FakeClock())
        runtime.set_link(SourceKind.HA, up=True, confirmed=True)
        client = HaInput("http://127.0.0.1:9", SecretStr("t"), (ROOM,), runtime)
        await asyncio.wait_for(client.session(), 5)
        assert runtime.store.snapshot(runtime.clock()).links == {SourceKind.HA: False}


class TestMqttLinkAndRetained:
    """Retained MQTT values and the MQTT link."""

    async def test_retained_seed_alive_after_live_liveness(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """A retained room value turns fresh once a live liveness signal arrives."""
        settings = make_settings(
            mqtt_inputs=MQTT_ROOM,
            control_room_signal="room_temperature",
            control_room_profile="on_change",
            control_room_liveness_signals="room_humidity",
        )
        clock = FakeClock()
        runtime = Runtime(StateStore(settings.staleness_policy()), clock=clock)
        messages = [
            inbound("sim/room", "21.9", retained=True),
            inbound("sim/humidity", "55", retained=True),
        ]
        fake = FakeMqttClient(messages)
        ingest = MqttIngest(settings, runtime, connect=lambda: fake)
        task = asyncio.create_task(ingest.session())
        await asyncio.wait_for(fake.delivered.wait(), 2)
        assert runtime.store.link_up(SourceKind.MQTT, clock())
        view = runtime.store.view("room_temperature", clock())
        assert view is not None
        assert view.value == 21.9
        assert not view.fresh
        clock.advance(600.0)
        ingest.ingest(inbound("sim/humidity", "56"))
        clock.advance(3 * HOUR)
        view = runtime.store.view("room_temperature", clock())
        assert view is not None
        assert view.fresh
        assert view.alive_by == "room_humidity"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not runtime.store.link_up(SourceKind.MQTT, clock())
        assert not runtime.store.is_fresh("room_temperature", clock())


def monitor(settings: Settings) -> MonitorConfig:
    """Return the monitor configuration for ``settings`` at a 40 °C water limit."""
    return monitor_config(settings, 40.0)


class TestAlarms:
    """Room sensor and Home Assistant link alarms."""

    def test_room_sensor_silent(self, make_settings: Callable[..., Settings]) -> None:
        """The silent-sensor alarm follows the silence limit and clears on a liveness report."""
        settings = make_settings(**{**OWNER, "control_room_silence_limit_s": 7200.0})
        clock = FakeClock()
        runtime = owner_runtime(settings, clock)
        runtime.set_link(SourceKind.HA, up=True, confirmed=True)
        runtime.apply(ha_reading(ROOM, "21.7", instant=clock()))
        config = monitor(settings)
        _, findings = evaluate(config, runtime.store.snapshot(clock()), {})
        by_code = {f.code: f for f in findings}
        assert by_code[AlarmCode.ROOM_SENSOR_SILENT].status is MonitorStatus.OK
        assert AlarmCode.ROOM_REPORT_OVERDUE not in by_code
        clock.advance(7201.0)
        _, findings = evaluate(config, runtime.store.snapshot(clock()), {})
        silent = {f.code: f for f in findings}[AlarmCode.ROOM_SENSOR_SILENT]
        assert silent.status is MonitorStatus.ACTIVE
        assert "no report from the room sensor or its liveness signals" in silent.message
        runtime.apply(ha_reading(HUMIDITY, "54", instant=clock()))
        _, findings = evaluate(config, runtime.store.snapshot(clock()), {})
        assert {f.code: f for f in findings}[AlarmCode.ROOM_SENSOR_SILENT].status is (
            MonitorStatus.OK
        )

    def test_periodic_report_overdue(self, make_settings: Callable[..., Settings]) -> None:
        """A periodic sensor raises the overdue alarm once its report is late."""
        settings = make_settings(control_room_signal=ROOM_ID, **HA)
        clock = FakeClock()
        runtime = owner_runtime(settings, clock)
        runtime.apply(ha_reading(ROOM, "21.7", instant=clock()))
        config = monitor(settings)
        clock.advance(899.0)
        _, findings = evaluate(config, runtime.store.snapshot(clock()), {})
        assert {f.code: f for f in findings}[AlarmCode.ROOM_REPORT_OVERDUE].status is (
            MonitorStatus.OK
        )
        clock.advance(2.0)
        _, findings = evaluate(config, runtime.store.snapshot(clock()), {})
        overdue = {f.code: f for f in findings}[AlarmCode.ROOM_REPORT_OVERDUE]
        assert overdue.status is MonitorStatus.ACTIVE
        assert "OVENBIRD_CONTROL_ROOM_PROFILE=on_change" in overdue.message

    def test_ha_link_down(self, make_settings: Callable[..., Settings]) -> None:
        """The Home Assistant link alarm is pending, then active after its delay, then clears."""
        settings = make_settings(**OWNER)
        clock = FakeClock()
        runtime = owner_runtime(settings, clock)
        config = monitor(settings)
        since, findings = evaluate(config, runtime.store.snapshot(clock()), {})
        assert {f.code: f for f in findings}[AlarmCode.HA_LINK_DOWN].status is (
            MonitorStatus.PENDING
        )
        clock.advance(301.0)
        since, findings = evaluate(config, runtime.store.snapshot(clock()), since)
        assert {f.code: f for f in findings}[AlarmCode.HA_LINK_DOWN].status is (
            MonitorStatus.ACTIVE
        )
        runtime.set_link(SourceKind.HA, up=True, confirmed=True)
        since, findings = evaluate(config, runtime.store.snapshot(clock()), since)
        assert {f.code: f for f in findings}[AlarmCode.HA_LINK_DOWN].status is MonitorStatus.OK
        assert AlarmCode.HA_LINK_DOWN not in since

    def test_no_ha_no_link_monitor(self, make_settings: Callable[..., Settings]) -> None:
        """Without Home Assistant there is no link or room sensor alarm."""
        _, findings = evaluate(monitor(make_settings()), StateStore().snapshot(FakeClock()()), {})
        codes = {f.code for f in findings}
        assert AlarmCode.HA_LINK_DOWN not in codes
        assert AlarmCode.ROOM_SENSOR_SILENT not in codes


class TestControlLoop:
    """The control loop's room status and sensor alarms."""

    def make(self, settings: Settings, clock: FakeClock) -> tuple[ControlLoop, Runtime]:
        """Build a shadow-mode control loop and its runtime for ``settings``."""
        runtime = Runtime(StateStore(settings.staleness_policy()), clock=clock)
        loop = ControlLoop(
            runtime,
            OvenbirdController(controller_config(settings)),
            mode=Mode.SHADOW,
            guard=PublishGuard.from_settings(settings),
            alarms=AlarmBoard(),
            room_signal=settings.control_room_signal,
        )
        return loop, runtime

    def feed(self, runtime: Runtime, room: str, thermostat: str) -> None:
        """Ingest the pump thermostat reading and the room reading."""
        ingest = MqttIngest(load_settings(mqtt_inputs=MQTT_ROOM), runtime)
        for message in pump_messages(Room_Thermostat_Temp=thermostat):
            ingest.ingest(message)
        ingest.ingest(inbound("sim/room", room))

    def test_room_implausible_alarm_and_status(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """A room reading far from the thermostat raises the implausible alarm until they agree."""
        settings = make_settings(
            mqtt_inputs=MQTT_ROOM,
            control_room_signal="room_temperature",
            control_room_profile="on_change",
            control_room_liveness_signals="room_humidity",
            control_room_crosscheck_signal="main/Room_Thermostat_Temp",
        )
        clock = FakeClock()
        loop, runtime = self.make(settings, clock)
        runtime.set_link(SourceKind.MQTT, up=True, confirmed=True)
        self.feed(runtime, "21.7", "23")
        loop.tick()
        status = loop.status()["room"]
        assert status["profile"] == "on_change"
        assert status["step_k"] == 0.2
        assert status["fresh"] is True
        assert status["link_up"] is True
        assert status["plausible"] is True
        assert status["max_age_s"] == 86_400.0
        for _ in range(26):
            clock.advance(300.0)
            self.feed(runtime, "21.7", "20")
            loop.tick()
        assert loop.alarms.is_active(AlarmCode.ROOM_IMPLAUSIBLE)
        assert loop.status()["room"]["plausible"] is False
        clock.advance(300.0)
        self.feed(runtime, "21.7", "23")
        loop.tick()
        assert loop.alarms.is_active(AlarmCode.ROOM_IMPLAUSIBLE)
        clock.advance(300.0)
        self.feed(runtime, "21.9", "23")
        loop.tick()
        assert not loop.alarms.is_active(AlarmCode.ROOM_IMPLAUSIBLE)

    def test_room_sensor_quiet_warns_after_eight_hours_without_proof_of_life(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """Eight hours without proof of life raise the quiet alarm, cleared by a liveness report."""
        settings = make_settings(
            mqtt_inputs=MQTT_ROOM,
            control_room_signal="room_temperature",
            control_room_profile="on_change",
            control_room_liveness_signals="room_humidity",
        )
        clock = FakeClock()
        loop, runtime = self.make(settings, clock)
        runtime.set_link(SourceKind.MQTT, up=True, confirmed=True)
        ingest = MqttIngest(load_settings(mqtt_inputs=MQTT_ROOM), runtime)
        ingest.ingest(inbound("sim/room", "23.3"))
        for _ in range(int(8 * HOUR / 600.0)):
            clock.advance(600.0)
            for message in pump_messages():
                ingest.ingest(message)
            loop.tick()
        assert not loop.alarms.is_active(AlarmCode.ROOM_SENSOR_QUIET)
        clock.advance(600.0)
        for message in pump_messages():
            ingest.ingest(message)
        loop.tick()
        assert loop.alarms.is_active(AlarmCode.ROOM_SENSOR_QUIET)
        (alarm,) = [a for a in loop.alarms.active() if a.code is AlarmCode.ROOM_SENSOR_QUIET]
        assert "cooling authority is gone" in alarm.message
        clock.advance(60.0)
        ingest.ingest(inbound("sim/humidity", "55"))
        loop.tick()
        assert not loop.alarms.is_active(AlarmCode.ROOM_SENSOR_QUIET)

    def test_no_quiet_warning_for_a_periodic_sensor(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        """A periodic sensor never raises the quiet alarm."""
        settings = make_settings(mqtt_inputs=MQTT_ROOM, control_room_signal="room_temperature")
        clock = FakeClock()
        loop, runtime = self.make(settings, clock)
        ingest = MqttIngest(load_settings(mqtt_inputs=MQTT_ROOM), runtime)
        ingest.ingest(inbound("sim/room", "21.5"))
        clock.advance(9 * HOUR)
        loop.tick()
        assert not loop.alarms.is_active(AlarmCode.ROOM_SENSOR_QUIET)

    def test_status_without_room(self, make_settings: Callable[..., Settings]) -> None:
        """Without a room signal the status has no room entry."""
        loop, _ = self.make(make_settings(), FakeClock())
        assert loop.status()["room"] is None


def test_crosscheck_time_survives_a_restart() -> None:
    """The crosscheck offset and start time survive saving and restoring the state."""
    now = Instant.from_unix(1_800_000_000.0)
    state = OvenbirdState(crosscheck_offset_k=1.2, crosscheck_since=now.monotonic - 600.0)
    later = now.shifted(60.0)
    restored, _ = decode_state(encode_state(state, now), later, 900.0)
    assert restored is not None
    assert restored.crosscheck_offset_k == 1.2
    assert restored.crosscheck_since == pytest.approx(later.monotonic - 660.0)
