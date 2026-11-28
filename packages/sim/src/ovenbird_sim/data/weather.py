"""Historical weather from the Open-Meteo archive and historical-forecast APIs.

Hourly values are cached as JSON under ``<captures>/weather/``. The ERA5-based
archive is preferred; hours it does not have yet (its ~5-day delay) are filled from
the historical-forecast API (best-match model run). Radiation in Open-Meteo is the
mean over the *preceding* hour, so radiation samples are placed at the middle of
that hour; temperature, cloud cover and wind are instantaneous.

Fetching happens only on explicit request (:func:`fetch_weather`); loading never
touches the network.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np

from ovenbird_sim.data.series import Series

ARCHIVE_URL: Final = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL: Final = "https://historical-forecast-api.open-meteo.com/v1/forecast"
HOURLY: Final = (
    "temperature_2m",
    "relative_humidity_2m",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "direct_normal_irradiance",
    "cloud_cover",
    "wind_speed_10m",
)
RADIATION: Final = frozenset(
    {"shortwave_radiation", "direct_radiation", "diffuse_radiation", "direct_normal_irradiance"}
)
CACHE_NAME: Final = "open_meteo_hourly.json"
type HourlyBlock = dict[str, list[Any]]
TIMEOUT_S: Final = 60.0


@dataclass(frozen=True, slots=True)
class Location:
    """Site coordinates.

    Parameters
    ----------
    latitude, longitude
        Decimal degrees.
    """

    latitude: float
    longitude: float


def _url(base: str, location: Location, start: date, end: date) -> str:
    """Return the Open-Meteo request URL for ``location`` from ``start`` to ``end``.

    Parameters
    ----------
    base
        Endpoint URL without query.
    location
        Place whose coordinates are requested.
    start
        First day (UTC).
    end
        Last day (UTC).
    """
    query = urllib.parse.urlencode(
        {
            "latitude": f"{location.latitude:.2f}",
            "longitude": f"{location.longitude:.2f}",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(HOURLY),
            "timezone": "UTC",
        }
    )
    return f"{base}?{query}"


def _get(url: str) -> dict[str, object]:
    """Fetch ``url`` over https and return the decoded JSON object."""
    if not url.startswith("https://"):
        raise ValueError("only https URLs are fetched")
    request = urllib.request.Request(url, headers={"User-Agent": "ovenbird-sim"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("unexpected Open-Meteo response")
    return payload


def _hourly(payload: dict[str, object]) -> HourlyBlock:
    """Return the hourly block of an Open-Meteo response as lists by variable name."""
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise ValueError("Open-Meteo response without hourly data")
    return {str(k): list(v) for k, v in hourly.items() if isinstance(v, list)}


def merge_hourly(primary: HourlyBlock, fallback: HourlyBlock) -> HourlyBlock:
    """Fill missing hours of ``primary`` from ``fallback`` (matched on ``time``).

    Parameters
    ----------
    primary, fallback
        Open-Meteo ``hourly`` blocks.

    Returns
    -------
    dict
        Hourly block over the union of times with a ``source`` list (``archive`` or
        ``forecast``) per hour.
    """
    times = sorted(set(map(str, primary.get("time", []))) | set(map(str, fallback.get("time", []))))
    index_p = {str(t): i for i, t in enumerate(primary.get("time", []))}
    index_f = {str(t): i for i, t in enumerate(fallback.get("time", []))}
    merged: HourlyBlock = {}
    sources: list[str] = []
    for t in times:
        ip, jf = index_p.get(t), index_f.get(t)
        use_primary = ip is not None and primary["temperature_2m"][ip] is not None
        sources.append("archive" if use_primary else "forecast")
        for key in HOURLY:
            block, idx = (primary, ip) if use_primary else (fallback, jf)
            column = block.get(key)
            value = column[idx] if column is not None and idx is not None else None
            merged.setdefault(key, []).append(value)
    out: HourlyBlock = {"time": [], **merged}
    out["time"] = [datetime.fromisoformat(t).replace(tzinfo=UTC).timestamp() for t in times]
    out["source_is_archive"] = [1.0 if s == "archive" else 0.0 for s in sources]
    return out


def fetch_weather(directory: Path, location: Location, start: date, end: date) -> Path:
    """Download hourly weather for ``[start, end]`` and write the cache file.

    Parameters
    ----------
    directory
        Cache directory, e.g. ``capture/captures/weather``.
    location
        Site coordinates.
    start, end
        Inclusive UTC date range.

    Returns
    -------
    Path
        The written cache file.
    """
    archive = _hourly(_get(_url(ARCHIVE_URL, location, start, end)))
    forecast = _hourly(_get(_url(FORECAST_URL, location, start, end)))
    merged = merge_hourly(archive, forecast)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CACHE_NAME
    meta = {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "fetched": datetime.now(UTC).isoformat(),
        "radiation_is_preceding_hour_mean": True,
    }
    path.write_text(json.dumps({"meta": meta, "hourly": merged}), encoding="utf-8")
    return path


def load_weather(directory: Path) -> dict[str, Series]:
    """Load the cached hourly weather as series.

    Parameters
    ----------
    directory
        Cache directory.

    Returns
    -------
    dict of str to Series
        One series per hourly variable (keys prefixed ``wx/``); radiation shifted to
        the middle of its averaging hour. Empty when there is no cache.
    """
    path = directory / CACHE_NAME
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    hourly = payload["hourly"]
    t = np.asarray(hourly["time"], dtype=np.float64)
    out: dict[str, Series] = {}
    for key in (*HOURLY, "source_is_archive"):
        raw = hourly.get(key)
        if raw is None:
            continue
        v = np.array([math.nan if x is None else float(x) for x in raw])
        shift = -1800.0 if key in RADIATION else 0.0
        out[f"wx/{key}"] = Series(t + shift, v)
    return out
