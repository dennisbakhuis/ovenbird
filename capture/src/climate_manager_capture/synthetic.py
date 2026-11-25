"""Deterministic synthetic capture built on the HeishaMon protocol model.

Used by the test suites and as a stand-in until a real capture exists::

    uv run climate-manager-capture-synthetic --out captures --name synthetic
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from .capture import CaptureWriter, Record
from .heishamon import Cadence, CommandSemantics

BASE: Final = "panasonic_heat_pump"
START: Final = datetime(2026, 1, 1, 0, 0, tzinfo=UTC).timestamp()
GAP_AT_S: Final = 600.0
GAP_LENGTH_S: Final = 90.0
NODE_RED_COMMAND_AT_S: Final = 900.0
NODE_RED_SETPOINT: Final = 36

_INITIAL: Final[dict[str, str]] = {
    "main/Heatpump_State": "1",
    "main/Operating_Mode_State": "2",
    "main/Outside_Temp": "3",
    "main/Main_Inlet_Temp": "31.5",
    "main/Main_Outlet_Temp": "36.0",
    "main/Main_Target_Temp": "36",
    "main/Room_Thermostat_Temp": "20.5",
    "main/Z1_Heat_Request_Temp": "35",
    "main/Z1_Water_Target_Temp": "35",
    "main/Heating_Mode": "1",
    "main/Compressor_Freq": "38",
    "main/Pump_Flow": "17.8",
    "main/Heat_Power_Production": "2600",
    "main/Heat_Power_Consumption": "680",
    "main/Defrosting_State": "0",
    "main/ThreeWay_Valve_State": "0",
    "main/Force_DHW_State": "0",
    "main/Sterilization_State": "0",
    "main/DHW_Temp": "47.0",
    "main/Error": "No error",
    "main/Heat_Pump_Model": "C2 D3 0B 33 65 B2 D3 0B 94 65",
    "main/Operations_Hours": "18420",
}


def build_records(*, minutes: float = 30.0, seed: int = 1) -> list[Record]:
    """Produce the synthetic capture as an in-memory list of records."""
    rng = random.Random(seed)
    clock_holder = [START]
    cadence = Cadence(lambda: clock_holder[0])
    semantics = CommandSemantics(lambda: clock_holder[0])
    state = dict(_INITIAL)
    for suffix, payload in state.items():
        cadence.set(suffix, payload)

    records: list[Record] = []
    for suffix, payload in state.items():
        records.append(Record(START, f"{BASE}/{suffix}", payload, retained=True))
    records.append(Record(START, f"{BASE}/LWT", "Offline", retained=True))
    records.append(Record(START + 60, "climate_manager_capture/room_temp", "20.4", retained=True))
    records.append(
        Record(START + 120, "climate_manager_capture/room_setpoint", "21.0", retained=True)
    )
    cadence.tick(START)

    outlet = 36.0
    end = START + minutes * 60
    t = START + 2
    command_sent = False
    while t < end:
        clock_holder[0] = t
        elapsed = t - START
        step = int((elapsed - 2) // 5)
        in_gap = GAP_AT_S <= elapsed < GAP_AT_S + GAP_LENGTH_S
        outlet = max(28.0, min(45.0, outlet + rng.uniform(-0.3, 0.3)))
        state["main/Main_Outlet_Temp"] = f"{outlet:.1f}"
        state["main/Main_Inlet_Temp"] = f"{outlet - 4.5 + rng.uniform(-0.2, 0.2):.1f}"
        state["main/Compressor_Freq"] = str(int(30 + 10 * rng.random()))
        state["main/Heat_Power_Production"] = str(int(2400 + 400 * rng.random()))
        if step > 0 and step % 120 == 0:
            state["main/Outside_Temp"] = str(int(state["main/Outside_Temp"]) - 1)
        if step > 0 and step % 60 == 0:
            state["main/Room_Thermostat_Temp"] = f"{20.5 + 0.1 * (step // 60):.1f}"
        if elapsed >= NODE_RED_COMMAND_AT_S and not command_sent:
            command_sent = True
            records.append(
                Record(
                    t,
                    f"{BASE}/commands/SetZ1HeatRequestTemperature",
                    str(NODE_RED_SETPOINT),
                )
            )
            semantics.receive("SetZ1HeatRequestTemperature", str(NODE_RED_SETPOINT))
        for effect in semantics.due(t):
            state[effect.suffix] = effect.payload
        for suffix, payload in state.items():
            cadence.set(suffix, payload)
        for emission in cadence.tick(t):
            if not in_gap:
                records.append(Record(t, f"{BASE}/{emission.suffix}", emission.payload))
        t += 5
    records.sort(key=lambda r: r.t)
    return records


def write_capture(
    directory: Path | str, name: str = "synthetic", *, minutes: float = 30.0, seed: int = 1
) -> Path:
    """Write the synthetic capture to ``directory/name`` and return that path."""
    records = build_records(minutes=minutes, seed=seed)
    writer = CaptureWriter(
        directory,
        name,
        header={"broker": "synthetic", "filters": [f"{BASE}/#", "climate_manager_capture/#"]},
        clock=lambda: START,
    )
    for record in records:
        writer.write(record)
    writer.close()
    return writer.path


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Write a synthetic HeishaMon capture.")
    parser.add_argument("--out", default="captures")
    parser.add_argument("--name", default="synthetic")
    parser.add_argument("--minutes", type=float, default=30.0)
    args = parser.parse_args(argv)
    path = write_capture(args.out, args.name, minutes=args.minutes)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
