"""CLI: ``python -m ovenbird_sim.evaluate open-loop ...`` and ``... dayshift ...``.

``open-loop`` drives ovenbird through a recorded capture (open loop, nothing is sent)
and writes ``openloop.sqlite`` plus ``openloop_summary.json``.

``dayshift`` evaluates the sun day shift on the simulated plant (paired closed-loop
runs over weather replicas, see :mod:`ovenbird_sim.evaluate.dayshift`) and writes
``dayshift.json`` plus ``dayshift_tables.md``; ``--quick`` is the two-scenario smoke
run the tests use.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

from ovenbird_core.control.config import OvenbirdConfig, PumpDutyConfig, RoomSensorProfile
from ovenbird_core.control.ovenbird import OvenbirdController
from ovenbird_core.store import HA_MAX_AGE_S
from ovenbird_sim import local
from ovenbird_sim.evaluate import dayshift_run
from ovenbird_sim.evaluate.openloop import (
    OpenLoopOptions,
    open_loop_run,
    render_stove,
    stove_option,
)
from ovenbird_sim.evaluate.recorded import RoomSource
from ovenbird_sim.evaluate.report import render_open_loop

EXAMPLE_DUTY: Final = PumpDutyConfig(
    heat=local.EXAMPLE_PUMP_DUTY_HEAT, idle=local.EXAMPLE_PUMP_DUTY_IDLE
)
SECONDS_PER_DAY: Final = 86400.0


def _day_start(day: date) -> float:
    """Return the UTC midnight of ``day`` in unix seconds."""
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()


def _install_min_setpoint() -> float | None:
    """Return the local ``MIN_SETPOINT_C``, or ``None`` when not set."""
    configured = local.value("MIN_SETPOINT_C", "")
    return float(configured) if configured else None


def ovenbird_config(
    comfort_c: float,
    min_setpoint_c: float | None = None,
    pump_duty: PumpDutyConfig | None = None,
    emitter: str = "mixed",
    room: RoomSensorProfile | None = None,
) -> OvenbirdConfig:
    """Return the preset with the given room target, minimum setpoint and pump duty.

    Built the way the service builds it (``controller_config``): the preset with the
    comfort target, pump duty and room sensor profile, then only the safety minimum
    replaced.

    Parameters
    ----------
    comfort_c
        Comfort room temperature target (degC).
    min_setpoint_c
        Safety minimum of the water setpoint (degC); ``None`` keeps the preset's.
    pump_duty
        Pump duty configuration; ``None`` keeps the preset's.
    emitter
        Emitter preset name, e.g. ``"mixed"``.
    room
        Room sensor profile; ``None`` uses the default profile.

    Returns
    -------
    OvenbirdConfig
        The controller configuration.
    """
    config = OvenbirdConfig.preset(
        emitter, comfort_room_c=comfort_c, pump_duty=pump_duty, room=room or RoomSensorProfile()
    )
    if min_setpoint_c is None:
        return config
    return replace(config, safety=replace(config.safety, min_setpoint_c=min_setpoint_c))


def _profile_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the ovenbird profile arguments (emitter, minimum setpoint, pump duty)."""
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
    """Return the pump duty of the arguments, or ``None`` with ``--no-pump-duty``."""
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

    shift = sub.add_parser("dayshift", help="paired evaluation of the sun day shift")
    shift.add_argument("--out", type=Path, required=True)
    shift.add_argument("--quick", action="store_true", help="two scenarios, short runs")
    shift.add_argument("--replicas", type=int, help="replicas per scenario")
    shift.add_argument("--workers", type=int, help="worker processes")
    shift.add_argument("--seed", type=int, default=0)
    shift.add_argument("--scenario", action="append", help="only these scenarios")
    shift.add_argument(
        "--setting",
        action="append",
        metavar="NAME=VALUE[,NAME=VALUE]",
        help="evaluate this setting instead of the sweep (boost_k, setback_k, recovery_h)",
    )

    return parser


def _span(args: argparse.Namespace, tick_s: float) -> tuple[float | None, float | None]:
    """Return the first and last tick of the ``--from``/``--to`` days (``None``: open)."""
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


def run_dayshift(args: argparse.Namespace) -> int:
    """Run the ``dayshift`` command; the status is 0 once the outputs are written.

    Parameters
    ----------
    args
        Parsed command-line arguments of the ``dayshift`` subcommand.

    Returns
    -------
    int
        Process exit status.
    """
    options = (
        dayshift_run.Options.quick(args.workers)
        if args.quick
        else dayshift_run.Options(workers=args.workers)
    )
    if args.replicas is not None:
        options = replace(options, replicas=args.replicas)
    if args.scenario:
        options = replace(options, scenarios=tuple(args.scenario))
    if args.setting:
        sweep = tuple(dayshift_run.parse_setting(text.split(",")) for text in args.setting)
        options = replace(options, sweep=sweep)
    options = replace(options, seed=args.seed)

    def progress(done: int, total: int) -> None:
        """Print every tenth of the runs."""
        if done == total or done % max(1, total // 10) == 0:
            print(f"{done}/{total} runs", flush=True)

    evaluation = dayshift_run.evaluate(options, progress)
    recommendation = dayshift_run.recommend(evaluation)
    document, tables = dayshift_run.write_outputs(args.out, evaluation, recommendation)
    for line in dayshift_run.summary(evaluation, recommendation):
        print(line)
    print(f"runtime {evaluation.runtime_s:.0f} s; wrote {document} and {tables}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    args = build_parser().parse_args(argv)
    if args.command == "dayshift":
        return run_dayshift(args)
    return run_dry(args)


if __name__ == "__main__":
    raise SystemExit(main())
