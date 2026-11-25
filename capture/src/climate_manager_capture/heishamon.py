"""Pure model of how a HeishaMon board behaves on MQTT.

Behaviour as observed on a board and in recordings:

- The board polls the pump every 5 s. A ``main/*`` topic is published only when
  its value changed, plus a full dump of every topic every 300 s and once on the
  first MQTT connect. Everything is retained, QoS 0.
- ``stats`` (JSON) and ``LWT``=``Online`` go out every query cycle. ``Online`` is
  *not* retained; the will message ``LWT``=``Offline`` *is*.
- Commands arrive on ``commands/#``. A payload is read as its leading integer
  (no range check, ``"21.5"`` becomes 21, non-numeric becomes 0). Nothing is
  echoed; the new value shows up in ``main/*`` at the next query cycle. The
  command queue holds 10 entries.
"""

from __future__ import annotations

import json
import math
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

QUERY_INTERVAL_S: Final = 5.0
DUMP_INTERVAL_S: Final = 300.0
COMMAND_QUEUE_MAX: Final = 10

#: ``commands/<name>`` → the ``main/*`` topics HeishaMon updates after the pump
#: acknowledged the write.
SIDE_EFFECTS: Final[dict[str, tuple[str, ...]]] = {
    "SetHeatpump": ("main/Heatpump_State",),
    "SetOperationMode": ("main/Operating_Mode_State",),
    "SetZ1HeatRequestTemperature": ("main/Z1_Heat_Request_Temp",),
}

#: Extra topics the pump also updates but the integration does not verify
#: against. Enabled with ``CommandSemantics(secondary=True)`` so dashboards
#: look right in the stateful simulator.
SECONDARY_SIDE_EFFECTS: Final[dict[str, tuple[str, ...]]] = {
    "SetZ1HeatRequestTemperature": ("main/Z1_Water_Target_Temp",),
}

_TOINT_RE: Final = re.compile(r"^\s*([+-]?\d+)")


def to_int(payload: str) -> int:
    """Return the leading integer of ``payload``, otherwise 0, as HeishaMon reads commands."""
    match = _TOINT_RE.match(payload)
    return int(match.group(1)) if match else 0


def command_name(topic: str) -> str | None:
    """Return the command name from a ``.../commands/<name>`` topic, or ``None``."""
    parts = topic.split("/")
    if len(parts) < 2 or parts[-2] != "commands":
        return None
    return parts[-1]


@dataclass(frozen=True)
class SideEffect:
    """A ``main/*`` update caused by a processed command."""

    suffix: str
    payload: str


@dataclass(frozen=True)
class Emission:
    """One MQTT publish the cadence model wants sent."""

    suffix: str
    payload: str
    retain: bool


class CommandSemantics:
    """Queue commands and release their side-effects on the 5 s query grid.

    Parameters
    ----------
    clock
        Returns the current time in seconds (any monotonic reference).
    query_interval
        Seconds between pump queries; side-effects land on this grid.
    queue_max
        HeishaMon's command-queue depth; further commands are dropped.
    secondary
        Also emit :data:`SECONDARY_SIDE_EFFECTS`.
    """

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        query_interval: float = QUERY_INTERVAL_S,
        queue_max: int = COMMAND_QUEUE_MAX,
        secondary: bool = False,
    ) -> None:
        self._clock = clock
        self._query_interval = query_interval
        self._queue_max = queue_max
        self._secondary = secondary
        self._queue: deque[tuple[float, str, int]] = deque()
        self._origin: float = clock()
        self.owned: set[str] = set()
        self.last_command_at: dict[str, float] = {}
        self.received = 0
        self.dropped = 0
        self.ignored = 0

    def receive(self, name: str, payload: str) -> bool:
        """Accept a command; return ``False`` when it was dropped or unknown."""
        now = self._clock()
        if name not in SIDE_EFFECTS:
            self.ignored += 1
            return False
        if len(self._queue) >= self._queue_max:
            self.dropped += 1
            return False
        self._queue.append((now, name, to_int(payload)))
        self.received += 1
        return True

    def _next_tick(self, received_at: float) -> float:
        steps = math.floor((received_at - self._origin) / self._query_interval) + 1
        return self._origin + steps * self._query_interval

    def due(self, now: float | None = None) -> list[SideEffect]:
        """Release side-effects of every queued command whose query tick passed."""
        current = self._clock() if now is None else now
        effects: list[SideEffect] = []
        while self._queue and self._next_tick(self._queue[0][0]) <= current:
            _, name, value = self._queue.popleft()
            targets = SIDE_EFFECTS[name]
            if self._secondary:
                targets += SECONDARY_SIDE_EFFECTS.get(name, ())
            for suffix in targets:
                self.owned.add(suffix)
                self.last_command_at[suffix] = current
                effects.append(SideEffect(suffix, str(value)))
        return effects

    def release_stale(self, now: float, max_age: float) -> set[str]:
        """Drop ownership of topics not commanded for ``max_age`` seconds."""
        released = {
            suffix
            for suffix, at in self.last_command_at.items()
            if suffix in self.owned and now - at >= max_age
        }
        self.owned -= released
        return released


class Cadence:
    """Decide *what* to publish each query cycle, like the firmware does.

    Callers keep the current value of every topic up to date with :meth:`set`
    and call :meth:`tick` frequently; the returned emissions follow the
    on-change / periodic-dump / stats / LWT rules.

    Parameters
    ----------
    clock
        Returns the current time in seconds.
    query_interval
        Seconds between query cycles.
    dump_interval
        Seconds between full dumps of every topic.
    version
        Firmware version string reported in ``stats``.
    """

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        query_interval: float = QUERY_INTERVAL_S,
        dump_interval: float = DUMP_INTERVAL_S,
        version: str = "3.9-sim",
    ) -> None:
        self._clock = clock
        self._query_interval = query_interval
        self._dump_interval = dump_interval
        self._version = version
        self._current: dict[str, str] = {}
        self._published: dict[str, str] = {}
        self._started: float | None = None
        self._last_query: float | None = None
        self._last_dump: float | None = None
        self.reads = 0

    def set(self, suffix: str, payload: str) -> None:
        """Record the latest decoded value for ``suffix``."""
        self._current[suffix] = payload

    def will(self) -> Emission:
        """Return the MQTT last-will HeishaMon registers on connect."""
        return Emission("LWT", "Offline", True)

    def _stats(self, now: float) -> str:
        uptime_ms = int((now - (self._started or now)) * 1000)
        return json.dumps(
            {
                "uptime": uptime_ms,
                "voltage": 3.3,
                "free memory": 45,
                "free heap": 180000,
                "wifi": 90,
                "mqtt reconnects": 1,
                "total reads": self.reads,
                "good reads": self.reads,
                "bad crc reads": 0,
                "bad header reads": 0,
                "too short reads": 0,
                "too long reads": 0,
                "timeout reads": 0,
                "version": self._version,
                "board": "simulator",
                "rules active": False,
            },
            sort_keys=True,
        )

    def tick(self, now: float | None = None) -> list[Emission]:
        """Return what a firmware query cycle would publish at ``now``."""
        current = self._clock() if now is None else now
        if self._started is None:
            self._started = current
        if self._last_query is not None and current - self._last_query < self._query_interval:
            return []
        self._last_query = current
        self.reads += 1
        dump = self._last_dump is None or current - self._last_dump >= self._dump_interval
        emissions: list[Emission] = []
        for suffix, payload in self._current.items():
            if dump or self._published.get(suffix) != payload:
                emissions.append(Emission(suffix, payload, True))
                self._published[suffix] = payload
        if dump:
            self._last_dump = current
        emissions.append(Emission("stats", self._stats(current), True))
        emissions.append(Emission("LWT", "Online", False))
        return emissions
