"""A HeishaMon board on top of the plant model, advanced one query cycle at a time.

:class:`SimulatedHeishaMon` is pure apart from its own state: it never reads a
clock and never touches the network. Each :meth:`SimulatedHeishaMon.cycle`
advances simulated time by one query interval (5 s) and returns what the
firmware would publish then:

1. the plant advances over the interval with the water target in effect;
2. commands received since the previous cycle are executed (in arrival order,
   at most :data:`COMMAND_QUEUE_MAX` per cycle, the rest dropped);
3. register topics show the new values at once; the water target topics
   (``Z1_Water_Target_Temp``, ``Main_Target_Temp``) and the plant follow
   ``target_lag_cycles`` cycles later, as observed on a recorded pump;
4. :class:`~climate_manager_capture.heishamon.Cadence` decides what goes out:
   changed ``main/*`` topics, a full dump every 300 s (and on the first cycle),
   ``stats`` and a non-retained ``LWT`` ``Online``.

During a defrost the pump drives its own pump duty and ignores the setting:
``Pump_Duty`` reads :data:`DEFROST_PUMP_DUTY` (220, an arbitrary high value above any
setting) while ``Max_Pump_Duty`` keeps the setting, and ``Pump_Duty``
returns to the setting when the defrost ends. ``Room_Thermostat_Temp`` is the remote's
integer room thermostat: the plant's air temperature plus :data:`THERMOSTAT_OFFSET_K`
and seeded noise (generic values: a remote that reads the room air without offset and a
tenth of a kelvin of noise; :mod:`ovenbird_sim.evaluate.sensors` fits an install's own),
rounded, sampled once a minute.

Test hooks (simulator only, nothing a real board has): :meth:`SimulatedHeishaMon.reboot`
restarts the firmware's publishing (uptime 0, a full dump); :attr:`SimulatedHeishaMon.dhw`
reports a DHW run (``ThreeWay_Valve_State`` 1; the plant is not affected);
:attr:`SimulatedHeishaMon.silenced` names ``main/*`` topics that are not published.

Commands are never echoed. The room sensor (an MQTT input for the service, not a
HeishaMon topic) is the shared sensor model of the evaluation
(:class:`~ovenbird_sim.evaluate.sensors.RoomSensorModel`, run by a
:class:`~ovenbird_sim.evaluate.sensors.RoomSensorDevice` on the plant's air
temperature): by default a periodic sensor re-sending its 0.1 K value every
``room_interval_s``; with ``room_sensor`` set, e.g. a send-on-delta device
(0.1 K grid, no heartbeat), plus its companion humidity on ``humidity_topic``. Both
are published retained, as a Zigbee bridge does.

Fault injection (simulator only, under ``inject_prefix``, never a HeishaMon topic):

- ``<prefix>/main/<Name>`` with a payload overrides what ``main/<Name>`` reports
  (``Pump_Flow`` ``3.0``, ``Error`` ``H62``, ``Internal_Heater_State`` ``1``); an
  empty payload or ``clear`` removes the override. The plant is not affected.
- ``<prefix>/register/<field>`` with an integer sets a pump register as if the pump
  had changed it (``heating_mode`` ``0`` switches to compensation mode).
- ``<prefix>/house/extra_heat_w`` with a number (W) adds heat from a source the
  controller does not know (a wood stove: ``6000``); ``0``, an empty payload or
  ``clear`` removes it. Unlike the ``main`` overrides this changes the plant: the heat
  goes into the house's air node, and the room with the sensor (where the stove
  stands) warms faster than the house (``stove_zone_k_per_kw``, see
  :class:`BoardConfig`). The pump's ``Room_Thermostat_Temp`` follows the house.
- ``<prefix>/clear`` removes every override (the extra heat included).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Final

import numpy as np

from climate_manager_capture.heishamon import (
    COMMAND_QUEUE_MAX,
    DUMP_INTERVAL_S,
    QUERY_INTERVAL_S,
    Cadence,
    command_name,
)
from ovenbird_core.control.config import RoomSensorProfile
from ovenbird_sim.evaluate.sensors import RoomSensorDevice, RoomSensorModel
from ovenbird_sim.heishamon.registers import Command, Registers, register_names
from ovenbird_sim.heishamon.weather import Weather, local_hour
from ovenbird_sim.model import Observation, PlantParams, PlantState, initial_state, step

DEFAULT_BASE: Final = "panasonic_heat_pump"
DEFAULT_ROOM_TOPIC: Final = "climate_manager_capture/room_temp"
DEFAULT_HUMIDITY_TOPIC: Final = "climate_manager_capture/room_humidity"
PERIODIC_ROOM_STEP_K: Final = 0.1
DEFROST_PUMP_DUTY: Final = 220
THERMOSTAT_OFFSET_K: Final = 0.0
THERMOSTAT_NOISE_K: Final = 0.1
THERMOSTAT_SAMPLE_S: Final = 60.0
THERMOSTAT_SEED_OFFSET: Final = 7919
PREROLL_STEP_S: Final = 60.0
PREROLL_ROOM_GAIN: Final = 4.0
PREROLL_SETPOINT_RANGE: Final = (20, 45)
MAX_EXTRA_HEAT_W: Final = 30_000.0
STATIC_TOPICS: Final = {
    "Heatpump_State": "1",
    "Error": "No error",
    "Room_Heater_State": "0",
    "Internal_Heater_State": "0",
    "External_Heater_State": "0",
    "Zones_State": "0",
    "Z1_Sensor_Settings": "0",
    "Buffer_Installed": "0",
    "DHW_Installed": "0",
    "Force_DHW_State": "0",
    "Holiday_Mode_State": "0",
    "Quiet_Mode_Priority": "0",
    "Powerful_Mode_Time": "0",
    "Heating_Control": "0",
    "Heater_On_Outdoor_Temp": "-5",
}


@dataclass(frozen=True, slots=True)
class Publication:
    """One MQTT publish.

    Parameters
    ----------
    topic
        Full topic.
    payload
        Text payload.
    retain
        Retained flag.
    """

    topic: str
    payload: str
    retain: bool


@dataclass(frozen=True, slots=True)
class BoardConfig:
    """Behaviour of the simulated board.

    Parameters
    ----------
    base
        HeishaMon ``mqtt_topic_base``.
    query_interval_s
        Seconds between pump queries.
    dump_interval_s
        Seconds between full dumps.
    target_lag_cycles
        Query cycles between a setpoint register change and the water target.
    room_topic
        Topic of the simulated room temperature; ``None`` disables it.
    room_interval_s
        Seconds between room temperature publications of the default periodic sensor.
    room_sensor
        Room sensor device model; ``None`` is the periodic sensor (0.1 K, re-sent
        every ``room_interval_s``).
    humidity_topic
        Topic of the companion humidity (needs a ``room_sensor`` with a humidity
        model); ``None`` disables it.
    room_seed
        Seed of the room sensor's noise and humidity.
    utc_offset_h
        Fixed offset of the local clock (internal gains, synthetic sun).
    inject_prefix
        Topic prefix of the fault injection interface; ``None`` disables it.
    thermostat_offset_k
        ``Room_Thermostat_Temp`` minus the air temperature (the recording's median);
        ``None`` does not publish the thermostat.
    thermostat_noise_k
        Standard deviation of the thermostat's noise before rounding.
    stove_zone_k_per_kw
        Steady excess of the sensor's room over the house air per kW of extra heat:
        the plant is one air node for the house while a stove heats one room. 0.6 K/kW
        puts the stove room about 3.5 K above the rest of the house under a 6 kW stove,
        the order of a recorded stove evening.
    stove_zone_tau_s
        Time constant of that excess (it builds up and fades with it).
    """

    base: str = DEFAULT_BASE
    query_interval_s: float = QUERY_INTERVAL_S
    dump_interval_s: float = DUMP_INTERVAL_S
    target_lag_cycles: int = 1
    room_topic: str | None = DEFAULT_ROOM_TOPIC
    room_interval_s: float = 60.0
    room_sensor: RoomSensorModel | None = None
    humidity_topic: str | None = None
    room_seed: int = 0
    utc_offset_h: float = 1.0
    inject_prefix: str | None = None
    thermostat_offset_k: float | None = THERMOSTAT_OFFSET_K
    thermostat_noise_k: float = THERMOSTAT_NOISE_K
    stove_zone_k_per_kw: float = 0.6
    stove_zone_tau_s: float = 2700.0

    def room_model(self) -> RoomSensorModel:
        """Return the room sensor model in effect."""
        if self.room_sensor is not None:
            return self.room_sensor
        return RoomSensorModel(
            step_k=PERIODIC_ROOM_STEP_K,
            confirm_s=self.room_interval_s,
            sample_s=self.room_interval_s,
            profile=RoomSensorProfile(report_interval_s=self.room_interval_s),
        )


@dataclass
class BoardStats:
    """Counters of the board.

    Parameters
    ----------
    commands_received, commands_applied, commands_ignored, commands_dropped
        Command counters (ignored: unknown names; dropped: queue full).
    applied
        Applied commands per name.
    injections, injections_rejected
        Accepted and rejected fault injections.
    """

    commands_received: int = 0
    commands_applied: int = 0
    commands_ignored: int = 0
    commands_dropped: int = 0
    applied: dict[str, int] = field(default_factory=dict)
    injections: int = 0
    injections_rejected: int = 0


class SimulatedHeishaMon:
    """HeishaMon + pump + house, advanced in query cycles.

    Parameters
    ----------
    params
        Plant parameters.
    weather
        Exogenous inputs.
    start
        Simulated wall time of the first cycle's start (timezone-aware).
    registers
        Initial pump registers.
    config
        Board behaviour.
    state
        Initial plant state; :func:`preroll` builds a settled one.
    """

    def __init__(
        self,
        params: PlantParams,
        weather: Weather,
        start: datetime,
        *,
        registers: Registers | None = None,
        config: BoardConfig | None = None,
        state: PlantState | None = None,
    ) -> None:
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        self.params = params
        self.weather = weather
        self.start = start
        self.config = config or BoardConfig()
        self.registers = registers or Registers()
        self.state = state or initial_state(params, 20.0)
        self.cycles = 0
        self.stats = BoardStats()
        self.observation: Observation | None = None
        self._queue: deque[tuple[Command, str]] = deque()
        self._cadence = Cadence(
            lambda: self.elapsed_s,
            query_interval=self.config.query_interval_s,
            dump_interval=self.config.dump_interval_s,
        )
        outside = self.weather.at(start.timestamp(), self._hour(start.timestamp())).outside_c
        target = self.registers.water_target(outside)
        self._target = target
        self._pending: deque[tuple[int, int]] = deque()
        self.room_device = RoomSensorDevice(self.config.room_model(), self.config.room_seed)
        self._room_rng = np.random.default_rng(self.config.room_seed)
        self._thermostat_rng = np.random.default_rng(self.config.room_seed + THERMOSTAT_SEED_OFFSET)
        self._thermostat: int | None = None
        self._thermostat_at: float | None = None
        self.overrides: dict[str, str] = {}
        self.dhw = False
        self.silenced: set[str] = set()
        self.extra_heat_w = 0.0
        self.stove_zone_k = 0.0

    @property
    def elapsed_s(self) -> float:
        """Simulated seconds since ``start``."""
        return self.cycles * self.config.query_interval_s

    @property
    def now(self) -> datetime:
        """Simulated wall time."""
        return self.start + timedelta(seconds=self.elapsed_s)

    @property
    def room_c(self) -> float:
        """Temperature of the room with the sensor: the house air plus the stove's excess."""
        return self.state.t_air + self.stove_zone_k

    def _stove_zone(self, dt: float) -> None:
        """Relax the stove-driven zone offset (K) towards its target."""
        wanted = self.config.stove_zone_k_per_kw * self.extra_heat_w / 1000.0
        tau = self.config.stove_zone_tau_s
        share = 1.0 if tau <= 0.0 else 1.0 - math.exp(-dt / tau)
        self.stove_zone_k += (wanted - self.stove_zone_k) * share
        if abs(self.stove_zone_k) < 1e-6:
            self.stove_zone_k = 0.0

    @property
    def water_target(self) -> int:
        """Water target in effect (what the plant follows)."""
        return self._target

    def _hour(self, unix_s: float) -> float:
        """Return the local hour of day at Unix time ``unix_s``."""
        return local_hour(unix_s, self.config.utc_offset_h)

    def _topic(self, suffix: str) -> str:
        """Return the full topic for ``suffix`` under the configured base topic."""
        return f"{self.config.base}/{suffix}"

    def reboot(self) -> None:
        """Restart the firmware: uptime from zero and a full dump on the next cycle.

        The pump, its registers and pending commands are not affected.
        """
        self._cadence = Cadence(
            lambda: self.elapsed_s,
            query_interval=self.config.query_interval_s,
            dump_interval=self.config.dump_interval_s,
        )

    def will(self) -> Publication:
        """Return the last will HeishaMon registers: ``LWT`` ``Offline``, retained."""
        will = self._cadence.will()
        return Publication(self._topic(will.suffix), will.payload, will.retain)

    @property
    def command_filter(self) -> str:
        """Topic filter of the commands this board listens to."""
        return self._topic("commands/#")

    @property
    def inject_filter(self) -> str | None:
        """Topic filter of the fault injection interface, if enabled."""
        prefix = self.config.inject_prefix
        return None if prefix is None else f"{prefix}/#"

    def inject(self, name: str, payload: str) -> bool:
        """Apply one fault injection (see the module docstring).

        Parameters
        ----------
        name
            Topic below the injection prefix (``main/Pump_Flow``, ``register/heating_mode``
            or ``clear``).
        payload
            Value text.

        Returns
        -------
        bool
            ``True`` when applied; ``False`` for an unknown name or a bad value.
        """
        text = payload.strip()
        kind, _, target = name.partition("/")
        accepted = False
        if name == "clear":
            self.overrides.clear()
            self.extra_heat_w = 0.0
            accepted = True
        elif name == "house/extra_heat_w":
            heat = 0.0 if text in ("", "clear") else _watts(text)
            if heat is not None:
                self.extra_heat_w = heat
                accepted = True
        elif kind == "main" and target and "/" not in target:
            if text in ("", "clear"):
                self.overrides.pop(target, None)
            else:
                self.overrides[target] = text
            accepted = True
        elif kind == "register" and target in register_names():
            try:
                value = int(text)
            except ValueError:
                value = None
            if value is not None:
                self.registers = replace(self.registers, **{target: value})
                accepted = True
        if accepted:
            self.stats.injections += 1
        else:
            self.stats.injections_rejected += 1
        return accepted

    def receive(self, topic: str, payload: bytes | str) -> bool:
        """Queue a command delivered on ``topic`` (or apply a fault injection).

        Parameters
        ----------
        topic
            Full topic; only ``<base>/commands/<name>`` is considered.
        payload
            Raw payload.

        Returns
        -------
        bool
            ``True`` when queued for the next cycle (or the injection was applied);
            ``False`` when it is not a command of this board, unknown, or the queue
            is full.
        """
        prefix = self.config.inject_prefix
        if prefix is not None and topic.startswith(f"{prefix}/"):
            text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
            return self.inject(topic.removeprefix(f"{prefix}/"), text)
        if not topic.startswith(self._topic("commands/")):
            return False
        name = command_name(topic)
        self.stats.commands_received += 1
        try:
            command = Command(name or "")
        except ValueError:
            self.stats.commands_ignored += 1
            return False
        if len(self._queue) >= COMMAND_QUEUE_MAX:
            self.stats.commands_dropped += 1
            return False
        text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
        self._queue.append((command, text))
        return True

    def _execute_queue(self) -> None:
        """Apply the queued commands to the registers and count them."""
        while self._queue:
            command, payload = self._queue.popleft()
            self.registers = self.registers.apply(command, payload)
            self.stats.commands_applied += 1
            self.stats.applied[command.value] = self.stats.applied.get(command.value, 0) + 1

    def _advance_target(self, outside_sensor: float) -> None:
        """Advance the delayed water target: queue a change and release those whose lag passed."""
        wanted = self.registers.water_target(outside_sensor)
        lag = max(self.config.target_lag_cycles, 0)
        latest = self._pending[-1][1] if self._pending else self._target
        if wanted != latest:
            self._pending.append((self.cycles + lag, wanted))
        while self._pending and self._pending[0][0] <= self.cycles:
            self._target = self._pending.popleft()[1]

    def cycle(self) -> list[Publication]:
        """Advance one query interval and return what goes out on MQTT.

        Returns
        -------
        list of Publication
            ``main/*`` changes (or the full dump), ``stats``, ``LWT`` and the room
            sensor's reports (temperature, humidity).
        """
        dt = self.config.query_interval_s
        begin = self.start.timestamp() + self.elapsed_s
        exogenous = self.weather.at(begin, self._hour(begin))
        if self.extra_heat_w > 0.0:
            exogenous = replace(exogenous, extra_heat_w=exogenous.extra_heat_w + self.extra_heat_w)
        self.state, observation = step(self.state, self.params, self._target, exogenous, dt)
        self._stove_zone(dt)
        if self.stove_zone_k != 0.0:
            observation = replace(observation, room_temp=round(self.room_c, 1))
        self.observation = observation
        self.cycles += 1
        self._execute_queue()
        self._advance_target(observation.outside_temp)
        observation = replace(observation, target_temp=self._target)
        for name, payload in self._main_topics(observation).items():
            self._cadence.set(f"main/{name}", payload)
        muted = {f"main/{name}" for name in self.silenced}
        out = [
            Publication(self._topic(e.suffix), e.payload, e.retain)
            for e in self._cadence.tick(self.elapsed_s)
            if e.suffix not in muted
        ]
        out.extend(self._room())
        return out

    def _main_topics(self, observation: Observation) -> dict[str, str]:
        """Return the main topics as published: static, observed, register-derived, overrides."""
        topics = dict(STATIC_TOPICS)
        topics.update(observation.main_topics())
        topics.update(self.registers.topics())
        topics["Pump_Duty"] = str(self._pump_duty())
        topics["Operations_Counter"] = str(self.state.starts)
        if self.dhw:
            topics["ThreeWay_Valve_State"] = "1"
        thermostat = self._room_thermostat()
        if thermostat is not None:
            topics["Room_Thermostat_Temp"] = str(thermostat)
        topics.update(self.overrides)
        return topics

    def _pump_duty(self) -> int:
        """Return the pump duty reported: zero when idle, the defrost duty when defrosting."""
        if not self.state.running:
            return 0
        if self.state.defrosting:
            return DEFROST_PUMP_DUTY
        return self.registers.max_pump_duty

    def _room_thermostat(self) -> int | None:
        """Return the thermostat reading (whole degrees) or ``None`` when not configured."""
        offset = self.config.thermostat_offset_k
        if offset is None:
            return None
        t = self.elapsed_s
        if self._thermostat_at is None or t - self._thermostat_at >= THERMOSTAT_SAMPLE_S - 1e-9:
            draw = float(self._thermostat_rng.standard_normal())
            noisy = self.state.t_air + offset + self.config.thermostat_noise_k * draw
            self._thermostat = math.floor(noisy + 0.5)
            self._thermostat_at = t
        return self._thermostat

    def _room(self) -> list[Publication]:
        """Return the room sensor publications due now (temperature, humidity), if any."""
        topic = self.config.room_topic
        if topic is None:
            return []
        out: list[Publication] = []
        t = self.start.timestamp() + self.elapsed_s
        device = self.room_device
        if device.sampled_at is None or t - device.sampled_at >= device.model.sample_s - 1e-9:
            draw = float(self._room_rng.standard_normal())
            value = device.temperature(t, self.room_c, draw)
            if value is not None:
                out.append(Publication(topic, f"{value:.1f}", True))
            humidity_topic = self.config.humidity_topic
            humidity = device.humidity(t) if humidity_topic is not None else None
            if humidity_topic is not None and humidity is not None:
                out.append(Publication(humidity_topic, f"{humidity:.0f}", True))
        return out


def preroll(
    params: PlantParams,
    weather: Weather,
    start: datetime,
    setpoint: int,
    *,
    room_c: float = 20.5,
    hours: float = 48.0,
    utc_offset_h: float = 1.0,
    room_gain_k_per_k: float = PREROLL_ROOM_GAIN,
) -> PlantState:
    """Settle the plant before ``start`` around a room temperature.

    The setpoint is ``setpoint`` plus ``room_gain_k_per_k`` times the room error,
    rounded and clamped to :data:`PREROLL_SETPOINT_RANGE`, so the house arrives at
    ``start`` close to ``room_c`` with its mass and loop in a matching state. The
    setpoint of the last step is in the returned state's ``last_setpoint``.

    Parameters
    ----------
    params
        Plant parameters.
    weather
        Exogenous inputs (evaluated over the hours before ``start``).
    start
        Start of the simulation.
    setpoint
        Base water setpoint (typically a heating curve at the start).
    room_c
        Room temperature to settle at; the mass starts 1 K and the water 3 K above it.
    hours
        Pre-roll duration.
    utc_offset_h
        Local clock offset.
    room_gain_k_per_k
        Setpoint change per K of room error; 0 holds ``setpoint``.

    Returns
    -------
    PlantState
        State at ``start`` with counters reset.
    """
    state = initial_state(params, room_c, t_mass=room_c + 1.0, t_water=room_c + 3.0)
    steps = max(0, math.ceil(hours * 3600.0 / PREROLL_STEP_S))
    t = start.timestamp() - steps * PREROLL_STEP_S
    low, high = PREROLL_SETPOINT_RANGE
    for _ in range(steps):
        exogenous = weather.at(t, local_hour(t, utc_offset_h))
        wanted = setpoint + room_gain_k_per_k * (room_c - state.t_air)
        applied = min(max(math.floor(wanted + 0.5), low), high)
        state, _ = step(state, params, float(applied), exogenous, PREROLL_STEP_S)
        t += PREROLL_STEP_S
    return replace(state, starts=0, defrosts=0, heat_j=0.0, elec_j=0.0, time_s=0.0)


def _watts(text: str) -> float | None:
    """Parse ``text`` as extra heat in W, or ``None`` when not finite or out of range."""
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and 0.0 <= value <= MAX_EXTRA_HEAT_W else None
