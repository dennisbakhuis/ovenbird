"""Check a running simulated dev stack through ovenbird's API (localhost only).

Usage::

    uv run python dev/check_sim.py [--url http://127.0.0.1:8099] [--min-hours 3]
        [--from 2026-01-06T06:00:00Z] [--allow-alarm heishamon_restarted ...]

Exits 0 when decisions are recorded in auto mode under room feedback (the room input
fresh under its profile; the dev stack runs an on_change sensor), commands were
sent and verified with none failed, no alarm is active and none was raised in the
window except the allowed ones, the health check reports ready with ``alarms`` ok,
every safety monitor reports ``ok``, the room stayed near the example comfort target
(21.5 °C by default), history holds the room and water-target series and the UI index
is served. Compressor starts and defrosts in the window are reported.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from statistics import fmean
from typing import Any, Final

LOCAL_PREFIXES: Final = ("http://127.0.0.1:", "http://localhost:")
EARLIEST: Final = "2000-01-01T00:00:00Z"
LATEST: Final = "2100-01-01T00:00:00Z"
COMFORT_C: Final = 21.5


def fetch(url: str, path: str, auth: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``path`` and decode JSON (text for non-JSON responses)."""
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(  # noqa: S310
        f"{url}/{path}{query}", headers={"Authorization": f"Basic {auth}"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        body = response.read().decode("utf-8")
        if "json" in response.headers.get("Content-Type", ""):
            return json.loads(body)
        return body


def parse_iso(text: str) -> datetime:
    """Parse an API timestamp."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def transitions(points: list[list[Any]], *, threshold: float) -> int:
    """Count rises of a series from below to at or above ``threshold``."""
    count = 0
    previous: float | None = None
    for _, value in points:
        if value is None:
            continue
        if previous is not None and previous < threshold <= value:
            count += 1
        previous = value
    return count


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8099")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="ovenbird-dev")
    parser.add_argument("--min-hours", type=float, default=3.0)
    parser.add_argument("--from", dest="start", default=EARLIEST, help="window start (ISO)")
    parser.add_argument("--comfort", type=float, default=COMFORT_C)
    parser.add_argument("--band-low", type=float, default=0.7, help="K below comfort allowed")
    parser.add_argument("--band-high", type=float, default=0.7, help="K above comfort allowed")
    parser.add_argument("--mean-tolerance", type=float, default=0.3)
    parser.add_argument("--allow-alarm", action="append", default=[], help="alarm code")
    args = parser.parse_args(argv)
    if not args.url.startswith(LOCAL_PREFIXES):
        parser.error("only a local ovenbird is checked")
    auth = base64.b64encode(f"{args.user}:{args.password}".encode()).decode()
    window = {"from": args.start, "to": LATEST}

    latest = fetch(args.url, "api/v1/decisions/latest", auth)
    health = fetch(args.url, "api/v1/health", auth)
    decisions = fetch(args.url, "api/v1/decisions", auth, {**window, "limit": 5000})["decisions"]
    commands = fetch(args.url, "api/v1/commands", auth, {**window, "limit": 5000})["commands"]
    alarms = fetch(args.url, "api/v1/alarms", auth, {**window, "limit": 5000})
    if not decisions:
        print("FAIL  no decisions recorded")
        return 1
    first, last = decisions[0]["at"], decisions[-1]["at"]
    signals = (
        "room_temperature,main/Z1_Water_Target_Temp,main/Outside_Temp,main/Compressor_Freq,"
        "main/Defrosting_State"
    )
    span = {"from": first, "to": last, "signals": signals, "step": 60}
    history = fetch(args.url, "api/v1/history", auth, span)
    raw = {"from": first, "to": last, "signals": "main/Compressor_Freq,main/Defrosting_State"}
    raw_history = fetch(args.url, "api/v1/history", auth, {**raw, "step": 0})
    index = fetch(args.url, "", auth)

    control = latest["control"] or {}
    room_input = control.get("room") or {}
    adapter = control.get("adapter") or {}
    safety = control.get("safety") or {}
    hours = (parse_iso(last) - parse_iso(first)).total_seconds() / 3600.0
    ladders = Counter(d["ladder"] for d in decisions)
    statuses = Counter(c["status"] for c in commands)
    kinds = Counter(c["kind"] for c in commands if c["status"] == "verified")
    series = history["series"]
    rooms = [v for _, v in series["room_temperature"]["points"] if v is not None]
    targets = [v for _, v in series["main/Z1_Water_Target_Temp"]["points"] if v]
    raw_series = raw_history["series"]
    starts = transitions(raw_series["main/Compressor_Freq"]["points"], threshold=1.0)
    defrosts = transitions(raw_series["main/Defrosting_State"]["points"], threshold=1.0)
    controlled = [d for d in decisions if d["ladder"] == "schedule_curve_feedback"]
    late = controlled[len(controlled) // 6 :]
    rooms_late = [
        ref["value"]
        for d in late
        for ref in d["record"]["inputs_used"]
        if ref["signal"] == "room_temperature"
    ]
    allowed = set(args.allow_alarm)
    raised = Counter(e["code"] for e in alarms["events"] if e["event"] == "raised")
    unexpected = {code: n for code, n in raised.items() if code not in allowed}
    active = [a["code"] for a in alarms["active"]]
    monitors = {m["code"]: m["status"] for m in safety.get("monitors", [])}
    unhealthy = {code: status for code, status in monitors.items() if status != "ok"}
    mean_late = fmean(rooms_late) if rooms_late else float("nan")

    print(f"simulated span   {first} .. {last} ({hours:.1f} h, {len(decisions)} decisions)")
    print(f"ladder           {dict(ladders)}")
    print(f"commands         {dict(statuses)}; verified by kind {dict(kinds)}")
    print(f"adapter          {adapter.get('counters')} budget {adapter.get('budget')}")
    print(f"hold             {adapter.get('hold')} until {adapter.get('hold_until')}")
    print(f"alarms raised    {dict(raised)}; active {active}")
    print(f"health           ready={health['ready']} checks={health['checks']}")
    print(f"safety monitors  level={safety.get('level')} {monitors}")
    print(f"compressor       {starts} starts, {defrosts} defrosts in the window")
    print(f"room (history)   {min(rooms):.2f} .. {max(rooms):.2f} °C over {len(rooms)} minutes")
    print(
        f"room (control)   {min(rooms_late):.2f} .. {max(rooms_late):.2f} °C, "
        f"mean {mean_late:.2f} °C after warm-up (target {args.comfort:.1f} °C)"
    )
    print(f"water target     {min(targets):.0f} .. {max(targets):.0f} °C")
    print(
        f"room input       profile {room_input.get('profile')} fresh {room_input.get('fresh')} "
        f"held {room_input.get('held_s')} s alive {room_input.get('alive_s')} s "
        f"(by {room_input.get('alive_by') or 'own report'}) link {room_input.get('link_up')}"
    )
    print(f"latest note      {latest['decision']['note']}")

    low, high = args.comfort - args.band_low, args.comfort + args.band_high
    checks = {
        "auto mode and publishing": control.get("mode") == "auto"
        and control.get("publishing") is True,
        f"at least {args.min_hours} h simulated": hours >= args.min_hours,
        "decisions under room feedback": len(controlled) > 0.8 * len(decisions),
        "room input fresh under its profile": room_input.get("fresh") is True,
        "commands sent and verified": statuses["sent"] > 0 and statuses["verified"] > 0,
        "no failed commands": statuses["failed"] == 0,
        "no active alarm": not [code for code in active if code not in allowed],
        "no unexpected alarm raised": not unexpected,
        "health ready, alarms ok": health["ready"] is True
        and health["checks"].get("alarms") == "ok",
        "every safety monitor ok": bool(monitors) and not unhealthy,
        f"room within [{low:.1f}, {high:.1f}] °C": all(low <= r <= high for r in rooms_late),
        f"room mean within ±{args.mean_tolerance} K": abs(mean_late - args.comfort)
        <= args.mean_tolerance,
        "history filled": len(rooms) > 60 and len(targets) > 60,
        "UI index served": isinstance(index, str) and "<" in index,
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if unexpected:
        print(f"      unexpected alarms: {unexpected}")
    if unhealthy:
        print(f"      monitors not ok: {unhealthy}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
