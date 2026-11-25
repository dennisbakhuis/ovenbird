"""Downsample a live capture to the JSON the overview page embeds.

Usage: ``uv run python capture/tools/overview_data.py capture/captures/live out.json``
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

from climate_manager_capture.capture import CaptureReader
from climate_manager_capture.capture_info import analyse

TZ = timezone(timedelta(hours=2))
BASE = "panasonic_heat_pump/main/"
STEP = 300
MEAN_KEYS = {"hz", "heat_w", "cons_w", "outlet", "inlet"}
KEYS = {
    "Outside_Temp": "outside",
    "Main_Outlet_Temp": "outlet",
    "Main_Inlet_Temp": "inlet",
    "Main_Target_Temp": "target",
    "Compressor_Freq": "hz",
    "Heat_Power_Production": "heat_w",
    "Heat_Power_Consumption": "cons_w",
    "Pump_Duty": "duty",
    "Defrosting_State": "defrost",
    "DHW_Temp": "dhw",
    "ThreeWay_Valve_State": "valve",
}
RESPONSE_TOPIC = {
    "SetCurves": "Z1_Water_Target_Temp",
    "SetMaxPumpDuty": "Pump_Duty",
    "SetZ1HeatRequestTemperature": "Z1_Heat_Request_Temp",
    "SetHeatpump": "Heatpump_State",
    "SetOperationMode": "Operating_Mode_State",
}


def _day(t: float) -> str:
    return datetime.fromtimestamp(t, TZ).strftime("%Y-%m-%d")


def build(capture: Path) -> dict[str, Any]:
    """Read every record once and derive series, runs, daily totals and health."""
    reader = CaptureReader(capture)
    records = list(reader.iter_records())
    lo, hi = records[0].t, records[-1].t
    t0 = int(lo // STEP * STEP)
    buckets: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    room: list[list[float]] = []
    commands: list[dict[str, Any]] = []
    errors: list[list[Any]] = []
    raw: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for rec in records:
        if rec.topic == "climate_manager_capture/room_temp":
            room.append([rec.t, float(rec.payload)])
            continue
        if "/commands/" in rec.topic:
            name = rec.topic.rsplit("/", 1)[1]
            commands.append({"t": rec.t, "name": name, "payload": rec.payload})
            continue
        if not rec.topic.startswith(BASE):
            continue
        suffix = rec.topic[len(BASE) :]
        if suffix == "Error":
            if not errors or errors[-1][1] != rec.payload:
                errors.append([rec.t, rec.payload])
            continue
        if suffix in RESPONSE_TOPIC.values():
            raw[suffix].append((rec.t, float(rec.payload)))
        key = KEYS.get(suffix)
        if key is not None:
            buckets[int((rec.t - t0) // STEP)][key].append(float(rec.payload))

    for cmd in commands:
        cmd["response"] = None
        topic = RESPONSE_TOPIC.get(cmd["name"])
        if topic is None:
            continue
        before = [v for t, v in raw[topic] if t <= cmd["t"]]
        prev = before[-1] if before else None
        for t, v in raw[topic]:
            if cmd["t"] < t <= cmd["t"] + 30 and v != prev:
                cmd["response"] = {"topic": topic, "value": v, "latency": round(t - cmd["t"], 1)}
                break

    series: list[dict[str, float | None]] = []
    carry: dict[str, float] = {}
    for i in range(int((hi - t0) // STEP) + 1):
        row: dict[str, float | None] = {"t": t0 + i * STEP}
        b = buckets.get(i, {})
        for key in KEYS.values():
            if b.get(key):
                carry[key] = sum(b[key]) / len(b[key]) if key in MEAN_KEYS else b[key][-1]
            row[key] = carry.get(key)
        series.append(row)

    runs: list[dict[str, Any]] = []
    start_i: int | None = None
    tail: dict[str, float | None] = {"hz": 0.0, "t": hi}
    for i, row in enumerate([*series, tail]):
        on = (row["hz"] or 0) > 0
        if on and start_i is None:
            start_i = i
        elif not on and start_i is not None:
            part = series[start_i:i]
            steady = part[1:] if len(part) > 2 else part
            runs.append(
                {
                    "start": part[0]["t"],
                    "end": row["t"],
                    "minutes": len(part) * STEP / 60,
                    "max_hz": max(p["hz"] or 0 for p in part),
                    "max_outlet": max(p["outlet"] or 0 for p in part),
                    "outside": part[0]["outside"],
                    "heat_wh": sum((p["heat_w"] or 0) for p in steady) * STEP / 3600,
                    "cons_wh": sum((p["cons_w"] or 0) for p in steady) * STEP / 3600,
                }
            )
            start_i = None

    daily: dict[str, dict[str, float]] = {}
    for row in series:
        d = daily.setdefault(
            _day(float(row["t"] or 0)),
            {"out_min": 99, "out_max": -99, "heat_wh": 0, "cons_wh": 0, "run_min": 0, "runs": 0},
        )
        if row["outside"] is not None:
            d["out_min"] = min(d["out_min"], row["outside"])
            d["out_max"] = max(d["out_max"], row["outside"])
        d["heat_wh"] += (row["heat_w"] or 0) * STEP / 3600
        d["cons_wh"] += (row["cons_w"] or 0) * STEP / 3600
        if (row["hz"] or 0) > 0:
            d["run_min"] += STEP / 60
    for run in runs:
        daily[_day(run["start"])]["runs"] += 1

    report = analyse(reader)
    health = {
        "files": report.files,
        "bytes": report.bytes,
        "gaps": report.gap_count,
        "bursts": report.retained_bursts,
        "online_cadence": report.online_cadence_s,
        "dump_interval": report.dump_interval_s,
        "topics": len(report.topics),
        "main_topics": sum(1 for t in report.topics if t.startswith(BASE)),
        "lwt": report.lwt_transitions,
        "problems": report.problems,
    }
    pairs = list(pairwise(series))
    defrosts = sum(1 for a, b in pairs if (a["defrost"] or 0) == 0 and (b["defrost"] or 0) > 0)
    dhw = sum(1 for a, b in pairs if (a["valve"] or 0) == 0 and (b["valve"] or 0) > 0)
    return {
        "generated": datetime.now(UTC).timestamp(),
        "start": lo,
        "end": hi,
        "records": len(records),
        "series": series,
        "room": room,
        "commands": commands,
        "runs": runs,
        "daily": daily,
        "health": health,
        "errors": errors,
        "defrosts": defrosts,
        "dhw_runs": dhw,
    }


def main(argv: list[str]) -> int:
    """CLI entry point."""
    capture, out = Path(argv[0]), Path(argv[1])
    data = build(capture)
    out.write_text(json.dumps(data))
    keys = ("records", "runs", "daily", "health", "errors", "defrosts", "dhw_runs")
    summary = {k: data[k] for k in keys}
    print(json.dumps(summary, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
