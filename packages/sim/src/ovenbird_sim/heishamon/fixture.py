r"""Synthetic two-hour capture: the simulated HeishaMon in closed loop with ovenbird.

The committed test fixture ``packages/core/tests/fixtures/synthetic/2026-01-06.jsonl.gz``
stands in for a slice of a live recording. It has the recording's shape (a header,
then one record per MQTT message with millisecond receipt times, HeishaMon
``main/*`` on-change plus the 300 s dump, ``stats`` and ``LWT`` every 5 s, the
mirrored room sensor, ``1wire`` and ``s0`` side topics, and ``SetCurves`` /
``SetMaxPumpDuty`` commands) but no recorded data: the plant is the built-in example
house, the weather the synthetic cold week, the room sensor the modelled
send-on-delta device, and the commands come from ovenbird's own controller
(:class:`~ovenbird_core.control.OvenbirdController`, the ``mixed`` preset with the
example comfort and pump duties) in closed loop with the board. The controller
steps every 60 s on a :class:`~ovenbird_core.store.StateStore` fed with every
record so far, as the service does; a setpoint or duty intent that differs from the
pump's reported value and from the last one sent is published as a command.

Examples
--------
Regenerate the committed fixture (byte-identical for the same code)::

    uv run python -m ovenbird_sim.heishamon.fixture \\
        --out packages/core/tests/fixtures/synthetic/2026-01-06.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from climate_manager_capture.capture import Record
from ovenbird_core.capture import capture_input
from ovenbird_core.control import (
    EmitterType,
    OvenbirdConfig,
    OvenbirdController,
    PumpDutyConfig,
    RoomSensorProfile,
    default_curve,
)
from ovenbird_core.control.observe import pump_actual, room_input
from ovenbird_core.control.ovenbird import OvenbirdState
from ovenbird_core.control.types import ControlInputs, IntentKind, Mode
from ovenbird_core.heishamon import MqttMessage
from ovenbird_core.inputs import InputRouter, MqttSignal
from ovenbird_core.instant import Instant
from ovenbird_core.store import StalenessPolicy, StateStore
from ovenbird_sim import local
from ovenbird_sim.evaluate.recorded import MIRROR_SIGNAL, MIRROR_TOPIC, ROOM_RANGE_C
from ovenbird_sim.evaluate.sensors import example_profile, example_room_sensor
from ovenbird_sim.heishamon.board import BoardConfig, Publication, SimulatedHeishaMon, preroll
from ovenbird_sim.heishamon.reference import REFERENCE_PARAMS
from ovenbird_sim.heishamon.registers import Registers
from ovenbird_sim.heishamon.weather import ColdWeek, local_hour
from ovenbird_sim.model.plant import Observation

FIXTURE: Final = Path("packages/core/tests/fixtures/synthetic/2026-01-06.jsonl.gz")
WEEK_START: Final = datetime(2026, 1, 5, tzinfo=UTC)
START: Final = WEEK_START + timedelta(days=1, hours=11, minutes=50)
HOURS: Final = 2.0
WARMUP_S: Final = 2000.0
UTC_OFFSET_H: Final = 1.0
BASE: Final = "panasonic_heat_pump"
COMMAND_PREFIX: Final = f"{BASE}/commands/"
TICK_S: Final = 60.0
COMMANDS: Final = {
    IntentKind.WATER_SETPOINT: "SetCurves",
    IntentKind.MAX_PUMP_DUTY: "SetMaxPumpDuty",
}
RECEIPT_DELAY_S: Final = 0.041
RECEIPT_SPREAD_S: Final = 0.002
COMMAND_DELAY_S: Final = 0.013
ONE_WIRE_EVERY_S: Final = 20.0
S0_EVERY_S: Final = 60.0
ONE_WIRE: Final = ("28ff00000000a001", "28ff00000000a002")
S0_PORTS: Final = (1, 2)
MODEL: Final = "C2 D3 0B 33 65 B2 D3 0B 94 65"
OPERATIONS_HOURS: Final = 18_420
STATIC_EXTRA: Final = {
    "Heat_Pump_Model": MODEL,
    "DHW_Power_Production": "0",
    "DHW_Power_Consumption": "0",
    "Heater_Delay_Time": "30",
    "Heater_Start_Delta": "-5",
    "Heater_Stop_Delta": "3",
}
UNCATALOGUED: Final = {
    "Sterilization_State": "0",
    "Sterilization_Temp": "65",
    "Sterilization_Max_Time": "5",
    "DHW_Temp": "-78",
    "DHW_Target_Temp": "48",
    "DHW_Heat_Delta": "-8",
    "DHW_Heater_State": "0",
    "Fan2_Motor_Speed": "0",
    "High_Pressure": "0",
    "Low_Pressure": "0",
    "Water_Pressure": "1.4",
    "Buffer_Temp": "-78",
    "Solar_Temp": "-78",
    "Pool_Temp": "-78",
    "Z1_Temp": "-78",
    "Z2_Temp": "-78",
    "Z1_Water_Temp": "-78",
    "Z2_Water_Temp": "-78",
    "Second_Inlet_Temp": "-78",
    "Economizer_Outlet_Temp": "-78",
    "Second_Room_Thermostat_Temp": "-78",
    "Bypass_Outlet_Temp": "-78",
    "Ipm_Temp": "0",
    "Expansion_Valve": "0",
    "Cooling_Mode": "0",
    "Cool_Delta": "5",
    "Cool_Power_Production": "0",
    "Cool_Power_Consumption": "0",
    "Heat_To_Cool_Temp": "0",
    "Cool_To_Heat_Temp": "0",
    "Z1_Cool_Request_Temp": "0",
    "Z2_Cool_Request_Temp": "0",
    "Z2_Heat_Request_Temp": "0",
    "Z2_Water_Target_Temp": "0",
    "Z2_Sensor_Settings": "0",
    "Z1_Pump_State": "0",
    "Z2_Pump_State": "0",
    "Z1_Valve_PID": "0",
    "Z2_Valve_PID": "0",
    "TwoWay_Valve_State": "0",
    "ThreeWay_Valve_State2": "0",
    "Bivalent_Control": "0",
    "Bivalent_Mode": "0",
    "Bivalent_Start_Temp": "-5",
    "Anti_Freeze_Mode": "0",
    "Optional_PCB": "0",
    "External_Control": "0",
    "External_Heat_Cool_Control": "0",
    "External_Error_Signal": "0",
    "External_Compressor_Control": "0",
    "External_Pad_Heater": "0",
    "Alt_External_Sensor": "0",
    "Force_Heater_State": "0",
    "Main_Schedule_State": "0",
    "Quiet_Mode_Schedule": "0",
    "Liquid_Type": "0",
    "Smart_DHW": "0",
    "Solar_Mode": "0",
    "Room_Holiday_Shift_Temp": "0",
    "DHW_Holiday_Shift_Temp": "0",
    "Room_Heater_Operations_Hours": "0",
    "DHW_Heater_Operations_Hours": "0",
}


@dataclass
class _Side:
    """Deterministic ``1wire`` and ``s0`` side topics (not used by the controller)."""

    watthours: dict[int, int] = field(default_factory=lambda: dict.fromkeys(S0_PORTS, 0))
    next_one_wire: float = -math.inf
    next_s0: float = -math.inf

    def publications(self, t: float, observation: Observation) -> list[Publication]:
        """Return the side topics HeishaMon publishes at ``t``."""
        out: list[Publication] = []
        if t >= self.next_one_wire:
            self.next_one_wire = t + ONE_WIRE_EVERY_S
            temperatures = (observation.outlet_temp, observation.inlet_temp)
            for sensor, value in zip(ONE_WIRE, temperatures, strict=True):
                out.append(Publication(f"{BASE}/1wire/{sensor}", f"{value:.2f}", False))
                out.append(Publication(f"{BASE}/1wire/{sensor}/alias", sensor[-4:], False))
        if t >= self.next_s0:
            self.next_s0 = t + S0_EVERY_S
            for port in S0_PORTS:
                watts = round(observation.elec_w) if port == 1 else 0
                hour_share = round(watts * S0_EVERY_S / 3600.0)
                self.watthours[port] += hour_share
                out.append(Publication(f"{BASE}/s0/Watt/{port}", str(watts), False))
                out.append(Publication(f"{BASE}/s0/Watthour/{port}", str(hour_share), False))
                total = str(self.watthours[port])
                out.append(Publication(f"{BASE}/s0/WatthourTotal/{port}", total, False))
        return out


def side_main(observation: Observation, elapsed_s: float) -> dict[str, str]:
    """Return the ``main/*`` values the plant model does not produce, derived from it.

    Refrigerant temperatures, compressor current, pump speed and the operating hours
    follow the modelled outlet, outside temperature, power and flow; the rest is
    static, plus a few topics the catalogue does not know (ignored as uncatalogued).
    """
    running = observation.compressor_freq > 0
    outside = observation.outside_temp
    outlet = observation.outlet_temp
    values = {**STATIC_EXTRA, **UNCATALOGUED}
    values.update(
        {
            "Main_Hex_Outlet_Temp": str(round(outlet)),
            "Discharge_Temp": str(round(outlet + 25) if running else outside + 4),
            "Defrost_Temp": str(outside - 6 if running else outside),
            "Outside_Pipe_Temp": str(outside - 5 if running else outside),
            "Inside_Pipe_Temp": str(round(outlet + 3) if running else round(outlet)),
            "Eva_Outlet_Temp": str(outside - 7 if running else outside),
            "Compressor_Current": f"{observation.elec_w / 230.0:.1f}" if running else "0.0",
            "Pump_Speed": str(round(observation.pump_flow * 120)),
            "Fan1_Motor_Speed": str(observation.compressor_freq * 13 if running else 0),
            "Operations_Hours": str(OPERATIONS_HOURS + int(elapsed_s // 3600)),
        }
    )
    return values


def command_payload(kind: IntentKind, value: int) -> str:
    """Return the HeishaMon command payload carrying ``value`` for ``kind``."""
    if kind is IntentKind.WATER_SETPOINT:
        return json.dumps({"zone1": {"heat": {"target": {"high": value}}}}, separators=(",", ":"))
    return str(value)


def room_profile() -> RoomSensorProfile:
    """Return the fixture's room sensor profile: the example's, without a liveness signal."""
    return example_profile(liveness=())


def controller() -> OvenbirdController:
    """Return the controller of the fixture: the ``mixed`` preset with the example values."""
    duty = PumpDutyConfig(heat=local.EXAMPLE_PUMP_DUTY_HEAT, idle=local.EXAMPLE_PUMP_DUTY_IDLE)
    config = OvenbirdConfig.preset(
        "mixed", comfort_room_c=local.EXAMPLE_COMFORT_C, pump_duty=duty, room=room_profile()
    )
    return OvenbirdController(config)


@dataclass(slots=True)
class Driver:
    """Ovenbird stepping every :data:`TICK_S` on what the board published so far.

    Parameters
    ----------
    control
        The controller.
    """

    control: OvenbirdController = field(default_factory=controller)
    store: StateStore = field(init=False)
    router: InputRouter = field(init=False)
    state: OvenbirdState = field(init=False)
    next_tick: float | None = None
    sent: dict[IntentKind, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Build the store, the router and the controller state."""
        profile = room_profile()
        self.store = StateStore(profile.policy(StalenessPolicy(), MIRROR_SIGNAL))
        signal = MqttSignal(MIRROR_SIGNAL, "°C", *ROOM_RANGE_C)
        self.router = InputRouter(mqtt_signals={MIRROR_TOPIC: signal})
        self.state = self.control.initial_state()

    def feed(self, record: Record) -> None:
        """Apply one published record to the store."""
        converted = capture_input(record)
        if isinstance(converted, MqttMessage):
            self.store.apply(self.router.route(converted))
        else:
            self.store.apply(converted)
        if self.next_tick is None:
            self.next_tick = math.ceil(record.t / TICK_S) * TICK_S

    def until(self, t: float) -> list[tuple[float, str, str]]:
        """Run every tick up to ``t``; return the commands as ``(time, topic, payload)``."""
        out: list[tuple[float, str, str]] = []
        while self.next_tick is not None and self.next_tick <= t:
            out += self._tick(self.next_tick)
            self.next_tick += TICK_S
        return out

    def _tick(self, t: float) -> list[tuple[float, str, str]]:
        now = Instant.from_unix(t)
        snapshot = self.store.snapshot(now)
        actual = pump_actual(snapshot)
        inputs = ControlInputs(
            now=now,
            snapshot=snapshot,
            room=room_input(snapshot, MIRROR_SIGNAL, room_profile()),
            plan=None,
            mode=Mode.AUTO,
            override=None,
            actual=actual,
        )
        result = self.control.step(self.state, inputs)
        self.state = result.state
        reported = {
            IntentKind.WATER_SETPOINT: actual.water_target,
            IntentKind.MAX_PUMP_DUTY: actual.max_pump_duty,
        }
        out = []
        for kind, name in COMMANDS.items():
            intent = result.intent(kind)
            if intent is None or intent.value == self.sent.get(kind):
                continue
            current = reported[kind]
            if current is not None and current.value == intent.value:
                continue
            self.sent[kind] = intent.value
            out.append((t, COMMAND_PREFIX + name, command_payload(kind, intent.value)))
        return out


def board(start: datetime = START) -> SimulatedHeishaMon:
    """Return the board of the fixture: example house, cold week, modelled room sensor."""
    weather = ColdWeek(WEEK_START)
    outside = weather.at(start.timestamp(), local_hour(start.timestamp(), UTC_OFFSET_H))
    setpoint = math.floor(default_curve(EmitterType.MIXED).water(outside.outside_c) + 0.5)
    state = preroll(REFERENCE_PARAMS, weather, start, setpoint, utc_offset_h=UTC_OFFSET_H)
    if state.last_setpoint is not None:
        setpoint = math.floor(state.last_setpoint + 0.5)
    registers = replace(Registers(), direct_setpoint=setpoint, curve_target_high=setpoint)
    config = BoardConfig(
        base=BASE,
        room_topic=MIRROR_TOPIC,
        room_sensor=example_room_sensor(),
        utc_offset_h=UTC_OFFSET_H,
    )
    return SimulatedHeishaMon(
        REFERENCE_PARAMS, weather, start, registers=registers, config=config, state=state
    )


def generate(start: datetime = START, hours: float = HOURS) -> list[Record]:
    """Run the closed loop and return the records of ``hours`` from ``start`` in order.

    The board and the controller run :data:`WARMUP_S` before ``start``, so the slice
    begins mid-stream as a cut from a long recording does: between two full dumps,
    with only the changed ``main/*`` values until the next dump.
    """
    driver = Driver()
    pump = board(start - timedelta(seconds=WARMUP_S))
    origin = pump.start.timestamp()
    side = _Side()
    records: list[Record] = []
    pending: list[Record] = []
    end = start.timestamp() + hours * 3600.0

    def feed(record: Record) -> None:
        records.append(record)
        driver.feed(record)

    def send(commands: Sequence[tuple[float, str, str]]) -> None:
        for t, topic, payload in commands:
            pending.append(Record(round(t + COMMAND_DELAY_S, 3), topic, payload))
            pump.receive(topic, payload)

    while True:
        if pump.observation is not None:
            pump.overrides.update(side_main(pump.observation, pump.elapsed_s))
        publications = pump.cycle()
        t = origin + pump.elapsed_s
        if t > end:
            break
        if pump.observation is not None:
            publications += side.publications(t, pump.observation)
        stamped = [
            Record(round(t + RECEIPT_DELAY_S + i * RECEIPT_SPREAD_S, 3), p.topic, p.payload)
            for i, p in enumerate(publications)
        ]
        while pending and pending[0].t <= stamped[0].t:
            records.append(pending.pop(0))
        for record in stamped:
            send(driver.until(record.t))
            while pending and pending[0].t <= record.t:
                records.append(pending.pop(0))
            feed(record)
        send(driver.until(t + 5.0 - 1e-3))
    records.extend(pending)
    first = start.timestamp()
    return sorted((r for r in records if first <= r.t <= end), key=lambda r: r.t)


def header(start: datetime = START, hours: float = HOURS) -> str:
    """Return the capture header line."""
    return json.dumps(
        {
            "v": 1,
            "name": "synthetic",
            "broker": "simulated",
            "filters": [f"{BASE}/#", "climate_manager_capture/#"],
            "started": start.isoformat(),
            "note": (
                f"synthetic {hours:g} h: example house, cold week, ovenbird in closed loop "
                "(python -m ovenbird_sim.heishamon.fixture)"
            ),
        },
        separators=(",", ":"),
    )


def write(path: Path, start: datetime = START, hours: float = HOURS) -> int:
    """Write the fixture to ``path`` (gzipped without a timestamp); return the record count."""
    records = generate(start, hours)
    text = "\n".join([header(start, hours), *(r.to_json() for r in records)]) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw, gzip.GzipFile("", "wb", 9, raw, mtime=0) as packed:
        packed.write(text.encode())
    return len(records)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the synthetic fixture."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_sim.heishamon.fixture")
    parser.add_argument("--out", type=Path, default=FIXTURE)
    parser.add_argument("--start", type=datetime.fromisoformat, default=START)
    parser.add_argument("--hours", type=float, default=HOURS)
    args = parser.parse_args(argv)
    count = write(args.out, args.start, args.hours)
    print(f"wrote {args.out} ({count} records)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
