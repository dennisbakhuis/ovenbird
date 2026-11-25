"""The publish guard: the conditions without which no command is ever published.

Publishing is possible only when **all** of these hold:

1. ``control_mode`` is ``auto`` (the default is ``shadow``);
2. ``OVENBIRD_ALLOW_COMMANDS`` is ``true`` (default false; environment only, an
   options file cannot set it);
3. the configured broker (``mqtt_host``, optionally with ``mqtt_port``) is listed in
   ``OVENBIRD_COMMAND_BROKERS`` (default empty; environment only). The comparison is
   exact and case-insensitive on the configured name: no DNS resolution, no
   wildcards, no address ranges, so an entry for the dev broker ``mosquitto`` never
   matches a production broker by accident;
4. the service clock is the real clock (``OVENBIRD_CLOCK_SPEED`` 1 and no
   ``OVENBIRD_CLOCK_START``), **or** ``OVENBIRD_SIMULATION`` is ``true``
   (environment only). Simulation mode itself only accepts a loopback broker or the
   dev stack's ``mosquitto`` (settings validation, re-checked here), and the
   command adapter additionally refuses to release anything until the HeishaMon
   reports a simulated firmware version (``stats.version`` ending in ``-sim``), so a
   production broker that happens to be called ``mosquitto`` still never receives a
   command timed by a scaled clock.

These four are the **installation** conditions: the service builds a publishing
connection only when they hold. On top, a runtime :class:`ModeHold` can put an
``auto`` installation into ``shadow``: the operator's pause (``POST
api/v1/control/pause``, kept across restarts) or a lost configuration store waiting for
an admin's acknowledgement. While it holds, the guard refuses exactly as if the mode
were ``shadow``: nothing is queued, released or published.

The guard is evaluated when the service is built (no publishing connection exists
otherwise), again by the adapter before every command it releases, and again by
the publishing link before every publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ovenbird.config.network import is_simulation_broker, normalise_broker
from ovenbird_core.control import Mode

if TYPE_CHECKING:
    from ovenbird.config import Settings


class CommandsRefusedError(RuntimeError):
    """Publishing was attempted while the publish guard refuses it."""


def broker_listed(host: str, port: int, allowlist: frozenset[str]) -> bool:
    """Whether ``host`` (or ``host:port``) is an exact allowlist entry.

    Parameters
    ----------
    host
        Configured broker host.
    port
        Configured broker port.
    allowlist
        Normalised entries (see :func:`ovenbird.config.normalise_broker`).

    Returns
    -------
    bool
        ``True`` only for an exact match of the host or of ``host:port``.
    """
    try:
        name = normalise_broker(host)
    except ValueError:
        return False
    with_port = f"[{name}]:{port}" if ":" in name and not name.startswith("[") else f"{name}:{port}"
    return name in allowlist or with_port in allowlist


@dataclass(eq=False, slots=True)
class ModeHold:
    """Runtime reasons to run an ``auto`` installation as ``shadow``.

    Parameters
    ----------
    paused
        An operator paused control (stored in the configuration store).
    reset_pending
        The configuration store was lost; shadow until an admin acknowledges.
    releasing
        Release control is restoring the go-live snapshot: the controller is stopped
        (the loop runs as ``shadow``) while the adapter may still publish the
        restore commands; the pause follows when they are done.
    """

    paused: bool = False
    reset_pending: bool = False
    releasing: bool = False

    @property
    def active(self) -> bool:
        """Whether any reason holds."""
        return self.paused or self.reset_pending

    def refusals(self) -> tuple[str, ...]:
        """Return the holding reasons in a human form."""
        reasons: list[str] = []
        if self.paused:
            reasons.append("control is paused")
        if self.reset_pending:
            reasons.append("the configuration was reset; shadow until an admin acknowledges it")
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class PublishGuard:
    """The three publish conditions of one service instance.

    Parameters
    ----------
    mode
        Controller mode.
    allow_commands
        Explicit permission.
    host, port
        Broker the service is connected to.
    allowlist
        Normalised broker entries commands may go to.
    realtime_clock
        The service clock is the real clock.
    simulation
        ``OVENBIRD_SIMULATION``: the broker is a simulator.
    hold
        Runtime shadow reasons (pause, configuration reset).
    """

    mode: Mode
    allow_commands: bool
    host: str
    port: int
    allowlist: frozenset[str]
    realtime_clock: bool = True
    simulation: bool = False
    hold: ModeHold = field(default_factory=ModeHold, compare=False)

    @classmethod
    def from_settings(cls, settings: Settings, hold: ModeHold | None = None) -> PublishGuard:
        """Build the guard from validated settings (and the runtime hold, if any)."""
        return cls(
            mode=Mode(settings.control_mode),
            allow_commands=settings.allow_commands,
            host=settings.mqtt_host,
            port=settings.mqtt_port,
            allowlist=frozenset(settings.command_brokers),
            realtime_clock=settings.realtime_clock,
            simulation=settings.simulation,
            hold=hold if hold is not None else ModeHold(),
        )

    def refusals(self) -> tuple[str, ...]:
        """Every unmet condition, in a human form; empty when publishing is allowed."""
        reasons = list(self.installation_refusals())
        if not reasons:
            reasons.extend(self.hold.refusals())
        return tuple(reasons)

    @property
    def installed(self) -> bool:
        """Whether the installation conditions hold (a publishing connection may exist)."""
        return not self.installation_refusals()

    def require_installed(self) -> None:
        """Raise unless the installation conditions hold.

        Raises
        ------
        CommandsRefusedError
            With every unmet installation condition.
        """
        reasons = self.installation_refusals()
        if reasons:
            raise CommandsRefusedError("publishing refused: " + "; ".join(reasons))

    def installation_refusals(self) -> tuple[str, ...]:
        """Return the unmet installation conditions (mode, permission, broker, clock)."""
        reasons: list[str] = []
        if self.mode is not Mode.AUTO:
            reasons.append(f"control mode is {self.mode.value}, not auto")
        if self.allow_commands is not True:
            reasons.append("OVENBIRD_ALLOW_COMMANDS is not true")
        if not broker_listed(self.host, self.port, self.allowlist):
            reasons.append(f"broker {self.host}:{self.port} is not in OVENBIRD_COMMAND_BROKERS")
        if not self.realtime_clock and not self.simulation:
            reasons.append(
                "the clock is scaled (OVENBIRD_CLOCK_SPEED/OVENBIRD_CLOCK_START) and "
                "OVENBIRD_SIMULATION is not true"
            )
        if self.simulation and not is_simulation_broker(self.host):
            reasons.append(f"simulation mode refuses broker {self.host}")
        return tuple(reasons)

    @property
    def permits(self) -> bool:
        """Whether every condition holds."""
        return not self.refusals()

    def require(self) -> None:
        """Raise unless publishing is allowed.

        Raises
        ------
        CommandsRefusedError
            With every unmet condition.
        """
        reasons = self.refusals()
        if reasons:
            raise CommandsRefusedError("publishing refused: " + "; ".join(reasons))
