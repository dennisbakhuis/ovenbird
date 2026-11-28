"""JSON and self-contained HTML summaries of a run."""

from __future__ import annotations

import html
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

STYLE: Final = """
:root{--bg:#fbfaf7;--fg:#1d1f21;--muted:#6b6f75;--line:#e3e1dc;--bar:#3f6fb5;--ok:#2f7d4f;
--bad:#b23a3a;--pend:#a87414;--card:#ffffff}
@media (prefers-color-scheme:dark){:root{--bg:#16181b;--fg:#e8e6e1;--muted:#9a9ea4;
--line:#2c2f34;--bar:#6f9be0;--ok:#5fbf86;--bad:#e07070;--pend:#d8a548;--card:#1d2024}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px}
.sub{color:var(--muted);margin:0 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.tile b{display:block;font-size:20px;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:12px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:8px;overflow:hidden}
td,th{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.bar{height:10px;background:var(--bar);border-radius:2px;min-width:1px}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--bad);font-weight:600}
.pending{color:var(--pend);font-weight:600}
.verdict{display:inline-block;padding:2px 10px;border-radius:12px;border:1px solid currentColor}
.wrap{overflow-x:auto}
"""


def _clean(value: Any) -> Any:
    """Return ``value`` with every non-finite float replaced by None, recursively."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def _fmt(value: Any, digits: int = 2) -> str:
    """Format ``value`` for a table cell: HTML-escaped text, floats to ``digits`` decimals."""
    if value is None:
        return "-"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "-"
        return f"{value:.{digits}f}"
    return html.escape(str(value))


def _tile(label: str, value: Any, digits: int = 2) -> str:
    """Return a summary tile showing ``value`` under ``label``."""
    return f'<div class="tile"><b>{_fmt(value, digits)}</b><span>{html.escape(label)}</span></div>'


def _bars(rows: Mapping[str, float], *, percent: bool = False, digits: int = 0) -> str:
    """Return a table of horizontal bars scaled to the largest value (shares when ``percent``)."""
    peak = max((v for v in rows.values() if isinstance(v, int | float)), default=0) or 1
    body = []
    for key, value in rows.items():
        width = 100.0 * value / peak if peak else 0.0
        shown = f"{100 * value:.1f} %" if percent else _fmt(value, digits)
        body.append(
            f"<tr><td>{html.escape(str(key))}</td><td class='n'>{shown}</td>"
            f"<td style='width:55%'><div class='bar' style='width:{width:.1f}%'></div></td></tr>"
        )
    return "<table><tbody>" + "".join(body) + "</tbody></table>"


def _pairs(rows: Mapping[str, Any], digits: int = 2) -> str:
    """Return a two-column table of the rows' names and values."""
    body = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td class='n'>{_fmt(v, digits)}</td></tr>"
        for k, v in rows.items()
    )
    return "<table><tbody>" + (body or "<tr><td>none</td><td></td></tr>") + "</tbody></table>"


def _faults(outcomes: list[dict[str, Any]]) -> str:
    """Return the table of every fault scenario check with its status and observation."""
    if not outcomes:
        return "<p class='sub'>No fault scenarios in this run.</p>"
    rows = []
    for item in outcomes:
        for check in item["checks"]:
            status = check["status"]
            rows.append(
                f"<tr><td>{html.escape(item['name'])}</td><td>{_fmt(item.get('at'))}</td>"
                f"<td>{html.escape(check['check'])}</td><td class='{status}'>{status}</td>"
                f"<td>{html.escape(check['detail'])}</td></tr>"
            )
    head = "<tr><th>scenario</th><th>at</th><th>expectation</th><th></th><th>observed</th></tr>"
    body = "".join(rows)
    return f"<div class='wrap'><table><thead>{head}</thead><tbody>{body}</tbody></table></div>"


def _violations(invariants: Mapping[str, Any]) -> str:
    """Return the invariant verdict: a pass line, or the violations by rule and the first ones."""
    if not invariants["violations"]:
        return (
            f"<p class='pass'>No violations in {invariants['decisions_checked']} decisions, "
            f"{invariants['command_events_checked']} command events and "
            f"{invariants['publishes_checked']} publishes.</p>"
        )
    rows = "".join(
        f"<tr><td>{html.escape(v['rule'])}</td><td>{html.escape(v['at'])}</td>"
        f"<td>{html.escape(v['detail'])}</td></tr>"
        for v in invariants["first"]
    )
    return (
        _pairs(invariants["by_rule"], 0)
        + "<h2>First violations</h2><div class='wrap'><table><thead><tr><th>rule</th><th>at</th>"
        + f"<th>detail</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def render_html(summary: Mapping[str, Any]) -> str:
    """Render the summary as one self-contained HTML page."""
    kpis = summary["kpis"]
    commands = kpis["commands"]
    plant = kpis["plant"]
    room = kpis["room"]
    span = summary["span"]
    passed = summary.get("passed", False)
    verdict = (
        "<span class='verdict pass'>passed</span>"
        if passed
        else "<span class='verdict fail'>failed</span>"
    )
    tiles = "".join(
        [
            _tile("simulated days", span["days"], 1),
            _tile("wall time (s)", summary["wall_time_s"], 0),
            _tile("starts per day", plant["starts_per_day"]),
            _tile("runs < 20 min", plant["share_runs_below_20_min"]),
            _tile("commands per day", commands["sent_per_day_mean"], 1),
            _tile(
                f"max writes/day (budget {commands['daily_budget']})",
                commands["sent_per_day_max"],
                0,
            ),
            _tile("room mean °C", room["mean_c"]),
            _tile("room min °C", room["min_c"]),
            _tile(f"h below {room['band_c']:.1f} °C", room["hours_below_band"], 1),
            _tile("room feedback share", kpis["room_feedback_share"]),
            _tile("held-value share", kpis["held_value_share"]),
            _tile("invariant violations", summary["invariants"]["violations"], 0),
        ]
    )
    energy = summary.get("energy", {})
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>ovenbird full run</title>",
        f"<style>{STYLE}</style></head><body><main>",
        f"<h1>ovenbird full run {verdict}</h1>",
        f"<p class='sub'>{_fmt(span['from'])} → {_fmt(span['to'])} · "
        f"{span['cycles']} cycles of 5 s · room via {_fmt(summary['profile']['room_via'])}</p>",
        f"<div class='tiles'>{tiles}</div>",
        "<h2>Ladder shares</h2>",
        _bars(kpis["ladder_shares"], percent=True),
        "<h2>Reasons</h2>",
        _bars(kpis["reason_shares"], percent=True),
        "<h2>Refusals (decisions)</h2>",
        _pairs(kpis["refusals"], 0),
        "<h2>Setpoint histogram (controlled decisions)</h2>",
        _bars({f"{k} °C": v for k, v in kpis["setpoint_histogram"].items()}),
        "<h2>Compressor run lengths (min)</h2>",
        _bars(plant["run_histogram_min"]),
        "<h2>Commands</h2>",
        _pairs(
            {
                **{f"events: {k}": v for k, v in commands["events"].items()},
                **{f"sent per day: {k}": v for k, v in commands["sent_by_kind_per_day"].items()},
                **{f"refused: {k}": v for k, v in commands["refused_by_reason"].items()},
            }
        ),
        "<h2>Alarms raised</h2>",
        _pairs(kpis["alarms_raised"], 0),
        "<h2>Command holds</h2>",
        _pairs(kpis["holds"], 0),
        "<h2>Fault scenarios</h2>",
        _faults(summary["faults"]),
        "<h2>Invariants</h2>",
        _violations(summary["invariants"]),
        "<h2>Plant and energy</h2>",
        _pairs(energy),
        "<h2>Sources</h2>",
        _pairs(summary["sources"]),
        "<h2>History database</h2>",
        _pairs(summary["history"]),
        "</main></body></html>",
    ]
    return "\n".join(parts)


def write_report(out: Path, summary: dict[str, Any]) -> None:
    """Write ``summary.json`` and ``summary.html`` into ``out``."""
    cleaned = _clean(summary)
    (out / "summary.json").write_text(
        json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / "summary.html").write_text(render_html(cleaned), encoding="utf-8")
