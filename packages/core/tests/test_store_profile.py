from __future__ import annotations

from datetime import timedelta

import pytest

from ovenbird_core import (
    Instant,
    MqttMessage,
    MqttSignal,
    SourceKind,
    StalenessPolicy,
    StateStore,
    ha_reading,
    ha_signal,
)
from ovenbird_core.control import RoomProfile, RoomSensorProfile, room_input
from ovenbird_core.store import HA_LINK_WINDOW_S

T0 = 1_794_528_000.0
ROOM = "sensor.living_room_temperature"
HUMIDITY = "sensor.living_room_humidity"
ROOM_ID = ha_signal(ROOM)
HUMIDITY_ID = ha_signal(HUMIDITY)
OWNER = RoomSensorProfile(kind=RoomProfile.ON_CHANGE, liveness=(HUMIDITY_ID,))
HOUR = 3600.0


def at(seconds: float) -> Instant:
    return Instant.from_unix(T0 + seconds)


def store_for(profile: RoomSensorProfile, signal: str = ROOM_ID) -> StateStore:
    return StateStore(profile.policy(StalenessPolicy(), signal))


def link(store: StateStore, seconds: float) -> None:
    store.set_link(SourceKind.HA, True, at(seconds))


class TestConfirmedBy:
    def test_liveness_signal_confirms_the_group(self) -> None:
        store = store_for(OWNER)
        link(store, 0)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        store.apply(ha_reading(HUMIDITY, "55", instant=at(3 * HOUR)))
        view = store.view(ROOM_ID, at(3 * HOUR + 60))
        assert view is not None
        assert view.age == pytest.approx(60.0)
        assert view.held == pytest.approx(3 * HOUR + 60)
        assert view.alive_by == HUMIDITY_ID
        assert store.age(ROOM_ID, at(3 * HOUR + 60)) == pytest.approx(60.0)

    def test_own_report_newer_than_liveness(self) -> None:
        store = store_for(OWNER)
        store.apply(ha_reading(HUMIDITY, "55", instant=at(0)))
        store.apply(ha_reading(ROOM, "21.7", instant=at(100)))
        view = store.view(ROOM_ID, at(160))
        assert view is not None
        assert view.age == pytest.approx(60.0)
        assert view.alive_by is None

    def test_invalid_liveness_confirms_nothing(self) -> None:
        store = store_for(OWNER)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        store.apply(ha_reading(HUMIDITY, "55", instant=at(100)))
        store.apply(ha_reading(HUMIDITY, "unavailable", instant=at(200)))
        view = store.view(ROOM_ID, at(300))
        assert view is not None
        assert view.age == pytest.approx(300.0)
        assert view.alive_by is None

    def test_policy_of_the_profiles(self) -> None:
        periodic = RoomSensorProfile(report_interval_s=3600.0).policy(StalenessPolicy(), ROOM_ID)
        assert periodic.max_age(ROOM_ID, SourceKind.HA) == 3 * HOUR
        assert periodic.max_age(ROOM_ID, SourceKind.HA, link_up=False) == 3 * HOUR
        default = RoomSensorProfile().policy(StalenessPolicy(), ROOM_ID)
        assert default.max_age(ROOM_ID, SourceKind.HA) == 1800.0
        held = OWNER.policy(StalenessPolicy(), ROOM_ID)
        assert held.max_age(ROOM_ID, SourceKind.HA) == 24 * HOUR
        assert held.max_age(ROOM_ID, SourceKind.HA, link_up=False) == 1800.0
        assert held.confirmed_by[ROOM_ID] == (HUMIDITY_ID,)


class TestHeldAndAlive:
    def test_held_since_the_last_change_alive_since_any_report(self) -> None:
        store = store_for(OWNER)
        link(store, 0)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        store.apply(ha_reading(ROOM, "21.7", instant=at(HOUR)))
        store.apply(ha_reading(ROOM, "21.9", instant=at(2 * HOUR)))
        store.apply(ha_reading(ROOM, "21.9", instant=at(5 * HOUR)))
        link(store, 5 * HOUR)
        view = store.view(ROOM_ID, at(5 * HOUR + 120))
        assert view is not None
        assert view.held == pytest.approx(3 * HOUR + 120)
        assert view.age == pytest.approx(120.0)
        assert view.fresh

    def test_held_seeded_from_last_changed_after_a_restart(self) -> None:
        store = store_for(OWNER)
        link(store, 0)
        now = at(0)
        changed = now.wall - timedelta(hours=7)
        reported = now.wall - timedelta(minutes=20)
        store.apply(
            ha_reading(
                ROOM,
                "22.1",
                instant=now,
                last_reported=reported,
                last_updated=reported,
                last_changed=changed,
            )
        )
        view = store.view(ROOM_ID, now)
        assert view is not None
        assert view.held == pytest.approx(7 * HOUR)
        assert view.age == pytest.approx(1200.0)

    def test_room_input_carries_the_profile(self) -> None:
        store = store_for(OWNER)
        link(store, 0)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        store.apply(ha_reading(HUMIDITY, "55", instant=at(HOUR)))
        room = room_input(store.snapshot(at(HOUR + 30)), ROOM_ID, OWNER)
        assert room is not None
        assert room.quantum_k == 0.2
        assert room.profile is RoomProfile.ON_CHANGE
        assert room.held_s == pytest.approx(HOUR + 30)
        assert room.alive_s == pytest.approx(30.0)
        assert room.alive_by == HUMIDITY_ID
        assert room.fresh

    def test_silent_after_the_silence_limit(self) -> None:
        store = store_for(OWNER)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        link(store, 24 * HOUR)
        assert store.is_fresh(ROOM_ID, at(24 * HOUR))
        link(store, 24 * HOUR + 1)
        assert not store.is_fresh(ROOM_ID, at(24 * HOUR + 1))


class TestLinkConditionalHold:
    def test_hold_needs_a_confirmed_link(self) -> None:
        store = store_for(OWNER)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        assert not store.is_fresh(ROOM_ID, at(2 * HOUR))
        store.set_link(SourceKind.HA, True)
        assert not store.link_up(SourceKind.HA, at(2 * HOUR))
        assert not store.is_fresh(ROOM_ID, at(2 * HOUR))
        link(store, 2 * HOUR)
        assert store.is_fresh(ROOM_ID, at(2 * HOUR))
        view = store.view(ROOM_ID, at(2 * HOUR))
        assert view is not None
        assert view.max_age == 24 * HOUR

    def test_failed_rereads_end_the_hold(self) -> None:
        store = store_for(OWNER)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        link(store, HOUR)
        assert store.is_fresh(ROOM_ID, at(HOUR + HA_LINK_WINDOW_S))
        assert not store.is_fresh(ROOM_ID, at(HOUR + HA_LINK_WINDOW_S + 1))
        assert store.snapshot(at(HOUR + HA_LINK_WINDOW_S + 1)).links == {SourceKind.HA: False}

    def test_disconnect_falls_back_to_the_default_limit(self) -> None:
        store = store_for(OWNER)
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        link(store, 1000)
        store.set_link(SourceKind.HA, False)
        assert store.is_fresh(ROOM_ID, at(1700))
        assert not store.is_fresh(ROOM_ID, at(1900))
        store.set_link(SourceKind.HA, True)
        assert not store.is_fresh(ROOM_ID, at(1900))
        assert store.max_age(ROOM_ID, at(1900)) == 1800.0
        assert store.max_age(ROOM_ID) == 24 * HOUR

    def test_mqtt_link_needs_only_the_connection(self) -> None:
        spec = MqttSignal("room_temperature", "°C")
        policy = OWNER.policy(StalenessPolicy(), "room_temperature")
        store = StateStore(policy)
        store.apply(spec.parse(MqttMessage("room/t", b"21.7", False, at(0))))
        store.set_link(SourceKind.MQTT, True)
        assert store.is_fresh("room_temperature", at(10 * HOUR))
        store.set_link(SourceKind.MQTT, False)
        assert not store.is_fresh("room_temperature", at(10 * HOUR))

    def test_periodic_ignores_the_link(self) -> None:
        store = store_for(RoomSensorProfile())
        store.apply(ha_reading(ROOM, "21.7", instant=at(0)))
        assert store.is_fresh(ROOM_ID, at(1800))
        assert not store.is_fresh(ROOM_ID, at(1801))


class TestRetainedSeeding:
    PROFILE = RoomSensorProfile(kind=RoomProfile.ON_CHANGE, liveness=("room_humidity",))

    def setup(self) -> tuple[StateStore, MqttSignal, MqttSignal]:
        store = StateStore(self.PROFILE.policy(StalenessPolicy(), "room_temperature"))
        store.set_link(SourceKind.MQTT, True)
        return store, MqttSignal("room_temperature", "°C"), MqttSignal("room_humidity", "%")

    def test_retained_value_seeds_but_is_not_alive(self) -> None:
        store, temp, _ = self.setup()
        store.apply(temp.parse(MqttMessage("room/t", b"21.9", True, at(0))))
        view = store.view("room_temperature", at(10))
        assert view is not None
        assert view.value == 21.9
        assert view.age is None
        assert view.held is None
        assert not view.fresh

    def test_live_liveness_makes_the_seeded_value_alive(self) -> None:
        store, temp, humidity = self.setup()
        store.apply(temp.parse(MqttMessage("room/t", b"21.9", True, at(0))))
        store.apply(humidity.parse(MqttMessage("room/h", b"54", False, at(600))))
        view = store.view("room_temperature", at(660))
        assert view is not None
        assert view.fresh
        assert view.value == 21.9
        assert view.age == pytest.approx(60.0)
        assert view.alive_by == "room_humidity"
        assert view.held is None

    def test_retained_liveness_proves_nothing(self) -> None:
        store, temp, humidity = self.setup()
        store.apply(temp.parse(MqttMessage("room/t", b"21.9", True, at(0))))
        store.apply(humidity.parse(MqttMessage("room/h", b"54", True, at(1))))
        assert not store.is_fresh("room_temperature", at(10))

    def test_live_value_after_the_seed(self) -> None:
        store, temp, _ = self.setup()
        store.apply(temp.parse(MqttMessage("room/t", b"21.9", True, at(0))))
        store.apply(temp.parse(MqttMessage("room/t", b"22.1", False, at(300))))
        view = store.view("room_temperature", at(400))
        assert view is not None
        assert view.fresh
        assert view.held == pytest.approx(100.0)
