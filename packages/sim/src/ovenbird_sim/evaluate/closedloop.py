"""Closed loop: a controller drives the fitted plant through a synthetic HeishaMon.

Per 60 s tick ``k`` at ``t_k``:

1. the plant's readings at ``t_k`` (HeishaMon resolution: integer outside sensor and
   room thermostat with calibrated dither noise, see :mod:`.sensors`; 0.25 K loop
   sensors; integer frequency) plus the applied settings form a
   :class:`~ovenbird_core.store.Snapshot` the way HeishaMon publishes them: a value
   is (re)observed when it changes and every topic again in the full dump every
   300 s. The controller's room input is the living-room sensor as Home Assistant
   delivers it: the device's reports
   (:class:`~ovenbird_sim.evaluate.sensors.RoomSensorDevice`: send-on-delta on its
   grid with calibrated noise and hysteresis, an optional heartbeat, the recorded
   dropouts as ``unavailable``) and its liveness reports (recorded humidity times)
   are applied to a :class:`~ovenbird_core.store.StateStore` with the configured
   room profile's policy and an HA link that is always up, and read through the
   same :func:`~ovenbird_core.control.observe.room_input` as live - so freshness,
   held and alive ages follow exactly the service's rules;
2. the controller steps on that snapshot;
3. intents reach the plant by the interface's semantics: a ``water_setpoint``
   intent that differs from the applied value is written and applied for the next
   step (the controller's own dwell, deadband and de-duplication decide how often
   that happens);
4. the plant advances 60 s with the applied setpoint and the recorded weather.

``max_pump_duty`` intents are applied and counted but do not change the plant: the
model's loop flow follows the compressor state, as the duty switching did in the
recording.

:class:`RecordedSetpoints` is the controller-agnostic baseline: it writes the
recorded applied water setpoint of every tick, whatever wrote it, so the plant
driven by it can be compared with the measured room, heat and starts.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Final, Protocol

import numpy as np

from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control.observe import pump_actual, room_input
from ovenbird_core.control.planner import ForecastHour
from ovenbird_core.control.protocol import Controller, StepResult
from ovenbird_core.control.record import DecisionRecord
from ovenbird_core.control.types import (
    CommandIntent,
    ControlInputs,
    IntentKind,
    LadderLevel,
    Mode,
    PlanSlice,
    ReasonCode,
)
from ovenbird_core.instant import Instant
from ovenbird_core.readings import ParseError, ParseErrorKind, Reading, SignalId, SourceKind, Value
from ovenbird_core.store import (
    HA_MAX_AGE_S,
    HEISHAMON_MAX_AGE_S,
    HeishaMonStatus,
    SignalView,
    Snapshot,
    StalenessPolicy,
    StateStore,
)
from ovenbird_sim.data.series import FloatArray
from ovenbird_sim.evaluate.recorded import DATALAKE_SIGNAL
from ovenbird_sim.evaluate.sensors import RoomSensorDevice, RoomSensorModel, SensorModel
from ovenbird_sim.model import heatpump as hp
from ovenbird_sim.model.plant import (
    Exogenous,
    PlantParams,
    PlantState,
    loop_temperatures,
    step,
)

DUMP_S: Final = 300.0
TICK_S: Final = 60.0
LOOP_SENSOR_STEP_K: Final = 0.25
HEARTBEAT_AGE_S: Final = 2.0
ROOM_RESOLUTION_K: Final = 0.2
PLAN_EVERY_S: Final = 900.0
MODEL_PLAN_APPLIED_KEY: Final = "model_plan_applied_k"
FEEDBACK_LEVELS: Final = frozenset(
    {"schedule_curve_feedback", "model_plan", "rule_plan", "optimiser_plan"}
)


STATIC_SIGNALS: Final[Mapping[SignalId, Value]] = MappingProxyType(
    {
        HeishaSignal.THREEWAY_VALVE_STATE.value: 0,
        HeishaSignal.HEATING_MODE.value: 1,
        HeishaSignal.OPERATING_MODE_STATE.value: 0,
        HeishaSignal.HEATPUMP_STATE.value: 1,
        HeishaSignal.QUIET_MODE_LEVEL.value: 0,
        "main/Zones_State": 0,
        "main/Z1_Sensor_Settings": 0,
        "main/Sterilization_State": 0,
    }
)


@dataclass(frozen=True, slots=True)
class Weather:
    """Exogenous inputs per tick.

    Parameters
    ----------
    t0
        First tick in unix seconds.
    dt
        Tick period.
    outside_c
        True outside temperature per tick.
    ghi_w_m2
        Global horizontal irradiance per tick.
    local_hour
        Local clock hour per tick (internal-gain profile).
    rh_pct
        Outside relative humidity per tick (frost build-up; ``None``: the plant
        parameters' default).
    """

    t0: float
    dt: float
    outside_c: FloatArray
    ghi_w_m2: FloatArray
    local_hour: FloatArray
    rh_pct: FloatArray | None = None

    def humidity(self, k: int) -> float:
        """Relative humidity at tick ``k`` (``NaN`` when not supplied)."""
        return math.nan if self.rh_pct is None else float(self.rh_pct[k])

    @property
    def n(self) -> int:
        """Number of ticks."""
        return int(self.outside_c.size)

    def times(self) -> FloatArray:
        """Tick times."""
        return self.t0 + self.dt * np.arange(self.n, dtype=np.float64)


class ForecastView(Protocol):
    """What the service has stored of the weather forecast at a time."""

    def rows(self, now: Instant) -> tuple[ForecastHour, ...]:
        """Return the hourly rows the planner reads at ``now`` (past and future hours)."""
        ...


@dataclass(frozen=True, slots=True)
class PlanRequest:
    """What the service has when it asks a planner for the slice starting at ``now``.

    Parameters
    ----------
    now
        Start of the slice.
    outside_filtered_c
        The controller's filtered outside temperature.
    previous_offset_k
        Offset of the slice issued by the previous call (0 when none, or expired).
    forecast
        View of the stored forecast.
    """

    now: Instant
    outside_filtered_c: float
    previous_offset_k: float
    forecast: ForecastView


type PlanProvider = Callable[[PlanRequest], PlanSlice | None]


@dataclass(frozen=True, slots=True)
class LoopOptions:
    """Options of a closed-loop run.

    Parameters
    ----------
    initial_setpoint
        Applied water setpoint before the first tick.
    initial_duty
        Applied max pump duty before the first tick.
    room_resolution_k
        Unused (the living-room sensor is :attr:`SensorModel.room`); kept for callers.
    dump_s
        HeishaMon full-dump period.
    mode
        Mode passed to the controller.
    room_signal
        Signal id of the simulated living-room sensor.
    sensors
        Dither noise of the integer sensors.
    plan_provider
        Called every ``plan_every_s`` of simulated time with a :class:`PlanRequest`;
        the slice it returns (or none) is passed to the controller until the next call
        (the controller ignores it once expired). ``None``: no plan, as before.
    plan_forecast
        The forecast view handed to the provider.
    plan_every_s
        Period of the provider calls.
    """

    initial_setpoint: int
    initial_duty: int = 102
    room_resolution_k: float = ROOM_RESOLUTION_K
    dump_s: float = DUMP_S
    mode: Mode = Mode.AUTO
    room_signal: SignalId = DATALAKE_SIGNAL
    sensors: SensorModel = field(default_factory=SensorModel)
    plan_provider: PlanProvider | None = None
    plan_forecast: ForecastView | None = None
    plan_every_s: float = PLAN_EVERY_S


@dataclass(frozen=True, slots=True)
class Trace:
    """Per-tick outcome of a closed-loop run (plant values at the end of each step).

    Parameters
    ----------
    t
        Tick times (step starts).
    setpoint
        Applied setpoint during each step.
    room_c, outlet_c
        Room air and outlet sensor temperature at the end of each step.
    heat_w, elec_w
        Heat into the loop and electrical input during each step.
    running, defrost
        Compressor running / defrosting at the end of each step.
    start
        A heating start happened during the step.
    write
        A setpoint write happened at the tick.
    run_start, run_length_s
        Start time and length of every completed run.
    reasons
        Decision reason code per tick.
    duty_writes
        Number of ``max_pump_duty`` writes.
    final
        Plant state after the last step.
    ladder
        Ladder level per tick.
    room_fresh
        Whether the controller's room input was fresh at each tick (0/1).
    room_feedback
        Whether room feedback was active at each tick (0/1): the ladder level used
        the room (fresh and plausible).
    hz
        Compressor frequency of heating operation at the end of each step (0 when
        stopped or defrosting).
    plan_offset_k
        Room-target offset of a model plan the controller applied at each tick (0 when
        none applied).
    """

    t: FloatArray
    setpoint: FloatArray
    room_c: FloatArray
    outlet_c: FloatArray
    heat_w: FloatArray
    elec_w: FloatArray
    running: FloatArray
    defrost: FloatArray
    start: FloatArray
    write: FloatArray
    run_start: FloatArray
    run_length_s: FloatArray
    reasons: tuple[str, ...]
    duty_writes: int
    final: PlantState
    ladder: tuple[str, ...] = ()
    room_fresh: FloatArray = field(default_factory=lambda: np.zeros(0))
    room_feedback: FloatArray = field(default_factory=lambda: np.zeros(0))
    hz: FloatArray = field(default_factory=lambda: np.zeros(0))
    plan_offset_k: FloatArray = field(default_factory=lambda: np.zeros(0))


def quantise(value: float, step_k: float) -> float:
    """Round ``value`` to a multiple of ``step_k``."""
    return round(round(value / step_k) * step_k, 6)


def plant_readings(
    params: PlantParams,
    state: PlantState,
    outside_c: float,
    setpoint: int,
    duty: int,
    noise: tuple[float, float] = (0.0, 0.0),
    sensors: SensorModel | None = None,
    t: float | None = None,
) -> dict[SignalId, Value]:
    """HeishaMon ``main/*`` values implied by the plant state and the applied settings.

    Parameters
    ----------
    params
        Plant parameters.
    state
        Plant state at the tick.
    outside_c
        True outside temperature at the tick.
    setpoint, duty
        Applied water setpoint and max pump duty.
    noise
        Standard-normal draws for the outside and thermostat readings.
    sensors
        Sensor noise model (none by default).
    t
        Tick time (selects the thermostat offset of the day).

    Returns
    -------
    dict
        Value per signal id.
    """
    model = sensors or SensorModel()
    p = params.heat_pump
    inlet, outlet = loop_temperatures(params, state)
    if state.defrosting:
        hz = round(p.hz_min * 2.0)
    elif state.running:
        hz = round(state.hz)
    else:
        hz = 0
    flow = p.flow_running_lpm if state.running else p.flow_idle_lpm
    values: dict[SignalId, Value] = dict(STATIC_SIGNALS)
    values.update(
        {
            HeishaSignal.OUTSIDE_TEMP.value: hp.sensor_outside(
                p, outside_c + model.outside_noise_k * noise[0], state.running
            ),
            HeishaSignal.ROOM_THERMOSTAT_TEMP.value: round(
                state.t_air + model.thermostat_offset(t) + model.thermostat_noise_k * noise[1]
            ),
            HeishaSignal.INLET_TEMP.value: quantise(inlet, LOOP_SENSOR_STEP_K),
            HeishaSignal.OUTLET_TEMP.value: quantise(outlet, LOOP_SENSOR_STEP_K),
            HeishaSignal.COMPRESSOR_FREQ.value: hz,
            HeishaSignal.DEFROSTING_STATE.value: int(state.defrosting),
            HeishaSignal.Z1_WATER_TARGET_TEMP.value: setpoint,
            HeishaSignal.MAIN_TARGET_TEMP.value: setpoint,
            "main/Z1_Heat_Curve_Target_High_Temp": setpoint,
            HeishaSignal.MAX_PUMP_DUTY.value: duty,
            HeishaSignal.PUMP_FLOW.value: round(flow, 2),
        }
    )
    return values


@dataclass(slots=True)
class SyntheticHeishaMon:
    """Turns plant readings into snapshots with HeishaMon's publish semantics.

    Parameters
    ----------
    room_signal
        Signal id of the room sensor.
    dump_s
        Full-dump period (every topic re-observed).
    """

    room_signal: SignalId
    dump_s: float = DUMP_S
    _seen: dict[SignalId, tuple[Value, Instant]] = field(default_factory=dict)
    _next_dump: float | None = None

    def snapshot(
        self,
        t: float,
        values: Mapping[SignalId, Value],
        room: SignalView | None = None,
    ) -> Snapshot:
        """Return the snapshot at ``t`` after publishing ``values``, with the room view.

        Parameters
        ----------
        t
            Tick time.
        values
            HeishaMon readings.
        room
            View of the room sensor (from :class:`HaRoomSensor`), if any.

        Returns
        -------
        Snapshot
            The store snapshot a controller sees.
        """
        now = Instant.from_unix(t)
        dump = self._next_dump is None or t >= self._next_dump
        if dump:
            self._next_dump = (math.floor(t / self.dump_s) + 1) * self.dump_s
        views: dict[SignalId, SignalView] = {}
        for signal, value in values.items():
            seen = self._seen.get(signal)
            if dump or seen is None or seen[0] != value:
                seen = (value, now)
                self._seen[signal] = seen
            views[signal] = _view(signal, value, seen[1], now, SourceKind.HEISHAMON)
        if room is not None:
            views[self.room_signal] = room
        status = HeishaMonStatus(
            alive=True,
            heartbeat_age=HEARTBEAT_AGE_S,
            lwt_online=True,
            version="simulated",
            uptime_s=None,
        )
        return Snapshot(
            now=now,
            signals=MappingProxyType(views),
            heishamon=status,
            errors=MappingProxyType({}),
            error_counts=MappingProxyType({}),
            links=MappingProxyType({SourceKind.HA: True}),
        )


def _view(
    signal: SignalId,
    value: Value,
    observed: Instant,
    now: Instant,
    source: SourceKind,
    max_age_s: float | None = None,
) -> SignalView:
    default = HA_MAX_AGE_S if source is SourceKind.HA else HEISHAMON_MAX_AGE_S
    max_age = default if max_age_s is None else max_age_s
    age = now.monotonic - observed.monotonic
    return SignalView(
        signal=signal,
        value=value,
        unit=None,
        source=source,
        observed=observed,
        age=age,
        max_age=max_age,
        fresh=age <= max_age,
        retained=False,
        source_timestamp=None,
    )


UNAVAILABLE_REASON: Final = "unavailable: entity has no state"
UNAVAILABLE_DETAIL: Final = "entity has no state"


@dataclass(slots=True)
class HaRoomSensor:
    """The simulated living-room sensor as the service's store sees it.

    Every tick the device's reports (temperature, liveness) are applied to a
    :class:`~ovenbird_core.store.StateStore` with the configured profile's policy
    (the HA link is up), and the room view is read from it.

    Parameters
    ----------
    model
        Device model with the configured profile.
    signal
        Signal id of the room temperature.
    seed
        Seed of a modelled companion humidity.
    """

    model: RoomSensorModel
    signal: SignalId = DATALAKE_SIGNAL
    seed: int = 0
    device: RoomSensorDevice = field(init=False)
    store: StateStore = field(init=False)
    liveness_signal: SignalId | None = field(init=False)
    was_unavailable: bool = False

    def __post_init__(self) -> None:
        """Build the device and the store."""
        self.device = RoomSensorDevice(self.model, self.seed)
        profile = self.model.profile
        self.store = StateStore(profile.policy(StalenessPolicy(), self.signal))
        self.liveness_signal = profile.liveness[0] if profile.liveness else None

    def _apply(self, signal: SignalId, value: float, now: Instant, at: float) -> None:
        stamp = datetime.fromtimestamp(at, UTC)
        self.store.apply(Reading(signal, value, None, now, SourceKind.HA, source_timestamp=stamp))

    def view(self, t: float, t_air: float, draw: float) -> SignalView | None:
        """Apply the device's reports up to ``t`` and return the room view.

        Parameters
        ----------
        t
            Tick time.
        t_air
            True air temperature.
        draw
            Standard-normal draw of the measurement noise.

        Returns
        -------
        SignalView or None
            The room view (``None`` before the first report).
        """
        now = Instant.from_unix(t)
        self.store.set_link(SourceKind.HA, True, now)
        if self.model.unavailable(t):
            if not self.was_unavailable:
                self.store.apply(
                    ParseError(
                        self.signal,
                        ParseErrorKind.UNAVAILABLE,
                        "unavailable",
                        UNAVAILABLE_DETAIL,
                        now,
                    )
                )
            self.was_unavailable = True
        else:
            value = self.device.temperature(t, t_air, draw, force=self.was_unavailable)
            self.was_unavailable = False
            if value is not None:
                self._apply(self.signal, value, now, t)
        if self.liveness_signal is not None:
            alive = self.device.liveness(t) if self.model.liveness_times else None
            if alive is not None:
                self._apply(self.liveness_signal, 0.0, now, alive)
            elif not self.model.liveness_times:
                humidity = self.device.humidity(t)
                if humidity is not None:
                    self._apply(self.liveness_signal, humidity, now, t)
        return self.store.view(self.signal, now)


RECORDED_SETPOINTS: Final = "recorded_setpoints"


@dataclass(frozen=True, slots=True)
class RecordedSetpoints:
    """Controller that writes the recorded applied water setpoint of every tick.

    It drives the plant the way the house was driven, whatever wrote the setpoint, so
    a closed-loop run with it checks the plant model against the measurements
    (room temperature, heat, starts) independently of any controller.

    Parameters
    ----------
    t0
        Time of the first setpoint in unix seconds.
    dt
        Spacing of the setpoints.
    setpoints
        Recorded applied water setpoint per tick (``Z1_Water_Target_Temp``).
    name
        Controller name recorded in every decision.
    """

    t0: float
    dt: float
    setpoints: tuple[int, ...] = ()
    name: str = RECORDED_SETPOINTS

    def initial_state(self) -> None:
        """Return the (empty) state."""

    def setpoint_at(self, t: float) -> int | None:
        """Return the recorded setpoint of the tick at ``t`` (``None`` outside the record)."""
        k = round((t - self.t0) / self.dt)
        return self.setpoints[k] if 0 <= k < len(self.setpoints) else None

    def step(self, state: None, inputs: ControlInputs) -> StepResult[None]:
        """Return the recorded setpoint of the tick as the water setpoint intent."""
        setpoint = self.setpoint_at(inputs.now.wall.timestamp())
        intents = (
            ()
            if setpoint is None
            else (CommandIntent(IntentKind.WATER_SETPOINT, setpoint, ReasonCode.OVERRIDE),)
        )
        record = DecisionRecord(
            at=inputs.now,
            controller=self.name,
            mode=inputs.mode,
            ladder=LadderLevel.HOLD,
            terms=(),
            pre_round=None if setpoint is None else float(setpoint),
            setpoint=setpoint,
            binding=None,
            flip_distance=None,
            inputs_used=(),
            controller_state={},
            reason=ReasonCode.OVERRIDE if setpoint is not None else ReasonCode.INPUTS_MISSING,
            note="recorded applied water setpoint"
            if setpoint is not None
            else "no recorded setpoint at this tick",
            intents=intents,
        )
        return StepResult(state, intents, record)


def _outside_filtered(state: object) -> float | None:
    """Return the controller state's filtered outside temperature, if it has one."""
    value = getattr(state, "outside_filtered", None)
    return float(value) if isinstance(value, int | float) else None


def simulate[S](
    controller: Controller[S],
    params: PlantParams,
    weather: Weather,
    initial: PlantState,
    options: LoopOptions,
    on_step: Callable[[int, StepResult[Any]], None] | None = None,
) -> Trace:
    """Run ``controller`` against the plant over ``weather``.

    Parameters
    ----------
    controller
        Any controller.
    params
        Plant parameters.
    weather
        Exogenous inputs per tick.
    initial
        Plant state at the first tick.
    options
        Loop options.
    on_step
        Called with every step result (decision records).

    Returns
    -------
    Trace
        Per-tick outcome.
    """
    n = weather.n
    dt = weather.dt
    times = weather.times()
    cols = {
        name: np.zeros(n)
        for name in (
            "setpoint",
            "room_c",
            "outlet_c",
            "heat_w",
            "elec_w",
            "running",
            "defrost",
            "start",
            "write",
            "hz",
        )
    }
    reasons: list[str] = []
    run_start: list[float] = []
    run_length: list[float] = []
    heishamon = SyntheticHeishaMon(options.room_signal, options.dump_s)
    applied = options.initial_setpoint
    duty = options.initial_duty
    duty_writes = 0
    plant = initial
    cstate = controller.initial_state()
    current_start: float | None = None
    draws = np.random.default_rng(options.sensors.seed).standard_normal((n, 3))
    sensor = HaRoomSensor(options.sensors.room, options.room_signal, options.sensors.seed)
    profile = options.sensors.room.profile
    ladder: list[str] = []
    fresh = np.zeros(n)
    feedback = np.zeros(n)
    plan_offset = np.zeros(n)
    plan: PlanSlice | None = None
    for k in range(n):
        t = float(times[k])
        outside = float(weather.outside_c[k])
        noise = (float(draws[k, 0]), float(draws[k, 1]))
        values = plant_readings(params, plant, outside, applied, duty, noise, options.sensors, t)
        room_view = sensor.view(t, plant.t_air, float(draws[k, 2]))
        snapshot = heishamon.snapshot(t, values, room_view)
        room_in = room_input(snapshot, options.room_signal, profile)
        fresh[k] = float(room_in is not None and room_in.fresh)
        if (
            options.plan_provider is not None
            and options.plan_forecast is not None
            and t % options.plan_every_s == 0.0
        ):
            filtered = _outside_filtered(cstate)
            if filtered is not None:
                previous = (
                    plan.room_offset_k if plan is not None and plan.active(snapshot.now) else 0.0
                )
                plan = options.plan_provider(
                    PlanRequest(snapshot.now, filtered, previous, options.plan_forecast)
                )
        inputs = ControlInputs(
            now=snapshot.now,
            snapshot=snapshot,
            room=room_in,
            plan=plan,
            mode=options.mode,
            override=None,
            actual=pump_actual(snapshot),
        )
        result = controller.step(cstate, inputs)
        cstate = result.state
        if on_step is not None:
            on_step(k, result)
        reasons.append(result.decision.reason.value)
        ladder.append(result.decision.ladder.value)
        feedback[k] = float(result.decision.ladder.value in FEEDBACK_LEVELS)
        applied_offset = result.decision.controller_state.get(MODEL_PLAN_APPLIED_KEY)
        if isinstance(applied_offset, int | float):
            plan_offset[k] = float(applied_offset)
        intent = result.intent(IntentKind.WATER_SETPOINT)
        if intent is not None and intent.value != applied:
            applied = intent.value
            cols["write"][k] = 1.0
        duty_intent = result.intent(IntentKind.MAX_PUMP_DUTY)
        if duty_intent is not None and duty_intent.value != duty:
            duty = duty_intent.value
            duty_writes += 1
        exo = Exogenous(
            outside, float(weather.ghi_w_m2[k]), float(weather.local_hour[k]), weather.humidity(k)
        )
        before = plant
        plant, obs = step(plant, params, float(applied), exo, dt)
        if plant.starts > before.starts:
            cols["start"][k] = 1.0
            current_start = t
        if before.running and not plant.running:
            if current_start is not None:
                run_start.append(current_start)
                run_length.append(t + dt - current_start)
            current_start = None
        cols["setpoint"][k] = applied
        cols["room_c"][k] = plant.t_air
        cols["outlet_c"][k] = loop_temperatures(params, plant)[1]
        cols["heat_w"][k] = obs.heat_w
        cols["elec_w"][k] = obs.elec_w
        cols["running"][k] = float(plant.running)
        cols["defrost"][k] = float(plant.defrosting)
        cols["hz"][k] = plant.hz if plant.running and not plant.defrosting else 0.0
    return Trace(
        t=times,
        setpoint=cols["setpoint"],
        room_c=cols["room_c"],
        outlet_c=cols["outlet_c"],
        heat_w=cols["heat_w"],
        elec_w=cols["elec_w"],
        running=cols["running"],
        defrost=cols["defrost"],
        start=cols["start"],
        write=cols["write"],
        run_start=np.asarray(run_start, dtype=np.float64),
        run_length_s=np.asarray(run_length, dtype=np.float64),
        reasons=tuple(reasons),
        duty_writes=duty_writes,
        final=plant,
        ladder=tuple(ladder),
        room_fresh=fresh,
        room_feedback=feedback,
        hz=cols["hz"],
        plan_offset_k=plan_offset,
    )
