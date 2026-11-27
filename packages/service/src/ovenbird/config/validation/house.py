"""Rules of the house settings: the left-out days and the learned-value bounds."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Final

from pydantic_core import PydanticCustomError

from ovenbird.config.values import Issue

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings

DATE_RE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_EXCLUDED_DAYS: Final = 60
FUTURE_SLACK_DAYS: Final = 1
MIN_TRAINING_DAYS: Final = 8
BOUND_PAIRS: Final = (
    ("house_ua_min_w_per_k", "house_ua_max_w_per_k"),
    ("house_time_constant_min_h", "house_time_constant_max_h"),
    ("house_solar_aperture_min_m2", "house_solar_aperture_max_m2"),
    ("house_internal_gain_min_w", "house_internal_gain_max_w"),
)


def check_excluded_days(value: tuple[str, ...], today: date | None = None) -> tuple[str, ...]:
    """Return the left-out days sorted, each a real date no more than a day ahead.

    Parameters
    ----------
    value
        Days as ``YYYY-MM-DD``.
    today
        The current date in UTC; defaults to now.

    Raises
    ------
    PydanticCustomError
        ``date_format``, ``date_future`` or ``date_repeated``.
    """
    latest = (today or datetime.now(UTC).date()) + timedelta(days=FUTURE_SLACK_DAYS)
    seen: set[str] = set()
    for text in value:
        try:
            if DATE_RE.fullmatch(text) is None:
                raise ValueError(text)
            day = date.fromisoformat(text)
        except ValueError:
            raise PydanticCustomError("date_format", "days are written YYYY-MM-DD") from None
        if day > latest:
            raise PydanticCustomError("date_future", "a left-out day cannot lie in the future")
        if text in seen:
            raise PydanticCustomError("date_repeated", "each left-out day is listed once")
        seen.add(text)
    return tuple(sorted(value))


def house_issues(settings: Settings) -> list[Issue]:
    """Return the violated house rules: bounds in order, enough training days."""
    issues: list[Issue] = []
    for low_name, high_name in BOUND_PAIRS:
        low, high = getattr(settings, low_name), getattr(settings, high_name)
        if low is not None and high is not None and low > high:
            issues.append(
                Issue(
                    high_name,
                    "house_bounds_order",
                    f"{low_name} must not exceed {high_name}",
                    {"min_field": low_name, "max_field": high_name, "min": low, "max": high},
                )
            )
    fit, test = settings.house_learn_fit_days, settings.house_learn_test_days
    if fit < test + MIN_TRAINING_DAYS:
        issues.append(
            Issue(
                "house_learn_fit_days",
                "house_fit_days_short",
                f"house_learn_fit_days must be at least house_learn_test_days + "
                f"{MIN_TRAINING_DAYS}",
                {"fit_days": fit, "test_days": test, "min": test + MIN_TRAINING_DAYS},
            )
        )
    return issues
