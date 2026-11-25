"""CLI: ``python -m ovenbird_sim.sensorcheck --datalake <root> --entity <id>``.

Reads the sensor's recorded Home Assistant states from the Datalake (hive-partitioned
parquet, ``states/entity_id=<id>/year=YYYY/month=MM/*.parquet``) and proposes a room
sensor profile with the ``OVENBIRD_CONTROL_ROOM_*`` settings. ``--liveness`` names a
sibling entity of the same device (e.g. its humidity) whose reports prove it alive.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ovenbird_sim.data import datalake as dl
from ovenbird_sim.sensorcheck.check import Proposal, SensorStats, analyse, propose

NOTE = (
    "The Datalake holds state changes only: a heartbeat that re-sends an unchanged value "
    "is invisible here. If HA's last_reported of the entity advances while its value stays "
    "the same, the sensor has a heartbeat: use periodic with that interval."
)


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_sim.sensorcheck", description=__doc__)
    parser.add_argument("--datalake", type=Path, required=True, help="Datalake root")
    parser.add_argument("--entity", required=True, help="room temperature entity id")
    parser.add_argument("--liveness", help="sibling entity of the same device (humidity)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    return parser


def to_json(stats: SensorStats, proposal: Proposal) -> dict[str, Any]:
    """Return the result as a JSON-friendly mapping."""
    gaps = {
        "sensor": {
            "p50_s": stats.gaps.p50,
            "p90_s": stats.gaps.p90,
            "p99_s": stats.gaps.p99,
            "max_s": stats.gaps.max,
        }
    }
    if stats.combined is not None:
        gaps["with_liveness"] = {
            "p50_s": stats.combined.p50,
            "p90_s": stats.combined.p90,
            "p99_s": stats.combined.p99,
            "max_s": stats.combined.max,
        }
    return {
        "entity": stats.entity,
        "liveness": stats.liveness,
        "states": stats.states,
        "days": stats.days,
        "unavailable": stats.unavailable,
        "step_k": stats.step_k,
        "step_share": stats.step_share,
        "grid_offset_k": stats.grid_offset_k,
        "changes_per_day": stats.changes_per_day,
        "reversal_share": stats.reversal_share,
        "gaps": gaps,
        "proposal": {
            "profile": proposal.profile,
            "step_k": proposal.step_k,
            "report_interval_s": proposal.report_interval_s,
            "silence_limit_s": proposal.silence_limit_s,
            "liveness": list(proposal.liveness),
            "coverage": proposal.coverage,
            "reasons": list(proposal.reasons),
            "settings": proposal.settings(f"ha/{stats.entity}"),
        },
        "note": NOTE,
    }


def render(stats: SensorStats, proposal: Proposal) -> str:
    """Return the result as text."""
    lines = [
        f"{stats.entity}: {stats.states} states over {stats.days:.1f} days, "
        f"{stats.unavailable} unavailable",
        f"proposed profile: {proposal.profile}",
        *(f"  - {reason}" for reason in proposal.reasons),
        "settings:",
        *(f"  {k}={v}" for k, v in proposal.settings(f"ha/{stats.entity}").items()),
        f"note: {NOTE}",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check; returns the exit code."""
    args = build_parser().parse_args(argv)
    states = dl.load_state(args.datalake, args.entity)
    if not len(states):
        print(f"no states of {args.entity} under {args.datalake}", file=sys.stderr)
        return 1
    liveness = dl.load_state(args.datalake, args.liveness) if args.liveness else None
    stats = analyse(states, args.entity, liveness, args.liveness)
    proposal = propose(stats)
    if args.json:
        print(json.dumps(to_json(stats, proposal), indent=2))
    else:
        print(render(stats, proposal))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
