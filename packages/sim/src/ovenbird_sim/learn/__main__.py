"""CLI: ``python -m ovenbird_sim.learn --history <db> --config <json> --models <dir>``.

Refits the house model (building and, when the history allows, the heat pump) on
the service's history, compares it with the current champion on the latest
held-out days, writes ``house-<date>.json`` and ``insight-<date>.json`` and points
``current.json`` at the new model when it is not worse. Never changes the control
configuration: the curve proposal becomes a draft only when the owner asks for it
in the UI. Exit code 0 for ``promoted``, ``kept_champion`` and ``learning``, 1 for
a failed run.

The configuration's ``house_*`` settings add the owner's facts, bounds, learning
options and left-out days (:mod:`ovenbird_sim.learn.priors`); ``--fit-days``,
``--test-days`` and ``--tolerance-k`` win over ``house_learn_fit_days``,
``house_learn_test_days`` and ``house_learn_tolerance_k`` when given, and the
defaults (60, 14, 0) apply when neither is set.

``--low-priority <cpu-seconds>`` lowers the process's own scheduling priority, caps its
CPU time and makes the kernel pick it first when memory runs out; it is applied before
numpy and scipy are imported. A run holds an exclusive lock on ``<models>/.learner.lock``;
when another learner has it the process exits with 75 and changes nothing.

``--every-h`` keeps the process running and repeats the run (the optional
``learner`` container); the first run starts after ``--delay-s``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Final

from ovenbird_sim.learn import models as store

if TYPE_CHECKING:
    from ovenbird_sim.learn.run import LearnOptions

RESOURCE: ModuleType | None = None
try:
    import resource

    RESOURCE = resource
except ImportError:
    pass

LOGGER = logging.getLogger("ovenbird_sim.learn")
NICE: Final = 15
CPU_GRACE_S: Final = 60
OOM_SCORE_ADJ: Final = "/proc/self/oom_score_adj"
BUSY_EXIT: Final = 75


def apply_low_priority(cpu_seconds: int) -> None:
    """Lower the priority, cap the CPU time and volunteer for the OOM killer (best effort)."""
    with contextlib.suppress(OSError, AttributeError):
        os.nice(NICE)
    if RESOURCE is not None and cpu_seconds > 0:
        with contextlib.suppress(OSError, ValueError):
            RESOURCE.setrlimit(RESOURCE.RLIMIT_CPU, (cpu_seconds, cpu_seconds + CPU_GRACE_S))
    with contextlib.suppress(OSError), open(OOM_SCORE_ADJ, "w", encoding="ascii") as handle:
        handle.write("1000")


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_sim.learn", description=__doc__)
    parser.add_argument("--history", type=Path, required=True, help="history.snapshot.db")
    parser.add_argument("--config", type=Path, required=True, help="effective configuration JSON")
    parser.add_argument("--models", type=Path, required=True, help="models directory")
    parser.add_argument("--floor-area", type=float, help="heated floor area in m2")
    parser.add_argument("--weather-dir", type=Path, help="Open-Meteo cache instead of forecasts")
    parser.add_argument(
        "--fit-days", type=float, help="days of history to fit (default: configuration, else 60)"
    )
    parser.add_argument(
        "--test-days", type=int, help="held-out days (default: configuration, else 14)"
    )
    parser.add_argument("--folds", type=int, default=2)
    parser.add_argument("--bootstrap", type=int, default=20)
    parser.add_argument("--signature-bootstrap", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--tolerance-k",
        type=float,
        help="promotion tolerance in K (default: configuration, else 0)",
    )
    parser.add_argument(
        "--building-only", action="store_true", help="skip the heat-pump identification"
    )
    parser.add_argument("--every-h", type=float, help="repeat every this many hours")
    parser.add_argument("--delay-s", type=float, default=0.0, help="wait before the first run")
    parser.add_argument(
        "--low-priority",
        type=int,
        metavar="CPU_SECONDS",
        help="lower the priority and cap the CPU time at this many seconds",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def options_from_args(args: argparse.Namespace) -> LearnOptions:
    """Learner options from the command line; flags given explicitly win over the configuration."""
    from ovenbird_sim.data.weather import load_weather
    from ovenbird_sim.learn.run import DEFAULT_LEARN, LearnOptions

    given = {
        name: getattr(args, name)
        for name in ("fit_days", "test_days", "tolerance_k")
        if getattr(args, name) is not None
    }
    return LearnOptions(
        floor_area_m2=args.floor_area,
        fit_days=given.get("fit_days", DEFAULT_LEARN.fit_days),
        test_days=given.get("test_days", DEFAULT_LEARN.test_days),
        folds=args.folds,
        bootstrap=args.bootstrap,
        signature_replicates=args.signature_bootstrap,
        seed=args.seed,
        tolerance_k=given.get("tolerance_k", DEFAULT_LEARN.tolerance_k),
        weather=load_weather(args.weather_dir) if args.weather_dir else None,
        full_plant=not args.building_only,
        interval_h=args.every_h,
        explicit=frozenset(given),
    )


def run_once(args: argparse.Namespace) -> dict[str, object]:
    """Load the configuration and run the learner once."""
    from ovenbird_sim.data.historydb import load_config
    from ovenbird_sim.learn.run import learn

    options = options_from_args(args)
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        LOGGER.error("cannot read the configuration %s: %s", args.config, exc)
        return {"outcome": "failed", "error": f"configuration: {exc}"}
    return learn(args.history, config, args.models, options)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    args = build_parser().parse_args(argv)
    if args.low_priority is not None:
        apply_low_priority(args.low_priority)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if args.delay_s > 0:
        time.sleep(args.delay_s)
    while True:
        with store.learner_lock(args.models) as held:
            if not held:
                print("another learner is running", file=sys.stderr)
                return BUSY_EXIT
            status = run_once(args)
            store.prune(args.models)
        print(json.dumps(status, indent=2, default=str))
        if args.every_h is None:
            return 1 if status.get("outcome") == "failed" else 0
        LOGGER.info("next run in %.1f h", args.every_h)
        time.sleep(args.every_h * 3600.0)


if __name__ == "__main__":
    raise SystemExit(main())
