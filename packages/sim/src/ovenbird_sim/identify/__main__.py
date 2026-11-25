"""CLI: ``python -m ovenbird_sim.identify <captures> [options]``.

Fits the plant on the recording, prints parameters with 90 % day-block bootstrap
intervals and held-out validation metrics, and writes the parameters plus the report
to ``<captures>/models/plant_params.json`` (or ``--out``) and the train-only fit to
``plant_params_train.json`` next to it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ovenbird_sim.data.events import describe as describe_events
from ovenbird_sim.data.weather import Location, fetch_weather
from ovenbird_sim.identify import io
from ovenbird_sim.identify.pipeline import (
    IdentifyOptions,
    IdentifyResult,
    describe_building,
    identify,
)


def _parse_day(text: str) -> float:
    return datetime.combine(date.fromisoformat(text), datetime.min.time(), UTC).timestamp()


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_sim.identify", description=__doc__)
    parser.add_argument("captures", type=Path, help="captures root (capture, datalake/, weather/)")
    parser.add_argument("--capture-name", default="live")
    parser.add_argument("--split", type=_parse_day, help="first test day (YYYY-MM-DD, UTC)")
    parser.add_argument("--test-days", type=int, default=14)
    parser.add_argument(
        "--folds", type=int, default=2, help="rolling-origin folds of --test-days, latest first"
    )
    parser.add_argument(
        "--to", dest="last_day", type=_parse_day, help="last day used (UTC, inclusive)"
    )
    parser.add_argument("--bootstrap", type=int, default=50, help="day-block replicates (0 = off)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out", type=Path, help="params JSON (default <captures>/models/plant_params.json)"
    )
    parser.add_argument("--fetch-weather", action="store_true", help="download Open-Meteo first")
    parser.add_argument("--lat", type=float, help="latitude for --fetch-weather")
    parser.add_argument("--lon", type=float, help="longitude for --fetch-weather")
    parser.add_argument(
        "--start", type=date.fromisoformat, help="weather start date for --fetch-weather"
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, help="weather end date for --fetch-weather"
    )
    return parser


def _defrost_line(result: IdentifyResult) -> str:
    hp = result.params.heat_pump
    frost = result.heat_pump.frost
    tail = f"{hp.defrost_duration_s / 60:.0f} min, {hp.defrost_heat_w:.0f} W from loop"
    if frost is None:
        return (
            f"  defrost rate exp({hp.defrost0:.2f} + {hp.defrost_o:.3f} T_o)/run-h below "
            f"{hp.defrost_max_outside_c:.1f} degC; {tail}"
        )
    return (
        f"  frost: coil {frost.coil0:.2f} {frost.coil_o:+.3f} T_o {frost.coil_h:+.3f} Hz "
        f"(rmse {frost.coil_rmse_k:.2f} K); {frost.driver_hpa_h:.1f} hPa h over "
        f"{frost.events} defrosts -> capacity {frost.capacity_hpa_h:.3g} hPa h; {tail}"
    )


def render(result: IdentifyResult) -> list[str]:
    """Human-readable report."""
    hp = result.params.heat_pump
    sw = result.switching
    fit = sw.start_fit
    v = result.validation_horizons
    days = result.validation_plant
    lines = ["== data coverage", *result.coverage.lines()]
    lines.append(
        f"== known events ({len(result.events)}; building-fit windows and validation days "
        "overlapping them are left out)"
    )
    lines += describe_events(result.events)
    if result.event_windows:
        lines.append(
            "  left-out fit windows: "
            + ", ".join(f"{datetime.fromtimestamp(t, UTC):%Y-%m-%d}" for t in result.event_windows)
        )
    lines += [
        "== pump start/stop rule (documented: start inlet <= SP-4, stop outlet >= SP+2 for 3 min)",
        f"  heating starts {sw.heating_starts} over {sw.days:.1f} days "
        f"({result.coverage.start:%Y-%m-%d} to {result.coverage.end:%Y-%m-%d}, "
        f"{sw.heating_starts / sw.days:.2f}/day), "
        f"defrosts {sw.defrosts}, median run {sw.run_minutes_median:.0f} min, "
        f"runs < 20 min {sw.short_run_share:.0%}",
        f"  stop: {sw.stop_rule_share:.1%} of stops after outlet >= SP+2 held "
        f"(median {sw.stop_hold_median_s:.0f} s); "
        f"{sw.overshoot_without_stop} long overshoots without stop",
        f"  start: {sw.start_doc_share:.0%} of starts at inlet <= SP-4, but "
        f"{sw.start_after_change_share:.0%} within 60 s of a setpoint change",
    ]
    if fit is not None:
        lines.append(
            f"  fitted start: on setpoint change if inlet <= SP-{fit.trigger_margin_k:.2f}; steady "
            f"if inlet <= SP-{fit.steady_margin_k:.2f} for {fit.steady_delay_s / 60:.0f} min; "
            f"min off {fit.min_off_s:.0f} s; hits +-2 min {fit.hit_rate:.0%} "
            f"(documented rule {fit.documented_hit_rate:.0%})"
        )
    c = result.heat_pump.controller
    lines += [
        "== heat pump layer (final fit, all data)",
        f"  heat = Hz ({hp.k0:.1f} + {hp.k_o:.2f} T_o + {hp.k_in:.2f} T_in "
        f"{hp.k_warmup:+.1f} exp(-t/{hp.k_warmup_tau_s:.0f} s)) {hp.q0_w:+.0f} W "
        f"(rmse {result.heat_pump.capacity_rmse_w:.0f} W)",
        f"  Hz floor {hp.hz_min:.1f}, raised to {hp.hz_min_cold:.1f} at pump outdoor reading "
        f"<= {hp.cold_floor_outside_c:.0f} degC; max {hp.hz_max:.0f}",
        f"  frequency controller: start {c.hz_start:.1f} Hz, aim SP{c.outlet_bias_k:+.2f} K "
        f"+-{c.hz_deadband_k:.2f}, gain {c.hz_gain:.2f} Hz/min/K, down {c.hz_rate_down:.2f} / up "
        f"{c.hz_rate_up:.2f} Hz/min (replay rmse {c.rmse_hz:.1f} Hz vs sd {c.std_hz:.1f})",
        f"  ln COP = {hp.cop0:.3f} + {hp.cop_o:.4f} T_o + {hp.cop_s:.4f} T_out + {hp.cop_h:.4f} Hz "
        f"{hp.cop_warmup:+.3f} exp(-t/{hp.cop_warmup_tau_s:.0f} s) "
        f"(rmse {result.heat_pump.cop_rmse_log:.3f}; pump estimate, P1 step ratio "
        f"{result.heat_pump.p1_ratio:.2f}); idle draw {hp.circulation_w:.0f} W",
        f"  start phase {hp.hz_start:.0f} Hz for {hp.start_phase_s:.0f} s, then "
        f"{hp.hz_resume0:.1f} {hp.hz_resume_o:+.2f} T_sensor Hz; return delay "
        f"{hp.return_delay_s:.0f} s",
        _defrost_line(result),
        f"  flows {hp.flow_running_lpm:.1f} / {hp.flow_idle_lpm:.1f} l/min, spread offset "
        f"{hp.spread_offset_k:.3f} K, outdoor sensor running bias "
        f"{hp.outside_bias_running_k:+.2f} K",
    ]
    lines += [
        f"  {k:22s} [{lo:.3g} .. {hi:.3g}]" for k, (lo, hi) in result.heat_pump_intervals.items()
    ]
    lines += ["== building layer (final fit, 90% day-block bootstrap)"]
    lines += describe_building(result.params.building, result.building_intervals)
    lines += [
        f"  fit rmse water {result.building.rmse_water:.2f} K, "
        f"room {result.building.rmse_room:.2f} K "
        f"over {result.building.n_windows} daily windows",
        f"== validation (fit before {datetime.fromtimestamp(result.split, UTC):%Y-%m-%d}, "
        "test after)",
    ]
    for h, r, o, p in zip(
        v.horizons_h, v.room_rmse, v.outlet_rmse, v.room_persistence_rmse, strict=True
    ):
        lines.append(
            f"  free-run {h:4.0f} h: room {r:.2f} K (persistence {p:.2f}), outlet {o:.2f} K"
        )
    span = result.held_out
    if span is not None:
        lines.append(
            f"  held-out continuous run {datetime.fromtimestamp(span.start, UTC):%Y-%m-%d} - "
            f"{datetime.fromtimestamp(span.end, UTC):%Y-%m-%d} ({span.days:.1f} days, "
            "recorded vs simulated):"
        )
        lines += [
            f"    {name:18s} {span.measured[name]:8.2f} {span.simulated[name]:8.2f} "
            f"({100 * span.error(name):+.1f}{' pts' if name == 'short_run_share' else ' %'})"
            for name in span.measured
        ]
    for fold in result.folds[1:]:
        span = fold.held_out
        lines.append(
            f"  earlier fold: fit before {datetime.fromtimestamp(fold.split, UTC):%Y-%m-%d}, "
            f"continuous run to {datetime.fromtimestamp(fold.end, UTC):%Y-%m-%d} "
            f"({span.days:.1f} days, recorded vs simulated):"
        )
        lines += [
            f"    {name:18s} {span.measured[name]:8.2f} {span.simulated[name]:8.2f} "
            f"({100 * span.error(name):+.1f}{' pts' if name == 'short_run_share' else ' %'})"
            for name in span.measured
        ]
    for label, cal in (("train", result.train_calibration), ("final", result.final_calibration)):
        if cal is not None:
            lines.append(
                f"  cycling calibration ({label}): return delay {cal.return_delay_s:.0f} s, "
                f"water-mass conductance x{cal.water_mass_scale:.2f}, controller candidate "
                f"{cal.controller_index}, score {cal.span.score:.1f}"
            )
    check = result.warmup_check
    if check is not None:
        lines.append(
            f"  COP first {check.early_s / 60:.0f} min of runs (held-out, "
            f"{100 * check.early_share_heat:.0f} % of heat): recorded "
            f"{check.cop_recorded_early:.2f}, warm-up map {check.cop_model_early:.2f}, steady "
            f"map {check.cop_steady_map_early:.2f}; later recorded {check.cop_recorded_late:.2f}, "
            f"warm-up map {check.cop_model_late:.2f}, steady map {check.cop_steady_map_late:.2f}"
        )
    lines += [
        f"  full plant, recorded setpoint, {days.day_starts.size} held-out days from "
        f"{datetime.fromtimestamp(result.split, UTC):%Y-%m-%d} (daily restart): "
        f"heat {days.heat_error_pct:+.1f} % "
        f"(daily MAPE {days.daily_heat_mape_pct:.1f} %), starts {days.starts_error_pct:+.1f} % "
        f"({days.starts_measured.mean():.1f} vs {days.starts_simulated.mean():.1f}/day)",
        f"  full plant rmse: room {days.room_rmse.mean():.2f} K, "
        f"outlet {days.outlet_rmse.mean():.2f} K",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    """Run the CLI."""
    args = build_parser().parse_args(argv)
    if args.fetch_weather:
        if args.lat is None or args.lon is None or args.start is None or args.end is None:
            print("--fetch-weather needs --lat, --lon, --start and --end", file=sys.stderr)
            return 2
        fetch_weather(args.captures / "weather", Location(args.lat, args.lon), args.start, args.end)
    options = IdentifyOptions(
        capture_name=args.capture_name,
        split=args.split,
        test_days=args.test_days,
        bootstrap=args.bootstrap,
        seed=args.seed,
        folds=args.folds,
        end=None if args.last_day is None else args.last_day + 86400.0,
    )
    result = identify(args.captures, options)
    print("\n".join(render(result)))
    out = args.out or args.captures / "models" / "plant_params.json"
    report = result.to_json()
    io.save(out, result.params, report)
    print(f"wrote {out}")
    stale = io.fold_paths(out)
    for index, fold in enumerate(result.folds):
        path = io.fold_path(out, index)
        split = {
            "split": datetime.fromtimestamp(fold.split, UTC).isoformat(),
            "test_end": datetime.fromtimestamp(fold.end, UTC).isoformat(),
            "fold": index,
        }
        io.save(path, fold.params, split | report)
        print(f"wrote {path}")
    for path in stale[len(result.folds) :]:
        path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
