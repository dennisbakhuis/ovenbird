"""The broker connection set in the app: validation, test, apply, watch and revert."""

from __future__ import annotations

import asyncio
import secrets
import socket
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import aiomqtt
import pytest

from ovenbird.backoff import Backoff
from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.configstore.apply import Actor, ConfigRefusedError
from ovenbird.configstore.effective import Source
from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.mqtt import MqttIngest
from ovenbird.mqttcheck import mqtt_check
from ovenbird.mqttsetup import TRIAL_KEY, MqttSetup, changes_from
from ovenbird.runtime import Runtime
from ovenbird.testing import FakeClock, FakeMqttClient, inbound, pump_messages, turns
from ovenbird.testing import until as settle
from ovenbird_core import StateStore

ADMIN = Actor("admin", "192.0.2.5")


async def no_sleep(_: float) -> None:
    """Yield to the event loop instead of sleeping."""
    await asyncio.sleep(0)


class Rig:
    """Config manager, MQTT ingest and setup wired together with fake broker and check."""

    def __init__(
        self,
        settings: Settings,
        *,
        locked: dict[str, Source] | None = None,
        commands: bool = False,
        check_ok: bool = True,
        live: bool = True,
        stored: dict[str, Any] | None = None,
        clock: FakeClock | None = None,
    ) -> None:
        """Build the rig from settings with optional locked fields, stored connection and fakes."""
        self.clock = clock or FakeClock(1_800_000_000.0)
        self.manager = ConfigManager.open(settings, self.clock, locked=locked or {})
        if stored:
            _, candidate, merged = self.manager.check_mqtt(stored)
            assert merged is not None
            self.manager.set_mqtt(candidate, merged, Actor("setup"))
        self.runtime = Runtime(StateStore(), clock=self.clock)
        self.ingest = MqttIngest(self.manager.settings, self.runtime, connect=self.client)
        self.manager.mqtt_listeners.append(self.ingest.reconfigure)
        self.alarms = AlarmBoard()
        self.live = live
        self.retained_only = False
        self.checked: list[Settings] = []
        self.check_ok = check_ok
        self.setup = MqttSetup(
            self.manager,
            self.ingest,
            self.runtime,
            lambda: commands,
            self.alarms,
            check=self.check,
            sleep=no_sleep,
            window_s=5.0,
        )

    def client(self) -> FakeMqttClient:
        """Return a fake MQTT client that behaves as the current broker setting dictates."""
        settings = self.ingest.settings
        if self.retained_only and settings.mqtt_host != "broker.old":
            return FakeMqttClient(retained_messages(settings.heishamon_base))
        if self.live or settings.mqtt_host == "broker.old":
            return FakeMqttClient(pump_messages(base=settings.heishamon_base))
        return FakeMqttClient(fail_connect=True)

    async def check(self, settings: Settings) -> dict[str, Any]:
        """Record the checked settings and return the canned check result."""
        self.checked.append(settings)
        return {"ok": self.check_ok, "error_code": None if self.check_ok else "unreachable"}

    def audit(self) -> list[str]:
        """Return the audit actions of events not made by setup."""
        events = self.manager.store.audit_events(0.0, 4e9, 100)
        return [event.action for event in events if event.actor != "setup"]


OLD: dict[str, Any] = {
    "mqtt_host": "broker.old",
    "mqtt_username": "heat",
    "mqtt_password": "secret",
}
OLD_TYPED: dict[str, Any] = {**OLD, "mqtt_port": 1883, "mqtt_tls": False}


def retained_messages(base: str) -> list[Any]:
    """Build the retained-only copy of the pump messages for a base topic."""
    return [
        inbound(message.topic, message.payload.decode(), retained=True)
        for message in pump_messages(base=base)
    ]


@pytest.fixture
def old_broker(make_settings: Callable[..., Settings]) -> Settings:
    """Provide settings for the old broker."""
    return make_settings()


def test_the_request_fields_map_to_settings() -> None:
    """Request fields map to MQTT settings and unknown fields are refused."""
    assert changes_from({"host": "b", "base": "hp"}) == {
        "mqtt_host": "b",
        "heishamon_base": "hp",
    }
    with pytest.raises(ValueError, match="unknown fields: url"):
        changes_from({"url": "x"})


def test_a_new_host_does_not_take_the_password_along(old_broker: Settings) -> None:
    """A new host drops the stored password unless the request supplies one."""
    rig = Rig(old_broker, stored=OLD)
    errors, candidate, settings = rig.manager.check_mqtt(
        {"mqtt_host": "broker.new", "mqtt_password": "secret"}
    )
    assert errors == []
    assert settings is not None
    assert settings.mqtt_password is not None
    errors, candidate, settings = rig.manager.check_mqtt({"mqtt_host": "broker.new"})
    assert errors == []
    assert settings is not None
    assert "mqtt_password" not in candidate
    rig.manager.close()


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"mqtt_port": "1883"}, "type"),
        ({"mqtt_port": 70000}, "above_max"),
        ({"mqtt_tls": "yes"}, "type"),
        ({"mqtt_host": "two words"}, "invalid"),
        ({"mqtt_ca_file": "/nowhere/ca.pem"}, "ca_file_missing"),
        ({"heishamon_base": "pump/#"}, None),
        ({"ha_url": "http://x"}, "unknown_field"),
        ({}, "no_change"),
    ],
)
def test_invalid_broker_changes_are_refused(
    make_settings: Callable[..., Settings], changes: dict[str, Any], code: str | None
) -> None:
    """Invalid broker changes are refused with a matching issue code."""
    rig = Rig(make_settings())
    errors, _, settings = rig.manager.check_mqtt(changes)
    assert settings is None
    assert errors
    if code is not None:
        assert errors[0].code == code
    rig.manager.close()


def test_mqtt_inputs_are_stored_in_a_version_and_picked_as_signals(
    make_settings: Callable[..., Settings],
) -> None:
    """MQTT inputs are stored in a config version and can be chosen as the outside signal."""
    clock = FakeClock(1_800_000_000.0)
    manager = ConfigManager.open(make_settings(), clock, locked={})
    inputs = [{"topic": "garden/temp", "signal": "mqtt/garden", "unit": "°C"}]
    clock.advance(61.0)
    manager.apply(0, {"mqtt_inputs": inputs}, ADMIN)
    assert manager.settings.mqtt_inputs[0].signal_id == "mqtt/garden"
    assert manager.payload()["fields"]["mqtt_inputs"]["source"] == "store"
    clock.advance(61.0)
    manager.apply(manager.version or 0, {"control_outside_signal": "mqtt/garden"}, ADMIN)
    source = manager.settings.controller_config().outside
    assert source is not None
    assert source.signal == "mqtt/garden"
    refused = manager.validate({"mqtt_inputs": [{"topic": "a/#"}]})
    assert refused.errors
    manager.close()


def test_a_deployment_value_is_locked(make_settings: Callable[..., Settings]) -> None:
    """A broker field set by the deployment cannot be changed in the app."""
    rig = Rig(make_settings(mqtt_host="broker.env"), locked={"mqtt_host": Source.ENV})
    errors, _, _ = rig.manager.check_mqtt({"mqtt_host": "broker.app"})
    assert [issue.code for issue in errors] == ["locked"]
    fields = rig.manager.payload()["fields"]
    assert fields["mqtt_host"]["locked"] is True
    assert fields["mqtt_host"]["source"] == "env"
    rig.manager.close()


async def test_apply_needs_a_matching_successful_test(old_broker: Settings) -> None:
    """Apply is refused with 409 unless the same change was tested successfully."""
    rig = Rig(old_broker, stored=OLD)
    with pytest.raises(ConfigRefusedError) as refused:
        rig.setup.apply({"host": "broker.new"}, ADMIN)
    assert refused.value.status == 409
    await rig.setup.test({"host": "broker.other"})
    with pytest.raises(ConfigRefusedError) as refused:
        rig.setup.apply({"host": "broker.new"}, ADMIN)
    assert refused.value.body["errors"][0]["code"] == "test_required"
    rig.check_ok = False
    await rig.setup.test({"host": "broker.new"})
    with pytest.raises(ConfigRefusedError):
        rig.setup.apply({"host": "broker.new"}, ADMIN)
    rig.manager.close()


async def test_apply_is_refused_while_commands_are_enabled(old_broker: Settings) -> None:
    """Apply is refused while commands are enabled."""
    rig = Rig(old_broker, stored=OLD, commands=True)
    await rig.setup.test({"host": "broker.new"})
    with pytest.raises(ConfigRefusedError) as refused:
        rig.setup.apply({"host": "broker.new"}, ADMIN)
    assert refused.value.body["errors"][0]["code"] == "commands_enabled"
    rig.manager.close()


async def test_a_working_broker_is_kept_and_stored(old_broker: Settings) -> None:
    """A broker that delivers data is applied, stored and subscribed with the new base."""
    rig = Rig(old_broker, stored=OLD)
    run = asyncio.create_task(rig.ingest.run())
    await rig.setup.test({"host": "broker.new", "base": "hp"})
    result = rig.setup.apply({"host": "broker.new", "base": "hp"}, ADMIN)
    assert result["mqtt"]["apply"]["state"] == "applying"
    assert rig.setup._watch is not None
    await rig.setup._watch
    assert rig.setup.state == "applied"
    assert rig.manager.settings.mqtt_host == "broker.new"
    assert rig.manager.settings.mqtt_password is None
    assert rig.manager.store.connection()["mqtt_host"] == "broker.new"
    assert rig.ingest.topics[0] == "hp/#"
    assert rig.audit() == ["mqtt_connection"]
    run.cancel()
    rig.manager.close()


async def test_a_broker_without_data_is_reverted_with_an_alarm(old_broker: Settings) -> None:
    """A broker without data is reverted after the window with an alarm, keeping later changes."""
    rig = Rig(old_broker, stored=OLD, live=False)
    run = asyncio.create_task(rig.ingest.run())
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)
    rig.clock.advance(61.0)
    rig.manager.apply(rig.manager.version or 0, {"control_comfort_c": 21.5}, ADMIN)
    assert rig.setup._watch is not None
    await rig.setup._watch
    assert rig.setup.state == "reverted"
    assert rig.manager.settings.mqtt_host == "broker.old"
    assert rig.manager.settings.control_comfort_c == 21.5
    assert rig.manager.settings.mqtt_password is not None
    assert rig.manager.store.connection()["mqtt_host"] == "broker.old"
    assert [a for a in rig.audit() if a.startswith("mqtt")] == [
        "mqtt_connection",
        "mqtt_connection_reverted",
    ]
    alarm = rig.alarms.get(AlarmCode.MQTT_CONNECTION_REVERTED)
    assert alarm is not None
    assert "broker.new" in alarm.message
    await asyncio.sleep(0)
    assert rig.ingest.settings.mqtt_host == "broker.old"
    await rig.setup.test({"host": "broker.old"})
    assert not rig.alarms.is_active(AlarmCode.MQTT_CONNECTION_REVERTED)
    run.cancel()
    rig.manager.close()


async def test_the_password_never_appears_in_status_audit_or_config(
    old_broker: Settings,
) -> None:
    """The password never appears in the status, audit or config payload."""
    rig = Rig(old_broker, stored=OLD)
    await rig.setup.test({"host": "broker.new", "password": "hunter22"})
    rig.setup.apply({"host": "broker.new", "password": "hunter22"}, ADMIN)
    text = repr(rig.setup.status()) + repr(rig.manager.payload())
    text += repr([event.detail for event in rig.manager.store.audit_events(0.0, 4e9, 100)])
    assert "hunter22" not in text
    assert rig.manager.payload()["fields"]["mqtt_password"]["value"] == "set"
    assert rig.setup._watch is not None
    rig.setup._watch.cancel()
    rig.manager.close()


async def test_a_reconfigured_ingest_reconnects_with_the_new_base(
    make_settings: Callable[..., Settings],
) -> None:
    """Reconfiguring the ingest reconnects with the new base topic, but not if it is unchanged."""
    settings = make_settings()
    runtime = Runtime(StateStore(), clock=FakeClock(1_800_000_000.0))
    clients: list[FakeMqttClient] = []

    def connect() -> FakeMqttClient:
        """Return a fake client delivering pump messages for the current base."""
        client = FakeMqttClient(pump_messages(base=ingest.settings.heishamon_base))
        clients.append(client)
        return client

    ingest = MqttIngest(settings, runtime, connect=connect)
    run = asyncio.create_task(ingest.run())
    await settle(lambda: bool(clients) and clients[0].delivered.is_set())
    assert ingest.heishamon_received > 0
    ingest.reconfigure(make_settings(heishamon_base="other"))
    assert ingest.heishamon_received == 0
    await settle(lambda: len(clients) > 1 and clients[1].delivered.is_set())
    assert clients[1].subscribed == ["other/#"]
    assert ingest.heishamon_received > 0
    ingest.reconfigure(make_settings(heishamon_base="other"))
    await asyncio.sleep(0)
    assert len(clients) == 2
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run


@pytest.fixture
async def retained_pump(broker: tuple[str, int]) -> AsyncIterator[str]:
    """Publish a retained state and live temperatures on a real broker under a unique base."""
    host, port = broker
    base = f"ovenbird-test-{secrets.token_hex(4)}"
    async with aiomqtt.Client(host, port, identifier=f"{base}-pub") as client:
        await client.publish(f"{base}/main/Heatpump_State", b"1", retain=True)

        async def publish_live() -> None:
            """Publish the outside temperature every 0.2 s."""
            while True:
                await client.publish(f"{base}/main/Outside_Temp", b"3")
                await asyncio.sleep(0.2)

        live = asyncio.create_task(publish_live())
        yield base
        live.cancel()
        await client.publish(f"{base}/main/Heatpump_State", b"", retain=True)


@pytest.fixture
async def stale_pump(broker: tuple[str, int]) -> AsyncIterator[str]:
    """Publish a retained state only, with no live values, on a real broker."""
    host, port = broker
    base = f"ovenbird-stale-{secrets.token_hex(4)}"
    async with aiomqtt.Client(host, port, identifier=f"{base}-pub") as client:
        await client.publish(f"{base}/main/Heatpump_State", b"1", retain=True)
        yield base
        await client.publish(f"{base}/main/Heatpump_State", b"", retain=True)


async def test_the_check_sees_heishamon_on_a_real_broker(
    broker: tuple[str, int], retained_pump: str, make_settings: Callable[..., Settings]
) -> None:
    """On a real broker the check sees live HeishaMon data and flags an empty base."""
    host, port = broker
    settings = make_settings(mqtt_host=host, mqtt_port=port, heishamon_base=retained_pump)
    result = await mqtt_check(settings, limit_s=5.0)
    assert result["ok"] is True
    assert result["topic"] == f"{retained_pump}/main/Outside_Temp"
    empty = make_settings(mqtt_host=host, mqtt_port=port, heishamon_base=f"{retained_pump}-x")
    result = await mqtt_check(empty, limit_s=1.0)
    assert result["ok"] is False
    assert result["connected"] is True
    assert result["error_code"] == "no_heishamon"


async def test_the_check_reports_an_unreachable_broker(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    """The check reports an unreachable broker as not connected."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    result = await mqtt_check(make_settings(mqtt_host="127.0.0.1", mqtt_port=port), limit_s=3.0)
    assert result["ok"] is False
    assert result["connected"] is False
    assert result["error_code"] in {"unreachable", "timeout"}


async def test_an_applied_base_reaches_the_running_ingest_on_a_real_broker(
    broker: tuple[str, int], retained_pump: str, make_settings: Callable[..., Settings]
) -> None:
    """An applied base topic reaches the running ingest on a real broker."""
    host, port = broker
    clock = FakeClock(1_800_000_000.0)
    manager = ConfigManager.open(make_settings(), clock, locked={})
    _, candidate, merged = manager.check_mqtt({"mqtt_host": host, "mqtt_port": port})
    assert merged is not None
    manager.set_mqtt(candidate, merged, Actor("setup"))
    runtime = Runtime(StateStore(), clock=clock)
    ingest = MqttIngest(manager.settings, runtime)
    manager.mqtt_listeners.append(ingest.reconfigure)
    setup = MqttSetup(manager, ingest, runtime, lambda: False, AlarmBoard(), window_s=10.0)
    run = asyncio.create_task(ingest.run())
    await settle(lambda: runtime.mqtt_connected)
    assert ingest.heishamon_received == 0
    assert (await setup.test({"base": retained_pump}))["ok"] is True
    setup.apply({"base": retained_pump}, ADMIN)
    assert setup._watch is not None
    await setup._watch
    assert setup.state == "applied"
    assert ingest.topics == (f"{retained_pump}/#",)
    assert ingest.heishamon_received > 0
    run.cancel()
    manager.close()


async def test_the_check_needs_a_live_value_on_a_real_broker(
    broker: tuple[str, int], stale_pump: str, make_settings: Callable[..., Settings]
) -> None:
    """On a real broker the check refuses retained values without live data."""
    host, port = broker
    settings = make_settings(mqtt_host=host, mqtt_port=port, heishamon_base=stale_pump)
    result = await mqtt_check(settings, limit_s=1.0)
    assert result["ok"] is False
    assert result["error_code"] == "no_heishamon"
    assert "only retained" in result["error"]


class RetainedOnly(FakeMqttClient):
    """Fake client delivering only retained messages."""

    def __init__(self, _settings: Settings, base: str) -> None:
        """Create the client with the retained messages of the base."""
        super().__init__(retained_messages(base))


async def test_the_check_ignores_retained_values(make_settings: Callable[..., Settings]) -> None:
    """The check refuses retained-only values but accepts live ones."""
    settings = make_settings()
    base = settings.heishamon_base
    result = await mqtt_check(settings, connect=lambda s: RetainedOnly(s, base), limit_s=0.2)
    assert result["ok"] is False
    assert result["connected"] is True
    assert result["heishamon"] is False
    assert "only retained" in result["error"]
    live = await mqtt_check(
        settings,
        connect=lambda _s: FakeMqttClient(pump_messages(base=base)),
        limit_s=0.2,
    )
    assert live["ok"] is True


async def test_retained_values_alone_do_not_confirm_a_change(old_broker: Settings) -> None:
    """Retained values alone do not confirm a broker change, so it is reverted."""
    rig = Rig(old_broker, stored=OLD)
    rig.retained_only = True
    run = asyncio.create_task(rig.ingest.run())
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)
    assert rig.setup._watch is not None
    await rig.setup._watch
    assert rig.setup.state == "reverted"
    assert rig.manager.settings.mqtt_host == "broker.old"
    run.cancel()
    rig.manager.close()


def test_a_deployment_password_never_follows_a_new_host(
    make_settings: Callable[..., Settings],
) -> None:
    """A password from the deployment is refused for a new host, port or CA."""
    settings = make_settings(mqtt_host="broker.old", mqtt_password="from-env")
    rig = Rig(settings, locked={"mqtt_password": Source.ENV})
    for changes in (
        {"mqtt_host": "evil.example"},
        {"mqtt_port": 8883},
        {"mqtt_ca_file": __file__},
    ):
        errors, _, merged = rig.manager.check_mqtt(changes)
        assert [issue.code for issue in errors] == ["password_locked"], changes
        assert errors[0].params == {"source": "env", "env": "OVENBIRD_MQTT_PASSWORD"}
        assert merged is None
    errors, _, merged = rig.manager.check_mqtt({"mqtt_username": "other"})
    assert errors == []
    assert merged is not None
    rig.manager.close()


def test_a_deployment_password_is_never_sent_without_tls(
    make_settings: Callable[..., Settings],
) -> None:
    """A deployment password cannot be sent once TLS is turned off."""
    settings = make_settings(mqtt_host="broker.old", mqtt_password="from-env", mqtt_tls=True)
    rig = Rig(settings, locked={"mqtt_password": Source.ENV})
    errors, _, _ = rig.manager.check_mqtt({"mqtt_tls": False})
    assert [issue.code for issue in errors] == ["password_locked"]
    rig.manager.close()


async def test_the_api_test_never_sends_a_deployment_password_elsewhere(
    make_settings: Callable[..., Settings],
) -> None:
    """The API test refuses a changed host and never checks it with the deployment password."""
    settings = make_settings(mqtt_host="broker.old", mqtt_password="from-env")
    rig = Rig(settings, locked={"mqtt_password": Source.ENV})
    with pytest.raises(ConfigRefusedError) as refused:
        await rig.setup.test({"host": "evil.example"})
    assert refused.value.status == 422
    assert refused.value.body["errors"][0]["code"] == "password_locked"
    assert rig.checked == []
    rig.manager.close()


@pytest.mark.parametrize(
    "changes",
    [{"mqtt_tls": False}, {"mqtt_ca_file": __file__}],
)
def test_tls_off_or_another_ca_drops_the_stored_password(
    old_broker: Settings, changes: dict[str, Any]
) -> None:
    """Turning TLS off or changing the CA drops the stored password unless one is given."""
    rig = Rig(old_broker, stored={**OLD, "mqtt_tls": True})
    errors, candidate, settings = rig.manager.check_mqtt(changes)
    assert errors == []
    assert settings is not None
    assert settings.mqtt_password is None
    assert "mqtt_password" not in candidate
    errors, candidate, settings = rig.manager.check_mqtt({**changes, "mqtt_password": "again"})
    assert errors == []
    assert settings is not None
    assert settings.mqtt_password is not None
    errors, candidate, settings = rig.manager.check_mqtt({"mqtt_username": "other"})
    assert settings is not None
    assert settings.mqtt_password is not None
    rig.manager.close()


async def test_a_version_applied_during_the_window_is_kept_after_a_revert(
    old_broker: Settings,
) -> None:
    """A config and connection applied during the trial window survive the revert."""
    rig = Rig(old_broker, stored=OLD_TYPED, live=False)
    assert rig.manager.connection["mqtt_port"] == "1883"
    run = asyncio.create_task(rig.ingest.run())
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)
    rig.clock.advance(61.0)
    rig.manager.apply(rig.manager.version or 0, {"control_comfort_c": 21.5}, ADMIN)
    rig.manager.set_connection({"ha_url": "http://192.0.2.30:8123", "ha_token": "t" * 40}, ADMIN)
    assert rig.setup._watch is not None
    await rig.setup._watch
    assert rig.setup.state == "reverted"
    assert rig.manager.settings.mqtt_host == "broker.old"
    assert rig.manager.settings.mqtt_password is not None
    assert rig.manager.settings.control_comfort_c == 21.5
    assert rig.manager.settings.ha_url == "http://192.0.2.30:8123"
    assert rig.manager.connection["ha_url"] == "http://192.0.2.30:8123"
    assert rig.manager.store.connection()["mqtt_port"] == "1883"
    assert rig.manager.store.runtime_get(TRIAL_KEY) is None
    run.cancel()
    rig.manager.close()


async def test_a_failing_revert_raises_an_alarm_and_leaves_a_clear_state(
    old_broker: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing revert raises an alarm and keeps the trial record."""
    rig = Rig(old_broker, stored=OLD, live=False)
    run = asyncio.create_task(rig.ingest.run())
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)

    def broken(_previous: Any) -> Any:
        """Fail as if the disk were gone."""
        raise OSError("disk gone")

    monkeypatch.setattr(rig.manager, "restore_mqtt", broken)
    assert rig.setup._watch is not None
    await rig.setup._watch
    assert rig.setup.state == "failed"
    assert rig.setup.status()["apply"]["state"] == "failed"
    alarm = rig.alarms.get(AlarmCode.MQTT_REVERT_FAILED)
    assert alarm is not None
    assert "OSError" in alarm.message
    assert rig.manager.store.runtime_get(TRIAL_KEY) is not None
    await rig.setup.test({"host": "broker.old"})
    assert not rig.alarms.is_active(AlarmCode.MQTT_REVERT_FAILED)
    run.cancel()
    rig.manager.close()


async def test_an_unfinished_trial_is_watched_again_after_a_restart(
    old_broker: Settings,
) -> None:
    """An unfinished trial is watched and reverted after a restart."""
    rig = Rig(old_broker, stored=OLD, live=False)
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)
    assert rig.setup._watch is not None
    rig.setup._watch.cancel()
    assert rig.manager.store.runtime_get(TRIAL_KEY) is not None
    rig.manager.close()

    again = Rig(old_broker, live=False, clock=rig.clock)
    assert again.manager.settings.mqtt_host == "broker.new"
    assert again.setup.pending_trial() is not None
    run = asyncio.create_task(again.ingest.run())
    trial = asyncio.create_task(again.setup.run())
    await settle(lambda: again.setup.state == "reverted")
    assert again.manager.settings.mqtt_host == "broker.old"
    assert again.manager.settings.mqtt_password is not None
    assert again.manager.store.runtime_get(TRIAL_KEY) is None
    assert again.alarms.is_active(AlarmCode.MQTT_CONNECTION_REVERTED)
    trial.cancel()
    run.cancel()
    again.manager.close()


async def test_a_restart_with_commands_enabled_keeps_the_broker_of_an_unfinished_trial(
    old_broker: Settings,
) -> None:
    """After a restart with commands enabled the unfinished trial's broker is kept."""
    rig = Rig(old_broker, stored=OLD, live=False)
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)
    assert rig.setup._watch is not None
    rig.setup._watch.cancel()
    rig.manager.close()

    again = Rig(old_broker, live=False, clock=rig.clock, commands=True)
    run = asyncio.create_task(again.ingest.run())
    trial = asyncio.create_task(again.setup.run())
    await settle(lambda: again.setup.state == "applied")
    assert again.manager.settings.mqtt_host == "broker.new"
    assert again.setup.pending_trial() is None
    assert not again.alarms.is_active(AlarmCode.MQTT_CONNECTION_REVERTED)
    assert "commands enabled" in (again.setup.message or "")
    trial.cancel()
    run.cancel()
    again.manager.close()


async def test_a_successful_test_of_the_current_broker_ends_a_left_over_trial(
    old_broker: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Testing the current broker successfully ends a trial left over from a failed revert."""
    rig = Rig(old_broker, stored=OLD, live=False)
    run = asyncio.create_task(rig.ingest.run())
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)

    def broken(_previous: Any) -> Any:
        """Fail as if the disk were gone."""
        raise OSError("disk gone")

    monkeypatch.setattr(rig.manager, "restore_mqtt", broken)
    assert rig.setup._watch is not None
    await rig.setup._watch
    assert rig.setup.pending_trial() is not None
    await rig.setup.test({"host": "broker.old"})
    assert rig.setup.pending_trial() is not None
    await rig.setup.test({})
    assert rig.setup.pending_trial() is None
    run.cancel()
    rig.manager.close()


async def test_a_confirmed_trial_is_not_watched_again(old_broker: Settings) -> None:
    """A confirmed trial is not watched again."""
    rig = Rig(old_broker, stored=OLD)
    run = asyncio.create_task(rig.ingest.run())
    await rig.setup.test({"host": "broker.new"})
    rig.setup.apply({"host": "broker.new"}, ADMIN)
    assert rig.setup._watch is not None
    await rig.setup._watch
    assert rig.setup.state == "applied"
    assert rig.setup.pending_trial() is None
    run.cancel()
    rig.manager.close()


async def test_a_reconfigure_wakes_the_reconnect_delay(
    make_settings: Callable[..., Settings],
) -> None:
    """A reconfigure interrupts the reconnect delay so the new broker is used at once."""
    runtime = Runtime(StateStore(), clock=FakeClock(1_800_000_000.0))
    clients: list[FakeMqttClient] = []

    def connect() -> FakeMqttClient:
        """Return a failing client for the down broker, otherwise a pump-delivering client."""
        if ingest.settings.mqtt_host == "broker.down":
            client = FakeMqttClient(fail_connect=True)
        else:
            client = FakeMqttClient(pump_messages(base=ingest.settings.heishamon_base))
        clients.append(client)
        return client

    ingest = MqttIngest(
        make_settings(mqtt_host="broker.down"),
        runtime,
        connect=connect,
        backoff=Backoff(initial=3600.0, cap=3600.0),
    )
    run = asyncio.create_task(ingest.run())
    await settle(lambda: len(clients) == 1)
    await turns()
    started = time.monotonic()
    ingest.reconfigure(make_settings(mqtt_host="broker.up"))
    await settle(lambda: runtime.mqtt_connected, limit=2.0)
    assert time.monotonic() - started < 2.0
    assert ingest.heishamon_live > 0
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
