"""The body of ``GET api/v1/weather``: measured, filtered and forecast outside temperature.

- ``measured``: ``main/Outside_Temp`` (the pump's integer sensor), 15 min means;
- ``filtered``: the controller's filtered outside temperature (decision state, last
  tick per 15 min);
- ``forecast``: the newest issue from the start of the current hour up to ``ahead_h``,
  ``[time, temperature, radiation, cloud cover, wind]``;
- ``forecast_past``: what was forecast 24 h ahead for each past hour;
- ``error``: bias and mean absolute error of the stored issues at 6 h and 24 h lead
  against the measured temperature (the 30 min around the hour) over the last 14 days;
- ``curve_outlook``: the active curve on the forecast, run through the same outside
  filter from the current filtered value ("curve only, before room correction").
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from ovenbird.clock import iso_from_unix
from ovenbird.history.forecast import ForecastRow, at_lead, issue_rows, latest_issue
from ovenbird.history.journal import decision_state_series
from ovenbird.history.query import query_series
from ovenbird.weather.service import STALE_AFTER_S, WeatherService
from ovenbird_core import HeishaSignal, Instant, StalenessPolicy
from ovenbird_core.control import OvenbirdConfig, filter_outside

HOUR_S: Final = 3600.0
STEP_S: Final = 900
ERROR_LEADS_H: Final = (6, 24)
PAST_LEAD_H: Final = 24
ERROR_DAYS: Final = 14
FILTERED_KEY: Final = "outside_filtered_c"


def _round(value: float | None, digits: int = 1) -> float | None:
    """Round a value, passing ``None`` through."""
    return None if value is None else round(value, digits)


def _interpolate(rows: Sequence[ForecastRow], ts: float) -> float | None:
    """Return the forecast temperature at ``ts`` by linear interpolation, or ``None``."""
    points = [(row.target_ts, row.temp_c) for row in rows if row.temp_c is not None]
    if not points:
        return None
    if ts <= points[0][0]:
        return points[0][1]
    for (t0, v0), (t1, v1) in pairwise(points):
        if t0 <= ts <= t1:
            return v0 + (v1 - v0) * (ts - t0) / (t1 - t0)
    return points[-1][1]


def _measured(
    path: Path, start: float, end: float, staleness: StalenessPolicy | None
) -> list[tuple[float, float]]:
    """Return the measured outside temperature as ``(ts, value)`` points in the window.

    Parameters
    ----------
    path
        History database file.
    start
        Start of the window, Unix time.
    end
        End of the window, Unix time.
    staleness
        Policy that hides stale values; ``None`` for none.
    """
    series = query_series(path, [HeishaSignal.OUTSIDE_TEMP], start, end, STEP_S, staleness)
    found = series.get(HeishaSignal.OUTSIDE_TEMP)
    if found is None:
        return []
    return [(ts, float(value)) for ts, value in found.points if isinstance(value, int | float)]


def error_statistics(
    path: Path, now_ts: float, staleness: StalenessPolicy | None = None
) -> dict[str, list[Any]]:
    """Bias and mean absolute error of the stored forecasts at 6 h and 24 h lead.

    Parameters
    ----------
    path
        ``history.db``.
    now_ts
        End of the evaluation window (unix seconds).
    staleness
        Staleness policy of the history query.

    Returns
    -------
    dict
        ``lead_h``, ``bias_k`` (forecast minus measured), ``mae_k`` and ``n`` per lead.
    """
    start = now_ts - ERROR_DAYS * 86_400.0
    measured = dict(_measured(path, start - HOUR_S, now_ts, staleness))
    bias: list[float | None] = []
    mae: list[float | None] = []
    counts: list[int] = []
    for lead in ERROR_LEADS_H:
        errors: list[float] = []
        for target, forecast in at_lead(path, lead, start, now_ts).items():
            near = [measured.get(target - STEP_S), measured.get(target)]
            values = [value for value in near if value is not None]
            if values:
                errors.append(forecast - sum(values) / len(values))
        counts.append(len(errors))
        bias.append(_round(sum(errors) / len(errors), 2) if errors else None)
        mae.append(_round(sum(abs(e) for e in errors) / len(errors), 2) if errors else None)
    return {"lead_h": list(ERROR_LEADS_H), "bias_k": bias, "mae_k": mae, "n": counts}


def weather_payload(
    service: WeatherService,
    history_path: Path,
    config: OvenbirdConfig,
    *,
    now: Instant,
    back_h: float,
    ahead_h: float,
    filtered_now: float | None,
    staleness: StalenessPolicy | None = None,
    measured_now: float | None = None,
) -> dict[str, Any]:
    """Return the body of ``GET api/v1/weather``.

    Parameters
    ----------
    service
        The weather component.
    history_path
        ``history.db``.
    config
        Active controller configuration (curve, outside filter).
    now
        Current instant.
    back_h, ahead_h
        Hours of history and of forecast to return.
    filtered_now
        The controller's current filtered outside temperature.
    staleness
        Staleness policy of the history query.
    measured_now
        The current (fresh) ``Outside_Temp``.

    Returns
    -------
    dict
        See ``docs/api-v1.md``; ``{"enabled": false, "reason", "location"}`` while off.
    """
    location = service.location()
    if not service.enabled:
        return {
            "enabled": False,
            "provider": service.provider.name,
            "reason": service.disabled_reason(),
            "location": None if location is None else location.to_json(),
        }
    end = now.wall.timestamp()
    start = end - back_h * HOUR_S
    issued = latest_issue(history_path, end) or service.issued_ts
    rows = issue_rows(history_path, issued) if issued is not None else []
    if not rows and service.latest is not None:
        rows = [
            ForecastRow(
                service.latest.issued_ts,
                h.target_ts,
                h.temp_c,
                h.radiation_wm2,
                h.cloud_pct,
                h.wind_ms,
            )
            for h in service.latest.hours
        ]
    first_hour = math.floor(end / HOUR_S) * HOUR_S
    ahead = [row for row in rows if first_hour <= row.target_ts <= end + ahead_h * HOUR_S]
    age = None if issued is None else max(0.0, end - issued)
    measured = _measured(history_path, start, end, staleness)
    filtered = decision_state_series(history_path, FILTERED_KEY, start, end, STEP_S)
    past = at_lead(history_path, PAST_LEAD_H, math.floor(start / HOUR_S) * HOUR_S, end)
    outlook: list[list[Any]] = []
    state, state_at = filtered_now, end
    tau = config.outside_filter_tau_s
    for row in ahead:
        if row.temp_c is None or row.target_ts < end:
            continue
        state = filter_outside(state, state_at, row.temp_c, row.target_ts, tau)
        state_at = row.target_ts
        outlook.append([iso_from_unix(row.target_ts), _round(config.base_water(state))])
    return {
        "enabled": True,
        "provider": service.provider.name,
        "issued": None if issued is None else iso_from_unix(issued),
        "age": _round(age),
        "stale": age is None or age > STALE_AFTER_S,
        "location": None if location is None else location.to_json(),
        "now": {
            "measured_c": measured_now,
            "filtered_c": _round(filtered_now, 2),
            "forecast_c": _round(_interpolate(rows, end)),
            "curve_c": None if filtered_now is None else _round(config.base_water(filtered_now)),
        },
        "measured": {"step": STEP_S, "points": [[iso_from_unix(t), v] for t, v in measured]},
        "filtered": {
            "step": STEP_S,
            "points": [[iso_from_unix(t), _round(v, 2)] for t, v in filtered],
        },
        "forecast": {
            "step": int(HOUR_S),
            "points": [
                [
                    iso_from_unix(row.target_ts),
                    _round(row.temp_c),
                    _round(row.radiation_wm2),
                    _round(row.cloud_pct, 0),
                    _round(row.wind_ms),
                ]
                for row in ahead
            ],
        },
        "forecast_past": {
            "lead_h": PAST_LEAD_H,
            "points": [[iso_from_unix(t), _round(v)] for t, v in sorted(past.items())],
        },
        "error": error_statistics(history_path, end, staleness),
        "curve_outlook": {"points": outlook},
    }
