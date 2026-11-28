"""Plain-text rendering of open-loop run summaries for the CLI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from ovenbird_sim.evaluate.meta import NO_CLAIMS_BANNER

RULE: Final = "=" * 78


def _fmt(value: Any, digits: int = 2) -> str:
    """Format a value for a table: ``-`` for ``None``, fixed ``digits`` for floats."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _top(histogram: Mapping[str, Any], n: int = 8) -> str:
    """Return the first ``n`` histogram entries as ``key count`` text, or ``-`` when empty."""
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
