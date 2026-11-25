"""CLI: ``python -m ovenbird_sim.learn --history <db> --config <json> --models <dir>``.

Refits the house model (building and, when the history allows, the heat pump) on
the service's history, compares it with the current champion on the latest
held-out days, writes ``house-<date>.json`` and ``insight-<date>.json`` and points
``current.json`` at the new model when it is not worse. Never changes the control
configuration: the curve proposal becomes a draft only when the owner asks for it
in the UI. Exit code 0 for ``promoted``, ``kept_champion`` and ``learning``, 1 for
a failed run.

``--every-h`` keeps the process running and repeats the run (the optional
``learner`` container); the first run starts after ``--delay-s``.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from ovenbird_sim.data.historydb import load_config
from ovenbird_sim.data.weather import load_weather
from ovenbird_sim.learn.run import LearnOptions, learn

LOGGER = logging.getLogger("ovenbird_sim.learn")


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_sim.learn", description=__doc__)
    parser.add_argument("--history", type=Path, required=True, help="history.snapshot.db")
    parser.add_argument("--config", type=Path, required=True, help="effective configuration JSON")
    parser.add_argument("--models", type=Path, required=True, help="models directory")
    parser.add_argument("--floor-area", type=float, help="heated floor area in m2")
    parser.add_argument("--weather-dir", type=Path, help="Open-Meteo cache instead of forecasts")
    parser.add_argument("--fit-days", type=float, default=60.0)
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument("--folds", type=int, default=2)
    parser.add_argument("--bootstrap", type=int, default=20)
    parser.add_argument("--signature-bootstrap", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--tolerance-k", type=float, default=0.0)
    parser.add_argument(
        "--building-only", action="store_true", help="skip the heat-pump identification"
    )
    parser.add_argument("--every-h", type=float, help="repeat every this many hours")
    parser.add_argument("--delay-s", type=float, default=0.0, help="wait before the first run")
    parser.add_argument("--log-level", default="INFO")
    return parser


def run_once(args: argparse.Namespace) -> dict[str, object]:
    """Load the configuration and run the learner once."""
    options = LearnOptions(
        floor_area_m2=args.floor_area,
        fit_days=args.fit_days,
        test_days=args.test_days,
        folds=args.folds,
        bootstrap=args.bootstrap,
        signature_replicates=args.signature_bootstrap,
        seed=args.seed,
        tolerance_k=args.tolerance_k,
        weather=load_weather(args.weather_dir) if args.weather_dir else None,
        full_plant=not args.building_only,
        interval_h=args.every_h,
    )
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        LOGGER.error("cannot read the configuration %s: %s", args.config, exc)
        return {"outcome": "failed", "error": f"configuration: {exc}"}
    return learn(args.history, config, args.models, options)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if args.delay_s > 0:
        time.sleep(args.delay_s)
    while True:
        status = run_once(args)
        print(json.dumps(status, indent=2, default=str))
        if args.every_h is None:
            return 1 if status.get("outcome") == "failed" else 0
        LOGGER.info("next run in %.1f h", args.every_h)
        time.sleep(args.every_h * 3600.0)


if __name__ == "__main__":
    raise SystemExit(main())
