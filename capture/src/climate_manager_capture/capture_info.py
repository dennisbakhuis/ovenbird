"""Inspect and validate a capture: cadence, gaps, topics, commands.

The per-topic *inter-change interval* and value granularity are the evidence
for how the integration's message-count-based smoothing will behave on real
data, so they are always reported.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from .capture import CaptureReader, Record, format_duration, parse_when, topic_suffix
from .heishamon import SIDE_EFFECTS, command_name, to_int

CAPTURE_PREFIX: Final = "climate_manager_capture/"
COMMAND_MATCH_WINDOW_S: Final = 60.0
MAX_GAPS_REPORTED: Final = 100
MAX_DISTINCT_TRACKED: Final = 64
LARGE_GAP_S: Final = 3600.0


@dataclass
class TopicStats:
    """Per-topic aggregates."""

    count: int = 0
    first: float = 0.0
    last: float = 0.0
    changes: int = 0
    last_change: float = 0.0
    numeric: bool = True
    min: float | None = None
    max: float | None = None
    distinct: list[str] = field(default_factory=list)
    _last_payload: str | None = field(default=None, repr=False)

    def observe(self, record: Record) -> None:
        """Fold one record into the aggregates."""
        if self.count == 0:
            self.first = record.t
            self.last_change = record.t
        self.count += 1
        self.last = record.t
        if record.payload != self._last_payload:
            if self._last_payload is not None:
                self.changes += 1
                self.last_change = record.t
            self._last_payload = record.payload
        if len(self.distinct) < MAX_DISTINCT_TRACKED and record.payload not in self.distinct:
            self.distinct.append(record.payload)
        if self.numeric:
            try:
                value = float(record.payload)
            except ValueError:
                self.numeric = False
                self.min = self.max = None
                return
            self.min = value if self.min is None else min(self.min, value)
            self.max = value if self.max is None else max(self.max, value)

    @property
    def mean_change_interval(self) -> float | None:
        """Mean seconds between value changes, or ``None`` if it never changed."""
        if self.changes == 0:
            return None
        return (self.last_change - self.first) / self.changes


@dataclass
class CommandStats:
    """Per-command aggregates and side-effect latencies."""

    count: int = 0
    latencies: list[float] = field(default_factory=list)
    unmatched: int = 0


@dataclass
class Report:
    """Everything :func:`analyse` learned about a capture."""

    capture: str
    base: str | None
    first: float
    last: float
    records: int
    bytes: int
    files: list[str]
    gaps: list[tuple[float, float]]
    gap_count: int
    retained_bursts: int
    lwt_transitions: list[tuple[float, str]]
    online_cadence_s: float | None
    dump_interval_s: float | None
    topics: dict[str, TopicStats]
    commands: dict[str, CommandStats]
    capture_topics: dict[str, int]
    problems: list[str]

    @property
    def duration(self) -> float:
        """Seconds between the first and last record."""
        return self.last - self.first


def _detect_base(topic: str) -> str | None:
    parts = topic.split("/")
    if "main" in parts[1:-1]:
        return "/".join(parts[: parts.index("main")])
    return None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def analyse(
    reader: CaptureReader,
    *,
    start: float | None = None,
    end: float | None = None,
    gap_threshold: float = 60.0,
    base: str | None = None,
) -> Report:
    """Single-pass analysis of the records inside the window."""
    topics: dict[str, TopicStats] = defaultdict(TopicStats)
    commands: dict[str, CommandStats] = defaultdict(CommandStats)
    capture_topics: dict[str, int] = defaultdict(int)
    gaps: list[tuple[float, float]] = []
    gap_count = 0
    retained_bursts = 0
    lwt_transitions: list[tuple[float, str]] = []
    online_times: list[float] = []
    pending: dict[str, list[tuple[float, int, str]]] = defaultdict(list)
    previous: Record | None = None
    first: float | None = None
    last: float | None = None
    records = 0

    for record in reader.iter_records(start, end):
        records += 1
        first = record.t if first is None else first
        last = record.t
        if previous is not None and record.t - previous.t > gap_threshold:
            gap_count += 1
            if len(gaps) < MAX_GAPS_REPORTED:
                gaps.append((previous.t, record.t))
        if record.retained and (previous is None or not previous.retained):
            retained_bursts += 1
        previous = record

        if base is None:
            base = _detect_base(record.topic)
        topics[record.topic].observe(record)

        if record.topic.startswith(CAPTURE_PREFIX):
            capture_topics[record.topic] += 1

        suffix = topic_suffix(record.topic, base) if base else None
        if suffix == "LWT":
            if not lwt_transitions or lwt_transitions[-1][1] != record.payload:
                lwt_transitions.append((record.t, record.payload))
            if record.payload.lower() == "online":
                online_times.append(record.t)
        name = command_name(record.topic)
        if name is not None:
            stats = commands[name]
            stats.count += 1
            for effect_suffix in SIDE_EFFECTS.get(name, ()):
                pending[effect_suffix].append((record.t, to_int(record.payload), name))
        elif suffix in pending:
            still: list[tuple[float, int, str]] = []
            value = to_int(record.payload)
            for cmd_t, cmd_value, cmd_name in pending[suffix]:
                if record.t - cmd_t > COMMAND_MATCH_WINDOW_S:
                    commands[cmd_name].unmatched += 1
                elif cmd_value == value:
                    commands[cmd_name].latencies.append(record.t - cmd_t)
                else:
                    still.append((cmd_t, cmd_value, cmd_name))
            pending[suffix] = still

    for entries in pending.values():
        for _, _, cmd_name in entries:
            commands[cmd_name].unmatched += 1

    if first is None or last is None:
        raise ValueError(f"no records in window for {reader.path}")

    online_deltas = [b - a for a, b in pairwise(online_times)]
    dump_interval = _estimate_dump_interval(topics, base)
    problems: list[str] = []
    if base is None:
        problems.append("no main/* topics found (is this a HeishaMon capture?)")
    if not lwt_transitions:
        problems.append("no LWT messages found")
    if any(b - a > LARGE_GAP_S for a, b in gaps):
        problems.append(f"gap longer than {format_duration(LARGE_GAP_S)} inside the window")

    return Report(
        capture=str(reader.path),
        base=base,
        first=first,
        last=last,
        records=records,
        bytes=sum(p.stat().st_size for p in reader.files()),
        files=[p.name for p in reader.files()],
        gaps=gaps,
        gap_count=gap_count,
        retained_bursts=retained_bursts,
        lwt_transitions=lwt_transitions,
        online_cadence_s=_median(online_deltas),
        dump_interval_s=dump_interval,
        topics=dict(topics),
        commands=dict(commands),
        capture_topics=dict(capture_topics),
        problems=problems,
    )


def _estimate_dump_interval(topics: dict[str, TopicStats], base: str | None) -> float | None:
    if base is None:
        return None
    main_prefix = f"{base}/main/"
    candidates = [f"{base}/main/Heat_Pump_Model"] + [
        topic
        for topic, stats in topics.items()
        if topic.startswith(main_prefix) and stats.changes == 0 and stats.count > 3
    ]
    for topic in candidates:
        stats = topics.get(topic)
        if stats is not None and stats.count > 3 and stats.changes == 0:
            return (stats.last - stats.first) / (stats.count - 1)
    return None


def _iso(t: float) -> str:
    import time

    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def render_text(report: Report, *, top: int = 25) -> str:
    """Human-readable summary."""
    lines = [
        f"capture      {report.capture}",
        f"base         {report.base or '?'}",
        f"window       {_iso(report.first)} → {_iso(report.last)}"
        f"  ({format_duration(report.duration)})",
        f"records      {report.records:,}  bytes on disk {report.bytes:,}"
        f"  files {len(report.files)}",
        f"topics       {len(report.topics)}",
        f"gaps         {report.gap_count} (> threshold); retained bursts {report.retained_bursts}",
    ]
    for a, b in report.gaps[:10]:
        lines.append(f"  gap {_iso(a)} → {_iso(b)}  {format_duration(b - a)}")
    lines.append(
        f"LWT          transitions {len(report.lwt_transitions)}; Online cadence "
        f"{_fmt(report.online_cadence_s)} s"
    )
    for t, payload in report.lwt_transitions[:10]:
        lines.append(f"  {_iso(t)}  {payload}")
    lines.append(f"dump interval ~{_fmt(report.dump_interval_s)} s (from a constant topic)")
    if report.commands:
        lines.append("commands (recorded):")
        for name, stats in sorted(report.commands.items()):
            lines.append(
                f"  {name:32s} n={stats.count:<5d} side-effect median "
                f"{_fmt(_median(stats.latencies))} s  unmatched={stats.unmatched}"
            )
    else:
        lines.append("commands     none recorded")
    if report.capture_topics:
        lines.append("HA-side inputs (climate_manager_capture/*):")
        for topic, count in sorted(report.capture_topics.items()):
            lines.append(f"  {topic:48s} n={count}")
    else:
        lines.append("HA-side inputs  none (climate_manager_capture/* absent)")
    lines.append(f"top {top} topics by message count:")
    lines.append(f"  {'topic':52s} {'n':>7s} {'chg':>6s} {'Δchg s':>8s} {'min':>8s} {'max':>8s}")
    for topic, tstats in sorted(report.topics.items(), key=lambda kv: -kv[1].count)[:top]:
        lines.append(
            f"  {topic[:52]:52s} {tstats.count:7d} {tstats.changes:6d} "
            f"{_fmt(tstats.mean_change_interval):>8s} {_fmt(tstats.min):>8s} {_fmt(tstats.max):>8s}"
        )
    if report.problems:
        lines.append("PROBLEMS:")
        lines.extend(f"  - {p}" for p in report.problems)
    else:
        lines.append("validation   ok")
    return "\n".join(lines)


def render_catalogue(report: Report) -> str:
    """Every topic with count and sample payloads, grouped by prefix."""
    lines: list[str] = ["topic catalogue:"]
    groups: dict[str, list[str]] = defaultdict(list)
    for topic in report.topics:
        parts = topic.split("/")
        groups["/".join(parts[:2]) if len(parts) > 2 else parts[0]].append(topic)
    for prefix in sorted(groups):
        total = sum(report.topics[t].count for t in groups[prefix])
        lines.append(f"{prefix}/  ({len(groups[prefix])} topics, {total:,} msgs)")
        for topic in sorted(groups[prefix]):
            stats = report.topics[topic]
            samples = ", ".join(repr(s[:40]) for s in stats.distinct[:3])
            lines.append(f"  {topic:60s} n={stats.count:<7d} e.g. {samples}")
    return "\n".join(lines)


def to_json(report: Report) -> str:
    """JSON rendering of the report."""
    obj: dict[str, Any] = asdict(report)
    for stats in obj["topics"].values():
        stats.pop("_last_payload", None)
    return json.dumps(obj, indent=2, default=str)


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def _build_argparser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Summarise and validate a capture.")
    parser.add_argument("capture", help="captures/<name> directory.")
    parser.add_argument("--from", dest="start")
    parser.add_argument("--to", dest="end")
    parser.add_argument("--gaps", type=float, default=60.0, help="Gap threshold in seconds.")
    parser.add_argument("--base", default=None, help="Override the detected topic base.")
    parser.add_argument("--catalogue", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=25)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exit code 1 when validation found problems."""
    args = _build_argparser().parse_args(argv)
    reader = CaptureReader(Path(args.capture))
    first, _ = reader.bounds()
    start = parse_when(args.start, first) if args.start else None
    end = parse_when(args.end, first) if args.end else None
    report = analyse(reader, start=start, end=end, gap_threshold=args.gaps, base=args.base)
    if args.json:
        print(to_json(report))
    else:
        print(render_text(report, top=args.top))
        if args.catalogue:
            print()
            print(render_catalogue(report))
    return 1 if report.problems else 0


if __name__ == "__main__":
    sys.exit(main())
