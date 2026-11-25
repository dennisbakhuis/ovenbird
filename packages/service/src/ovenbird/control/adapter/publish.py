"""The adapter's broker side: the closed topic allowlist and the publishing link.

:class:`AdapterConfig` names the six command topics and builds their payloads;
:class:`CommandLink` is the only code in the service that publishes. Both live in this
one module, so the publishing guarantee (one publish call, one module naming command
topics) can be checked on a single file.
"""

from __future__ import annotations

import json
import logging
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, Final, Protocol, Self

import aiomqtt

from ovenbird.control.adapter.model import (
    Command,
    CommandKind,
)
from ovenbird.control.guard import CommandsRefusedError, PublishGuard
from ovenbird.mqtt import CONNECT_TIMEOUT_S, KEEPALIVE_S, tls_context
from ovenbird_core import (
    PUMP_SETTINGS,
    PumpSetting,
)
from ovenbird_core.control import IntentKind, SafetyLimits

if TYPE_CHECKING:
    from ovenbird.config import Settings

COMMANDS: Final = "commands"
SETPOINT_COMMANDS: Final = {
    "setcurves_target_high": "SetCurves",
    "z1_heat_request_temperature": "SetZ1HeatRequestTemperature",
}
QUIET_RANGE: Final = (0, 3)


@dataclass(frozen=True, slots=True)
class AdapterConfig:
    """Limits and timing of the adapter.

    Parameters
    ----------
    base
        HeishaMon topic base.
    setpoint_register
        ``setcurves_target_high`` or ``z1_heat_request_temperature``.
    setpoint_range, pump_duty_range, quiet_range
        Inclusive integer clamps per setting.
    min_spacing_s
        Minimum time between two published commands.
    verify_timeout_s
        Time a command has to show up before it is retried (or, when the pump
        already reports its value, counts as verified).
    max_retries
        Retries after the first attempt.
    daily_budget
        Published commands per UTC day.
    hold_s
        First hold after a failed verification or a foreign writer.
    escalation_window_s
        Holds within this window escalate.
    escalation_factor
        The second hold in the window lasts ``hold_s`` times this.
    latch_after
        This many holds in the window latch until an operator releases them.
    safety_reserve
        Safety corrections allowed beyond the daily budget.
    max_corrections
        Safety corrections per ``correction_window_s``.
    correction_window_s
        Window of ``max_corrections``.
    restart_grace_s
        After a detected HeishaMon restart, read-back differences are attributed to
        the restart for this long (no foreign-writer hold).
    require_simulated_board
        Release nothing unless HeishaMon reports a simulated firmware version.
    direct_heating_mode
        Required ``Heating_Mode``.
    allowed_operating_modes
        Accepted ``Operating_Mode_State`` values.
    envelope_rule
        The safety limits the HeishaMon envelope rule enforces when the owner declared
        it installed; ``None`` otherwise (every read-back mismatch is then a foreign
        writer).
    """

    base: str
    setpoint_register: str
    setpoint_range: tuple[int, int]
    pump_duty_range: tuple[int, int]
    quiet_range: tuple[int, int] = QUIET_RANGE
    min_spacing_s: float = 7.0
    verify_timeout_s: float = 30.0
    max_retries: int = 3
    daily_budget: int = 150
    hold_s: float = 3600.0
    escalation_window_s: float = 12 * 3600.0
    escalation_factor: float = 4.0
    latch_after: int = 3
    safety_reserve: int = 10
    max_corrections: int = 3
    correction_window_s: float = 3600.0
    restart_grace_s: float = 600.0
    require_simulated_board: bool = False
    direct_heating_mode: int = 1
    allowed_operating_modes: frozenset[int] = frozenset({0})
    envelope_rule: SafetyLimits | None = None

    def __post_init__(self) -> None:
        """Validate the register and the ranges."""
        if self.setpoint_register not in SETPOINT_COMMANDS:
            raise ValueError(f"unknown setpoint register {self.setpoint_register!r}")
        for low, high in (self.setpoint_range, self.pump_duty_range, self.quiet_range):
            if low > high:
                raise ValueError("clamp ranges must be ordered")
        if self.latch_after < 2:
            raise ValueError("latch_after must be at least 2")

    @classmethod
    def from_settings(cls, settings: Settings, safety: SafetyLimits) -> AdapterConfig:
        """Build the adapter limits from the settings and the controller's safety limits."""
        return cls(
            base=settings.heishamon_base,
            setpoint_register=settings.command_setpoint_register,
            setpoint_range=(
                math.ceil(safety.min_setpoint_c - 1e-9),
                math.floor(safety.max_supply_c + 1e-9),
            ),
            pump_duty_range=(settings.command_pump_duty_min, settings.command_pump_duty_max),
            min_spacing_s=settings.command_min_spacing_s,
            verify_timeout_s=settings.command_verify_timeout_s,
            max_retries=settings.command_max_retries,
            daily_budget=settings.command_daily_budget,
            hold_s=settings.command_hold_s,
            escalation_window_s=settings.command_escalation_hours * 3600.0,
            escalation_factor=settings.command_escalation_factor,
            latch_after=settings.command_latch_after,
            require_simulated_board=settings.simulation,
            envelope_rule=safety if settings.envelope_rule_installed else None,
        )

    def command_name(self, kind: CommandKind) -> str:
        """HeishaMon command carrying ``kind``."""
        if isinstance(kind, PumpSetting):
            return PUMP_SETTINGS[kind].command
        match kind:
            case IntentKind.WATER_SETPOINT:
                return SETPOINT_COMMANDS[self.setpoint_register]
            case IntentKind.MAX_PUMP_DUTY:
                return "SetMaxPumpDuty"
            case IntentKind.QUIET_MODE:
                return "SetQuietMode"

    def topic(self, kind: CommandKind) -> str:
        """Full command topic of ``kind``."""
        return f"{self.base}/{COMMANDS}/{self.command_name(kind)}"

    def topics(self) -> frozenset[str]:
        """Return the closed set of topics the adapter may publish to.

        The controller's three intents and the operator's three pump settings: six
        topics, one per setting.
        """
        return frozenset(self.topic(kind) for kind in (*IntentKind, *PumpSetting))

    def setting_topics(self) -> frozenset[str]:
        """Return the topics of the operator's pump settings (the second allowlist)."""
        return frozenset(self.topic(setting) for setting in PumpSetting)

    def clamp_range(self, kind: CommandKind) -> tuple[int, int]:
        """Inclusive integer range of ``kind``."""
        if isinstance(kind, PumpSetting):
            spec = PUMP_SETTINGS[kind]
            return spec.low, spec.high
        match kind:
            case IntentKind.WATER_SETPOINT:
                return self.setpoint_range
            case IntentKind.MAX_PUMP_DUTY:
                return self.pump_duty_range
            case IntentKind.QUIET_MODE:
                return self.quiet_range

    def payload(self, kind: CommandKind, value: int) -> str:
        """Payload of ``kind`` carrying ``value``."""
        if kind is IntentKind.WATER_SETPOINT and self.setpoint_register == "setcurves_target_high":
            body = {"zone1": {"heat": {"target": {"high": value}}}}
            return json.dumps(body, separators=(",", ":"))
        return str(value)


class PublishingClient(Protocol):
    """The broker capabilities the command link uses."""

    async def __aenter__(self) -> Any:
        """Connect."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect."""
        ...

    async def publish(self, topic: str, payload: str, qos: int, retain: bool) -> Any:
        """Publish one message."""
        ...


class CommandLink:
    """The publishing MQTT connection; exists only while the guard permits publishing.

    Parameters
    ----------
    settings
        Broker address, credentials and TLS (the same broker the ingest reads).
    guard
        Publish guard; checked here and before every publish.
    topics
        The only topics this link publishes to.
    client_factory
        Builds the underlying client from keyword arguments (injectable for tests).

    Raises
    ------
    CommandsRefusedError
        When the installation conditions of the guard do not hold (a pause only
        stops :meth:`send`).
    """

    __slots__ = ("_client", "_guard", "_topics")

    def __init__(
        self,
        settings: Settings,
        guard: PublishGuard,
        topics: frozenset[str],
        *,
        client_factory: Callable[..., PublishingClient] = aiomqtt.Client,
    ) -> None:
        guard.require_installed()
        self._guard = guard
        self._topics = topics
        password = settings.mqtt_password.get_secret_value() if settings.mqtt_password else None
        self._client = client_factory(
            hostname=settings.mqtt_host,
            port=settings.mqtt_port,
            username=settings.mqtt_username,
            password=password,
            identifier=f"ovenbird-cmd-{secrets.token_hex(4)}",
            will=None,
            clean_session=True,
            keepalive=KEEPALIVE_S,
            timeout=CONNECT_TIMEOUT_S,
            tls_context=tls_context(settings),
            logger=logging.getLogger("ovenbird.mqtt.commands"),
        )

    def __repr__(self) -> str:
        """Representation without credentials."""
        return "CommandLink()"

    async def __aenter__(self) -> Self:
        """Connect to the broker."""
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect from the broker."""
        await self._client.__aexit__(exc_type, exc, tb)

    async def send(self, command: Command) -> None:
        """Publish ``command`` (QoS 1, never retained).

        Raises
        ------
        CommandsRefusedError
            When the guard refuses or the topic is not allowlisted.
        """
        self._guard.require()
        if command.topic not in self._topics:
            raise CommandsRefusedError(f"topic {command.topic!r} is not allowlisted")
        await self._client.publish(command.topic, command.payload, qos=1, retain=False)


class CommandSender(Protocol):
    """What the worker needs from a link."""

    async def __aenter__(self) -> CommandSender:
        """Connect."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect."""
        ...

    async def send(self, command: Command) -> None:
        """Publish a command."""
        ...
