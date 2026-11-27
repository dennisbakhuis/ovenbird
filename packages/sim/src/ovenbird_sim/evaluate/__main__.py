"""CLI: ``python -m ovenbird_sim.evaluate {open-loop,counterfactual,model-plan} ...``.

``open-loop`` drives ovenbird through a recorded capture (open loop, nothing is sent)
and writes ``openloop.sqlite`` plus ``openloop_summary.json``; ``counterfactual`` runs
ovenbird and the recorded setpoints on the fitted plant (closed loop) and writes
``counterfactual.sqlite`` plus ``counterfactual_summary.json``; ``model-plan`` runs the
paired planner evaluation (:mod:`ovenbird_sim.evaluate.modelplan_run`).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from ovenbird_core.control.config import PumpDutyConfig, RoomSensorProfile
from ovenbird_core.control.ovenbird import OvenbirdController
from ovenbird_core.control.types import RoomProfile
from ovenbird_core.store import HA_MAX_AGE_S
from ovenbird_sim import local
from ovenbird_sim.evaluate import modelplan, modelplan_run
from ovenbird_sim.evaluate.claims import GateBounds
from ovenbird_sim.evaluate.counterfactual import (
    ASSUMED_CONFIRM_S,
    EXAMPLE_DUTY,
    EXAMPLE_TARGET_C,
    ComfortMeasure,
    CounterfactualOptions,
    counterfactual,
    ovenbird_config,
)
from ovenbird_sim.evaluate.openloop import (
    OpenLoopOptions,
    open_loop_run,
    render_stove,
    stove_option,
)
from ovenbird_sim.evaluate.recorded import RoomSource
from ovenbird_sim.evaluate.report import render_counterfactual, render_open_loop
from ovenbird_sim.evaluate.sensors import HUMIDITY_SIGNAL

SECONDS_PER_DAY = 86400.0


def _day_start(day: date) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()


def _install_min_setpoint() -> float | None:
    """Return the local ``MIN_SETPOINT_C``, or ``None`` when not set."""
    configured = local.value("MIN_SETPOINT_C", "")
    return float(configured) if configured else None


def _profile_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--emitter", default="mixed", help="ovenbird emitter preset")
    parser.add_argument(
        "--min-setpoint",
        type=float,
        default=_install_min_setpoint(),
        help="ovenbird lowest water setpoint (default: the local MIN_SETPOINT_C, else the "
        "preset's safety minimum)",
    )
    parser.add_argument(
        "--pump-duty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="ovenbird sets the max pump duty (default: on)",
    )
    parser.add_argument("--pump-duty-heat", type=int, default=_install_duty().heat)
    parser.add_argument("--pump-duty-idle", type=int, default=_install_duty().idle)


def _install_duty() -> PumpDutyConfig:
    """Return the local ``PUMP_DUTY_HEAT``/``PUMP_DUTY_IDLE``, else the example duties."""
    heat = int(local.number("PUMP_DUTY_HEAT", EXAMPLE_DUTY.heat))
    return PumpDutyConfig(heat=heat, idle=int(local.number("PUMP_DUTY_IDLE", EXAMPLE_DUTY.idle)))


def _duty(args: argparse.Namespace) -> PumpDutyConfig | None:
    if not args.pump_duty:
        return None
    return PumpDutyConfig(heat=args.pump_duty_heat, idle=args.pump_duty_idle)


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_sim.evaluate", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    loop = sub.add_parser("open-loop", help="open loop over a recorded capture (no outcome claims)")
    loop.add_argument("--capture", type=Path, required=True, help="capture dir or day file")
    loop.add_argument("--datalake", type=Path, help="Datalake root (living-room sensor)")
    loop.add_argument("--room", choices=[r.value for r in RoomSource], default=RoomSource.AUTO)
    loop.add_argument(
        "--room-max-age",
        type=float,
        default=HA_MAX_AGE_S,
        metavar="S",
        help="room staleness limit (default: the live Home Assistant 1800 s)",
    )
    loop.add_argument(
        "--comfort",
        type=float,
        default=local.number("COMFORT_C", local.EXAMPLE_COMFORT_C),
        help="ovenbird room target (default: the local COMFORT_C, else the example)",
    )
    _profile_arguments(loop)
    loop.add_argument("--from", dest="start", type=date.fromisoformat, help="first day (UTC)")
    loop.add_argument("--to", dest="end", type=date.fromisoformat, help="last day (UTC, inclusive)")
    loop.add_argument("--no-inputs", action="store_true", help="do not store the inputs table")
    loop.add_argument("--stove", action="store_true", help="ovenbird with wood-stove mode")
    loop.add_argument("--stove-reference", help="wood-stove reference room (HA entity or signal)")
    loop.add_argument("--stove-reference-floor", type=float, help="reference floor (default 19)")
    loop.add_argument("--stove-reference-max-age", type=float, metavar="S", help="its max age")
    loop.add_argument("--out", type=Path, required=True)

    cf = sub.add_parser("counterfactual", help="closed loop on the fitted plant")
    cf.add_argument("--capture", type=Path, required=True, help="capture directory")
    cf.add_argument("--params", type=Path, required=True, help="plant_params.json")
    cf.add_argument("--datalake", type=Path, help="Datalake root (default: next to capture)")
    cf.add_argument("--weather", type=Path, help="weather cache (default: next to capture)")
    cf.add_argument("--bootstrap", type=int, default=0, metavar="N", help="parameter replicates")
    cf.add_argument("--seed", type=int, default=0)
    cf.add_argument("--workers", type=int, help="worker processes (default: CPU count)")
    cf.add_argument("--no-ablation", action="store_true")
    cf.add_argument("--no-sensor-noise", action="store_true")
    cf.add_argument(
        "--comfort",
        type=float,
        default=local.number("COMFORT_C", EXAMPLE_TARGET_C),
        help="the recorded install's room target (default: the local COMFORT_C)",
    )
    cf.add_argument("--band", type=float, default=0.5, help="comfort band below the target (K)")
    cf.add_argument("--ovenbird-target", type=float, help="ovenbird room target (default comfort)")
    cf.add_argument("--ovenbird-min-setpoint", type=float, help="ovenbird lowest water setpoint")
    cf.add_argument(
        "--pump-duty", action=argparse.BooleanOptionalAction, default=True, help="ovenbird duty"
    )
    cf.add_argument("--pump-duty-heat", type=int, default=_install_duty().heat)
    cf.add_argument("--pump-duty-idle", type=int, default=_install_duty().idle)
    cf.add_argument(
        "--calibrate-target",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="calibrate ovenbird's room target to equal comfort with the baseline",
    )
    cf.add_argument(
        "--comfort-measure",
        choices=[m.value for m in ComfortMeasure],
        default=ComfortMeasure.CHECK.value,
        help="calibrate on the whole comfort check, the tail below the baseline P10 or the mean",
    )
    cf.add_argument(
        "--room-confirm-s",
        type=float,
        default=ASSUMED_CONFIRM_S,
        help="assumed heartbeat of an unchanged room value (inf: none, as recorded)",
    )
    cf.add_argument(
        "--room-profile",
        choices=[p.value for p in RoomProfile],
        default=RoomProfile.ON_CHANGE.value,
        help="room sensor profile ovenbird is configured with (default: on_change)",
    )
    cf.add_argument("--room-step", type=float, help="room sensor step in K (profile default)")
    cf.add_argument("--room-report-interval", type=float, default=300.0, metavar="S")
    cf.add_argument("--room-silence-limit", type=float, default=86400.0, metavar="S")
    cf.add_argument(
        "--room-liveness",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="recorded humidity report times prove the room sensor alive",
    )
    cf.add_argument(
        "--room-variants",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="also run the ideal and 1800 s room sensor variants",
    )
    cf.add_argument(
        "--room-crosscheck",
        default="",
        help="plausibility cross-check signal (e.g. main/Room_Thermostat_Temp); '' disables",
    )
    cf.add_argument("--train-params", type=Path, help="train-only plant parameters")
    cf.add_argument("--no-sensitivity", action="store_true")
    cf.add_argument(
        "--no-known-events", action="store_true", help="score stove days too (no exclusion)"
    )
    cf.add_argument("--room-rmse-bound", type=float, default=GateBounds().room_rmse_k)
    cf.add_argument("--records", action="store_true", help="store the point runs' decisions")
    cf.add_argument("--from", dest="start", type=date.fromisoformat, help="first day (UTC)")
    cf.add_argument("--to", dest="end", type=date.fromisoformat, help="last day (UTC, inclusive)")
    cf.add_argument("--out", type=Path, required=True)

    plan = sub.add_parser(
        "model-plan",
        help="paired closed-loop runs with and without a planner over weather replicas",
    )
    plan.add_argument("--out", type=Path, required=True)
    plan.add_argument(
        "--planner",
        choices=tuple(modelplan.PLANNERS),
        default=modelplan_run.DEFAULT_PLANNER,
        help="planner to evaluate (none: pairing check, noise: false-alarm calibration)",
    )
    plan.add_argument(
        "--param",
        action="append",
        metavar="NAME=VALUE",
        help="planner parameter (repeatable), e.g. gain=0.3 or lead_h=3",
    )
    plan.add_argument("--replicas", type=int, help="weather replicas per cell (default 24)")
    plan.add_argument(
        "--max-replicas", type=int, help="replicas after the starts extension (default 48)"
    )
    plan.add_argument("--scenarios", nargs="+", choices=tuple(modelplan.SCENARIOS))
    plan.add_argument("--models", nargs="+", choices=tuple(modelplan.MODEL_VARIANTS))
    plan.add_argument("--days", type=int, help="simulated days per run (default 8)")
    plan.add_argument("--seed", type=int, help="base seed of the replicas (default 0)")
    plan.add_argument("--workers", type=int, help="worker processes (default: CPU count)")
    plan.add_argument(
        "--quick", action="store_true", help="2 scenarios, 2 models, 4 replicas, 3 days (tests)"
    )
    plan.add_argument(
        "--sweep", action="store_true", help="run the planner's parameter sweep instead"
    )
    plan.add_argument("--sweep-replicas", type=int, help="replicas per cell of the sweep")
    return parser


def _span(args: argparse.Namespace, tick_s: float) -> tuple[float | None, float | None]:
    start = _day_start(args.start) if args.start is not None else None
    end = _day_start(args.end) + SECONDS_PER_DAY - tick_s if args.end is not None else None
    return start, end


def run_dry(args: argparse.Namespace) -> int:
    """Run the ``open-loop`` command."""
    controller = OvenbirdController(
        ovenbird_config(args.comfort, args.min_setpoint, _duty(args), args.emitter)
    )
    start, end = _span(args, 60.0)
    options = OpenLoopOptions(
        room=RoomSource(args.room),
        room_max_age_s=args.room_max_age,
        start=start,
        end=end,
        store_inputs=not args.no_inputs,
        stove=stove_option(args.stove, args.stove_reference, args.stove_reference_floor),
        stove_reference_max_age_s=args.stove_reference_max_age,
    )
    summary = open_loop_run(
        controller, args.capture, args.out, datalake=args.datalake, options=options
    )
    print(render_open_loop(summary))
    stove = render_stove(summary)
    if stove is not None:
        print(stove)
    print(f"runtime {summary['runtime_s']:.1f} s; wrote {args.out}")
    return 0


def room_profile(args: argparse.Namespace) -> RoomSensorProfile:
    """Return the room sensor profile of the counterfactual arguments."""
    return RoomSensorProfile(
        kind=RoomProfile(args.room_profile),
        step_k=args.room_step,
        report_interval_s=args.room_report_interval,
        silence_limit_s=args.room_silence_limit,
        liveness=(HUMIDITY_SIGNAL,) if args.room_liveness else (),
        crosscheck=args.room_crosscheck or None,
    )


def run_counterfactual(args: argparse.Namespace) -> int:
    """Run the ``counterfactual`` command."""
    start, end = _span(args, 0.0)
    options = CounterfactualOptions(
        start=start,
        end=end,
        comfort_c=args.comfort,
        band_k=args.band,
        bootstrap=args.bootstrap,
        seed=args.seed,
        workers=args.workers,
        ablation=not args.no_ablation,
        gate=GateBounds(room_rmse_k=args.room_rmse_bound),
        keep_records=args.records,
        sensor_noise=not args.no_sensor_noise,
        ovenbird_target_c=args.ovenbird_target,
        ovenbird_min_setpoint_c=args.ovenbird_min_setpoint,
        pump_duty=_duty(args),
        calibrate_target=args.calibrate_target,
        comfort_measure=ComfortMeasure(args.comfort_measure),
        room_confirm_s=args.room_confirm_s,
        room_profile=room_profile(args),
        room_liveness=args.room_liveness,
        room_variants=args.room_variants,
        train_params=args.train_params,
        sensitivity=not args.no_sensitivity,
        known_events=not args.no_known_events,
    )
    summary = counterfactual(
        args.capture,
        args.params,
        args.out,
        datalake=args.datalake,
        weather=args.weather,
        options=options,
        log=lambda message: print(message, file=sys.stderr),
    )
    print(render_counterfactual(summary))
    runtime = summary["runtime_s"]
    if isinstance(runtime, dict):
        print(f"runtime {runtime['total']:.0f} s ({runtime['runs_count']} runs); wrote {args.out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    args = build_parser().parse_args(argv)
    if args.command == "open-loop":
        return run_dry(args)
    if args.command == "model-plan":
        return modelplan_run.run(args)
    return run_counterfactual(args)


if __name__ == "__main__":
    raise SystemExit(main())
