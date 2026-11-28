"""Change the broker connection from the app: test, apply, watch and revert.

1. ``POST api/v1/config/mqtt/test`` validates the candidate (the stored connection with
   the requested changes) and runs :func:`~ovenbird.mqttcheck.mqtt_check`. A successful
   test is remembered by a fingerprint of the whole candidate, password included, for
   :data:`TEST_VALID_S`.
2. ``PUT api/v1/config/mqtt`` applies only that tested candidate: it is stored and
   audited, the ingest reconnects at once and a watch starts.
3. The watch waits up to :data:`APPLY_WINDOW_S` for the new session to be connected and a
   live (not retained) HeishaMon ``main/*`` value to arrive. Then the change stands
   (``applied``). Otherwise the previous broker is put back on the current state (the
   configuration and HA connection as they are now; audited as
   ``mqtt_connection_reverted`` by the service), the ingest reconnects to it and the
   alarm ``mqtt_connection_reverted`` stays active until the next successful test or
   apply. When putting it back fails, the state is ``failed`` and the critical alarm
   ``mqtt_revert_failed`` is raised.

The trial survives a restart: the previous connection is kept in ``config.db``
(runtime key :data:`TRIAL_KEY`) until the watch decides, and :meth:`MqttSetup.run`
watches an unfinished trial again at start.

While commands are enabled the broker cannot be changed in the app: the command link
and the publish guard keep the broker they were started with, so a restart is needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError

from ovenbird.config import Issue, Settings
from ovenbird.configstore.apply import SYSTEM_ACTOR, Actor, ConfigManager, ConfigRefusedError
from ovenbird.configstore.fields import MQTT_FIELDS
from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.mqttcheck import mqtt_check

if TYPE_CHECKING:
    from ovenbird.mqtt import MqttIngest
    from ovenbird.runtime import Runtime

LOGGER = logging.getLogger("ovenbird.mqttsetup")
APPLY_WINDOW_S: Final = 60.0
TEST_VALID_S: Final = 600.0
POLL_S: Final = 1.0
TRIAL_KEY: Final = "mqtt_trial"
API_FIELDS: Final = {
    "host": "mqtt_host",
    "port": "mqtt_port",
    "username": "mqtt_username",
    "password": "mqtt_password",
    "tls": "mqtt_tls",
    "ca_file": "mqtt_ca_file",
    "client_id": "mqtt_client_id",
    "base": "heishamon_base",
}
"""Request field to settings field."""

type Check = Callable[[Settings], Awaitable[dict[str, Any]]]


def changes_from(body: Mapping[str, Any]) -> dict[str, Any]:
    """Return the settings changes of a request body.

    Raises
    ------
    ValueError
        For a field that is not part of the broker connection.
    """
    unknown = sorted(set(body) - set(API_FIELDS))
    if unknown:
        raise ValueError(f"unknown fields: {', '.join(unknown)}")
    return {API_FIELDS[key]: value for key, value in body.items()}


def fingerprint(candidate: Mapping[str, str]) -> str:
    """Return a digest of the broker part of a stored connection (password included)."""
    broker = {name: candidate.get(name) for name in MQTT_FIELDS}
    return hashlib.sha256(json.dumps(broker, sort_keys=True).encode()).hexdigest()


class MqttSetup:
    """Test, apply and, when it does not come up, revert a broker connection.

    Parameters
    ----------
    manager
        Stores and audits the connection and tells the MQTT listeners.
    ingest
        The running ingest (its session and HeishaMon message count).
    runtime
        The link state (``mqtt_connected``).
    commands_enabled
        Whether commands may be published now (a change is then refused).
    alarms
        The alarm board (``mqtt_connection_reverted``, ``mqtt_revert_failed``).
    check
        The connection test (tests pass a fake).
    sleep
        Awaitable sleep of the watch (tests pass a fast one).
    window_s
        How long the watch waits for the new connection.
    """

    def __init__(
        self,
        manager: ConfigManager,
        ingest: MqttIngest,
        runtime: Runtime,
        commands_enabled: Callable[[], bool],
        alarms: AlarmBoard | None = None,
        *,
        check: Check = mqtt_check,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        window_s: float = APPLY_WINDOW_S,
    ) -> None:
        self.manager = manager
        self.ingest = ingest
        self.runtime = runtime
        self.commands_enabled = commands_enabled
        self.alarms = alarms
        self.check = check
        self.sleep = sleep
        self.window_s = window_s
        self.state = "idle"
        self.message: str | None = None
        self.changed_at: str | None = None
        self._tested: tuple[str, float] | None = None
        self._watch: asyncio.Task[None] | None = None

    def status(self) -> dict[str, Any]:
        """Return ``GET api/v1/config/mqtt``: the link and the last apply."""
        settings = self.manager.settings
        return {
            "connected": self.runtime.mqtt_connected,
            "host": settings.mqtt_host,
            "port": settings.mqtt_port,
            "base": settings.heishamon_base,
            "heishamon_messages": self.ingest.heishamon_received,
            "apply": {"state": self.state, "message": self.message, "at": self.changed_at},
            "commands_enabled": self.commands_enabled(),
        }

    async def test(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and test a candidate; remember it when the test succeeds.

        Raises
        ------
        ConfigRefusedError
            ``422`` for an invalid candidate (no change is fine for a test).
        """
        candidate, settings = self._candidate(body, allow_same=True)
        result = await self.check(settings)
        if result.get("ok"):
            self._tested = (fingerprint(candidate), time.monotonic())
            self._clear_alarm("a broker connection was tested successfully")
            if fingerprint(candidate) == fingerprint(self._current()) and not self._watching():
                self.manager.store.runtime_set(TRIAL_KEY, None)
        return result

    def apply(self, body: Mapping[str, Any], actor: Actor) -> dict[str, Any]:
        """Store the tested candidate, reconnect and start the watch.

        Raises
        ------
        ConfigRefusedError
            ``409`` while commands are enabled, while an apply is being watched or
            without a matching successful test; ``422`` for an invalid candidate or no
            change.
        """
        if self.commands_enabled():
            raise _refused(
                409,
                "commands_enabled",
                "commands are enabled: the command link keeps its broker until a restart, "
                "so change the broker in the deployment and restart",
            )
        if self._watching():
            raise _refused(409, "apply_pending", "the last broker change is still being checked")
        candidate, settings = self._candidate(body, allow_same=False)
        tested = self._tested
        fresh = tested is not None and time.monotonic() - tested[1] <= TEST_VALID_S
        if not fresh or tested is None or tested[0] != fingerprint(candidate):
            raise _refused(
                409, "test_required", "test exactly these broker settings successfully first"
            )
        previous = self._current()
        self._tested = None
        self._save_trial(previous)
        self.manager.set_mqtt(candidate, settings, actor)
        self._start_watch(previous)
        return {"config": self.manager.payload(), "mqtt": self.status()}

    async def run(self) -> None:
        """Watch a trial left unfinished by a restart, then idle (a service component)."""
        previous = self.pending_trial()
        if previous is not None and self.commands_enabled():
            LOGGER.warning(
                "an unfinished broker change is kept: commands are enabled and the command "
                "link started on this broker"
            )
            self.manager.store.runtime_set(TRIAL_KEY, None)
            self._set(
                "applied",
                "kept after a restart with commands enabled; the command link uses this broker",
            )
        elif previous is not None and (self._watch is None or self._watch.done()):
            LOGGER.warning("an unfinished broker change is watched again after the restart")
            await self._start_watch(previous)
        await asyncio.Event().wait()

    def pending_trial(self) -> dict[str, str] | None:
        """Return the connection before an unfinished broker change, if there is one."""
        raw = self.manager.store.runtime_get(TRIAL_KEY)
        if raw is None:
            return None
        try:
            stored = json.loads(raw)
        except ValueError:
            LOGGER.error("the stored broker trial is unreadable; it is dropped")
            self.manager.store.runtime_set(TRIAL_KEY, None)
            return None
        previous = stored.get("previous") if isinstance(stored, dict) else None
        if not isinstance(previous, dict):
            self.manager.store.runtime_set(TRIAL_KEY, None)
            return None
        return {str(name): str(value) for name, value in previous.items() if name in MQTT_FIELDS}

    def _save_trial(self, previous: Mapping[str, str]) -> None:
        """Store the previous broker so a restart during the trial can revert to it."""
        self.manager.store.runtime_set(
            TRIAL_KEY,
            json.dumps({"previous": dict(previous), "at": self.manager.clock().wall.isoformat()}),
        )

    def _start_watch(self, previous: Mapping[str, str]) -> asyncio.Task[None]:
        """Start the task that waits for HeishaMon data from the new broker."""
        self._set("applying", f"waiting up to {self.window_s:.0f} s for HeishaMon data")
        self._watch = asyncio.get_running_loop().create_task(self.watch(previous))
        return self._watch

    async def watch(self, previous: Mapping[str, str]) -> None:
        """Keep the new connection when live HeishaMon data arrives in time, else revert."""
        waited = 0.0
        while waited < self.window_s:
            if self.runtime.mqtt_connected and self.ingest.heishamon_live > 0:
                self.manager.store.runtime_set(TRIAL_KEY, None)
                self._set("applied", "connected; HeishaMon data arrives")
                self._clear_alarm("the new broker connection works")
                return
            await self.sleep(POLL_S)
            waited += POLL_S
        settings = self.manager.settings
        why = (
            "no live HeishaMon data"
            if self.runtime.mqtt_connected
            else f"no connection to {settings.mqtt_host}:{settings.mqtt_port}"
        )
        try:
            self.revert(previous, why)
        except Exception as exc:
            self._revert_failed(why, exc)

    def revert(self, previous: Mapping[str, str], why: str) -> None:
        """Put the broker of ``previous`` back on the current configuration.

        Raises
        ------
        Exception
            Whatever storing or rebuilding the settings raises; the trial marker stays.
        """
        candidate, restored = self.manager.restore_mqtt(previous)
        self.manager.set_mqtt(
            candidate, restored, Actor(SYSTEM_ACTOR), action="mqtt_connection_reverted"
        )
        self.manager.store.runtime_set(TRIAL_KEY, None)
        text = (
            f"the broker change was reverted: {why} within {self.window_s:.0f} s; back on "
            f"{restored.mqtt_host}:{restored.mqtt_port}"
        )
        self._set("reverted", text)
        LOGGER.warning("%s", text)
        if self.alarms is not None:
            self.alarms.raise_alarm(AlarmCode.MQTT_CONNECTION_REVERTED, text, self.manager.clock())

    def _revert_failed(self, why: str, exc: Exception) -> None:
        """Record and alarm that the previous broker could not be restored after a failed trial."""
        detail = (
            "the previous broker no longer fits the configuration"
            if isinstance(exc, ValidationError)
            else type(exc).__name__
        )
        text = (
            f"the broker change did not work ({why} within {self.window_s:.0f} s) and putting "
            f"the previous broker back failed ({detail}); the new broker stays: set a working "
            "broker under Settings, MQTT, or in the deployment"
        )
        LOGGER.exception("%s", text)
        self._set("failed", text)
        if self.alarms is not None:
            self.alarms.raise_alarm(AlarmCode.MQTT_REVERT_FAILED, text, self.manager.clock())

    def _candidate(
        self, body: Mapping[str, Any], *, allow_same: bool
    ) -> tuple[dict[str, str], Settings]:
        """Return the broker values and settings a request would produce, refusing invalid ones."""
        try:
            changes = changes_from(body)
        except ValueError as exc:
            raise _refused(422, "unknown_field", str(exc)) from None
        errors, candidate, settings = self.manager.check_mqtt(changes)
        if allow_same and [issue.code for issue in errors] == ["no_change"]:
            errors, settings = [], self.manager.settings
        if errors or settings is None:
            raise ConfigRefusedError(
                422, {"errors": [issue.to_json() for issue in errors], "warnings": []}
            )
        return candidate, settings

    def _current(self) -> dict[str, str]:
        """Return the stored broker fields now in force."""
        return {
            name: value for name, value in self.manager.connection.items() if name in MQTT_FIELDS
        }

    def _watching(self) -> bool:
        """Return whether a trial watch is still running."""
        return self._watch is not None and not self._watch.done()

    def _set(self, state: str, message: str) -> None:
        """Set the state and message shown to the user and stamp the change time."""
        self.state = state
        self.message = message
        self.changed_at = self.manager.clock().wall.isoformat()

    def _clear_alarm(self, why: str) -> None:
        """Clear the broker-reverted and revert-failed alarms."""
        if self.alarms is not None:
            for code in (AlarmCode.MQTT_CONNECTION_REVERTED, AlarmCode.MQTT_REVERT_FAILED):
                self.alarms.clear(code, self.manager.clock(), why)


def _refused(status: int, code: str, message: str) -> ConfigRefusedError:
    """Return the refusal that answers a request with one issue."""
    return ConfigRefusedError(
        status, {"errors": [Issue(None, code, message).to_json()], "warnings": []}
    )
