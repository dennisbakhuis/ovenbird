"""Convenience alias in the weather package for the forecast storage.

The stored forecasts live in ``history.db``, so the storage is
:mod:`ovenbird.history.forecast`; this module re-exports its names next to the
providers and the report that use them.
"""

from ovenbird.history.forecast import (
    COLUMNS,
    HOUR_S,
    ForecastRow,
    at_lead,
    delete_forecast_before,
    issue_rows,
    latest_issue,
    write_forecast,
)

__all__ = [
    "COLUMNS",
    "HOUR_S",
    "ForecastRow",
    "at_lead",
    "delete_forecast_before",
    "issue_rows",
    "latest_issue",
    "write_forecast",
]
