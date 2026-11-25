"""Plain-text rendering of open-loop run and counterfactual summaries for the CLI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from ovenbird_sim.evaluate.closedloop import RECORDED_SETPOINTS as BASELINE
from ovenbird_sim.evaluate.kpi import TOTAL_KPIS
from ovenbird_sim.evaluate.meta import NO_CLAIMS_BANNER

RULE: Final = "=" * 78


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _top(histogram: Mapping[str, Any], n: int = 8) -> str:
    return ", ".join(f"{k} {v}" for k, v in list(histogram.items())[:n]) or "-"


def render_open_loop(summary: Mapping[str, Any]) -> str:
    """Render a open-loop run summary; the no-claims banner opens and closes it."""
    banner = f"*** {NO_CLAIMS_BANNER} ***"
    meta = summary.get("meta", {})
    controller = meta.get("controller", {})
    decisions = summary["decisions"]
    setpoint = summary["setpoint"]
    reference = setpoint["recorded_reference_only"]
    stale = summary["stale_inputs"]
    lines = [
        RULE,
        banner,
        RULE,
        f"controller {controller.get('name')} ({controller.get('version')}), "
        f"config {meta.get('config_hash')}, git {meta.get('git', {}).get('commit', '?')[:12]}",
        f"ticks {summary['ticks']} ({summary['days']:.1f} days) "
        f"{summary['first_tick']} -> {summary['last_tick']}",
        "ladder time share: "
        + ", ".join(f"{k} {100 * v:.1f} %" for k, v in decisions["ladder_time_share"].items()),
        f"reason codes: {_top(decisions['reason_codes'])}",
        f"binding: {_top(decisions['binding'])}",
    ]
    for kind, info in summary["intents"].items():
        lines.append(
            f"intent {kind}: {info['changes']} changes ({_fmt(info['changes_per_day'], 1)}/day)"
        )
    lines += [
        f"setpoint mean {_fmt(setpoint['mean'])} °C; distribution "
        + ", ".join(f"{k}: {100 * v:.0f} %" for k, v in setpoint["distribution"].items()),
        f"  recorded (reference only) mean {_fmt(reference['mean'])} °C; same tick "
        f"exact {_fmt(reference['same_tick_exact_share'], 3)}, "
        f"±1 K {_fmt(reference['same_tick_within_1k_share'], 3)}",
        f"stale inputs (room max age {_fmt(meta.get('options', {}).get('room_max_age_s'), 0)} s, "
        f"source {meta.get('options', {}).get('room')}): room missing "
        f"{100 * stale['room_missing_share']:.1f} %, room stale "
        f"{100 * stale['room_stale_share']:.1f} %, curve-only "
        f"{100 * stale.get('curve_only_share', 0.0):.1f} %, HeishaMon dead ticks "
        f"{stale['heishamon_dead_ticks']}",
        f"  hold/refuse: {_top(stale['hold_or_refuse_ticks'])}",
        RULE,
        banner,
        RULE,
    ]
    return "\n".join(lines)


def _gate_lines(gate: Mapping[str, Any]) -> list[str]:
    lines = []
    for c in gate["criteria"]:
        recorded = f" vs recorded {_fmt(c['recorded'])}" if c["recorded"] is not None else ""
        lines.append(
            f"  {c['name']:16s} simulated {_fmt(c['simulated'])}{recorded} {c['unit']}: "
            f"error {_fmt(c['error'], 3)} (bound {c['bound']}) "
            f"{'ok' if c['passed'] else 'FAIL'}"
        )
    return lines


FIDELITY_SHOWN = (
    "heat_kwh_per_day",
    "elec_kwh_per_day",
    "cop",
    "starts_per_day",
    "run_median_min",
    "short_run_share",
)


def _fidelity_lines(rows: list[Mapping[str, Any]], label: str) -> list[str]:
    by = {r["kpi"]: r for r in rows}
    out = []
    for name in FIDELITY_SHOWN:
        r = by.get(name)
        if r is None:
            continue
        relative = r["kind"] == "relative"
        scale, unit = (100.0, "%") if relative else (1.0, "")
        error = r["error"]
        shown = "-" if error is None else f"{scale * error:+.{1 if relative else 3}f}{unit}"
        out.append(
            f"  {label:9s} {name:20s} recorded {_fmt(r['recorded'])} simulated "
            f"{_fmt(r['simulated'])} ({shown}, tolerance ±{scale * r['tolerance']:g}{unit}) "
            f"{'ok' if r['ok'] else 'FAIL'}"
        )
    return out


def _event_lines(events: Mapping[str, Any] | None) -> list[str]:
    if not events or not events.get("items"):
        return ["known events: none detected"]
    lines = [
        f"known events (days left out of the gates, fidelity and sensor calibration: "
        f"{', '.join(events['excluded_days']) or '-'}; {events['scored_days']} days scored):"
    ]
    for item in events["items"]:
        lines.append(
            f"  {item['kind']} {item['start_local']} -> {item['end_local']} "
            f"({item['hours']} h + recovery to {item['tail_end_local']}): {item['reason']}"
        )
    lines.append("  gate on all days, for reference:")
    lines += ["  " + line for line in _gate_lines(events["gate_all_days"])]
    for fold in events.get("held_out_all_days", []):
        if fold["excluded_days"]:
            lines.append(f"  held-out {fold['period_start'][:10]} on all days, for reference:")
            lines += ["  " + line for line in _gate_lines(fold["gate_all_days"])]
    return lines


def render_counterfactual(summary: Mapping[str, Any]) -> str:
    """Render a counterfactual summary with the baseline gates first."""
    gate = summary["gate"]
    held = gate.get("held_out")
    passed = gate["passed"] and (held is None or held["passed"])
    verdict = "PASSED" if passed else "FAILED - every comparison is NOT CLAIMABLE"
    period = summary["meta"]["period"]
    lines = [
        RULE,
        f"BASELINE GATES {verdict}",
        RULE,
        f"period {period['start']} -> {period['end']} ({period['days']} days); "
        f"{summary['recorded_statement']}",
        *_event_lines(summary.get("known_events")),
        "in-sample gate (parameters fitted on all days):",
        *_gate_lines(gate),
    ]
    folds = [] if held is None else held.get("folds", [held])
    for fold in folds:
        hp = fold["period"]
        lines += [
            f"held-out gate ({hp['start']} -> {hp['end']}, {hp['days']} days; parameters "
            "fitted before it only):",
            f"  {fold['recorded_statement']}",
            *_gate_lines(fold),
        ]
    if held is None:
        lines.append("held-out gate: not run (no train-only parameters)")
    share = gate.get("replicates_passed_share")
    if share is not None:
        lines.append(f"  bootstrap replicates passing the in-sample gate: {100 * share:.0f} %")
    starts = summary["starts_investigation"]["all_days"]
    lines.append(
        "  starts/day: recorded {r}, plant on recorded setpoints (daily restart {a}, "
        "continuous {b})".format(
            r=_fmt(starts["recorded_per_day"]),
            a=_fmt(starts["recorded_setpoints_daily_restart_per_day"]),
            b=_fmt(starts["recorded_setpoints_continuous_per_day"]),
        )
    )
    lines += ["", "baseline fidelity (plant on the recorded setpoints vs measured):"]
    lines += _fidelity_lines(summary["baseline_fidelity"], "in-sample")
    for fold in folds:
        lines += _fidelity_lines(fold["fidelity"], f"held-out {fold['period']['start'][:10]}")
    refusals = summary.get("cycling_refusals") or []
    failed = "FAILED - electricity, COP, starts and run lengths refused"
    lines.append(f"cycling fidelity: {failed if refusals else 'ok'}")
    comfort = summary["comfort"]
    cal = summary.get("target_calibration")
    reps = summary.get("replicate_targets_c", {})
    lines += [
        "",
        "equal comfort (ovenbird - baseline, point [90 % combined interval]):",
        f"  calibrated ovenbird target {_fmt(comfort['calibrated_target_c'], 3)} °C"
        + (
            f" on the {cal.get('measure', 'mean')} (worst difference "
            f"{_fmt(cal.get('worst'), 2)} x tolerance, "
            f"{'met' if cal['converged'] else 'NOT met'}"
            f"; replicate targets {_fmt(reps.get('min'), 2)}-{_fmt(reps.get('max'), 2)})"
            if cal
            else " (not calibrated)"
        ),
    ]
    if cal and "mean_matched_target_c" in cal:
        lines.append(
            f"  target matching the mean alone {_fmt(cal['mean_matched_target_c'], 3)} °C, "
            f"the tail alone {_fmt(cal.get('tail_matched_target_c'), 3)} °C"
        )
    for key, label in (
        ("mean_delta_k", "mean room"),
        ("p10_delta_k", "occupied P10"),
        ("dh_below_baseline_p10_delta", "K·h/day below baseline P10"),
    ):
        d = comfort[key]
        lines.append(
            f"  {label:28s} {_fmt(d['point'], 3):>8s} [{_fmt(d['lo'], 3)}, {_fmt(d['hi'], 3)}]"
        )
    lines.append(
        f"  baseline mean {_fmt(comfort['baseline_mean_c'])} °C, P10 "
        f"{_fmt(comfort['baseline_p10_c'])} °C; "
        f"comfort {'matched' if comfort['matched'] else 'NOT matched'}"
    )
    for name, info in summary.get("room_input", {}).items():
        lines.append(
            f"  {name} room input fresh {100 * (info['fresh_share'] or 0):.1f} %, room feedback "
            f"{100 * (info.get('feedback_share') or 0):.1f} %, curve-only "
            f"{100 * (info['curve_only_share'] or 0):.1f} %, steady-rule starts "
            f"{100 * (info['steady_start_share'] or 0):.1f} %"
        )
    kpis = summary["kpis"]
    lines += ["", f"{'KPI':28s}{'recorded':>12s}{'baseline':>12s}{'ovenbird':>12s}"]
    for name in TOTAL_KPIS:
        lines.append(
            f"{name:28s}"
            + "".join(f"{_fmt(kpis[k].get(name)):>12s}" for k in ("recorded", BASELINE, "ovenbird"))
        )
    intervals = summary.get("intervals", {})
    lines += [
        "",
        "paired differences ovenbird - baseline: point [90 % interval: parameters + days] "
        "(parameters only | days only), claim status",
    ]
    for d in summary["differences"]:
        extra = intervals.get(d["kpi"], {})
        po = extra.get("parameters_only", [None, None])
        do = extra.get("days_only", [None, None])
        lines.append(
            f"  {d['kpi']:28s}{_fmt(d['point']):>9s} [{_fmt(d['lo'])}, {_fmt(d['hi'])}] "
            f"([{_fmt(po[0])}, {_fmt(po[1])}] | [{_fmt(do[0])}, {_fmt(do[1])}]) "
            f"{d['status'].upper()}"
        )
        lines.extend(f"      - {reason}" for reason in d["reasons"])
    lines.append(
        "refused (data not recorded): "
        + ", ".join(r["claim"] for r in summary["refused_unrecorded"])
    )
    sensitivity = summary.get("sensitivity", {})
    if sensitivity:
        lines += ["", "sensitivity (point estimate; difference ovenbird - baseline):"]
        for name, entry in sensitivity.items():
            diffs = ", ".join(
                f"{k} {_fmt(entry[k]['difference'])}"
                for k in ("elec_kwh_per_day", "cop", "starts_per_day", "room_mean_c")
            )
            lines.append(f"  {name:24s} {diffs}; {entry['note']}")
    variants = summary.get("room_variants", {})
    if variants:
        lines += [
            "",
            "room sensor variants (ovenbird at the calibrated target; point estimate):",
            f"  {'variant':9s}{'fresh':>8s}{'feedback':>10s}{'room mean':>11s}{'elec':>8s}"
            f"{'starts':>8s}  difference to the baseline (room, elec, starts)",
        ]
        for name, entry in variants.items():
            lines.append(
                f"  {name:9s}{100 * (entry['room_fresh_share'] or 0):7.1f}%"
                f"{100 * (entry['feedback_share'] or 0):9.1f}%"
                f"{_fmt(entry['room_mean_c']['ovenbird'], 2):>11s}"
                f"{_fmt(entry['elec_kwh_per_day']['ovenbird'], 2):>8s}"
                f"{_fmt(entry['starts_per_day']['ovenbird'], 1):>8s}  "
                f"{_fmt(entry['room_mean_c']['difference'], 2)}, "
                f"{_fmt(entry['elec_kwh_per_day']['difference'], 2)}, "
                f"{_fmt(entry['starts_per_day']['difference'], 1)}"
            )
    contributions = summary["ablation"]["contributions"]
    if contributions:
        lines += ["", "term ablation (full controller minus the term; point estimate)"]
        for kpi_name, terms in contributions.items():
            lines.append(
                f"  {kpi_name:28s}"
                + ", ".join(f"{term} {_fmt(value)}" for term, value in terms.items())
            )
    for name, env in summary["envelope"].items():
        lines.append(
            f"envelope {name}: setpoint outside recorded {env['setpoint_range']} for "
            f"{100 * env['setpoint_outside_share']:.1f} %, room outside for "
            f"{100 * env['room_outside_share']:.1f} %"
        )
    lines += [RULE, f"BASELINE GATES {verdict}", RULE]
    return "\n".join(lines)
