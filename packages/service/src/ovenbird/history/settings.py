"""History settings (``history_*``): retention per resolution, the yearly archive, housekeeping.

A retention of ``0`` days or ``None`` keeps the data forever; ``0`` is the form the
configuration store keeps (``None`` there means "back to the default"). Any other
retention is at least one day, so the monthly archive (:mod:`ovenbird.history.archive`),
which copies the history every quarter of an hour, always reaches data before
retention removes it.

:data:`RETENTION_PRESETS` are the simple choices of Settings → Data; a combination
that matches none of them is shown as "custom".
"""

from __future__ import annotations

from typing import Final

from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError

from ovenbird.config.fromcore import FeatureSettings
from ovenbird.history.database import Retention

MIN_RETENTION_DAYS: Final = 1.0
RETENTION_FIELDS: Final = (
    "history_raw_days",
    "history_1m_days",
    "history_15m_days",
    "history_1h_days",
    "history_decision_days",
)
RETENTION_PRESETS: Final[dict[str, dict[str, float]]] = {
    "short": {
        "history_raw_days": 7.0,
        "history_1m_days": 31.0,
        "history_15m_days": 366.0,
        "history_1h_days": 0.0,
        "history_decision_days": 31.0,
    },
    "standard": {
        "history_raw_days": 14.0,
        "history_1m_days": 90.0,
        "history_15m_days": 0.0,
        "history_1h_days": 0.0,
        "history_decision_days": 30.0,
    },
    "long": {
        "history_raw_days": 31.0,
        "history_1m_days": 366.0,
        "history_15m_days": 0.0,
        "history_1h_days": 0.0,
        "history_decision_days": 366.0,
    },
    "unlimited": {
        "history_raw_days": 0.0,
        "history_1m_days": 0.0,
        "history_15m_days": 0.0,
        "history_1h_days": 0.0,
        "history_decision_days": 0.0,
    },
}


def kept_days(days: float | None) -> float | None:
    """Return a retention in days; ``None`` (forever) for ``None`` and ``0``."""
    return days or None


def check_retention(days: float | None) -> float | None:
    """Return ``days`` when it is ``None``, ``0`` (forever) or at least one day.

    Raises
    ------
    PydanticCustomError
        ``retention_min`` for a value between 0 and 1.
    """
    if days is not None and 0 < days < MIN_RETENTION_DAYS:
        raise PydanticCustomError(
            "retention_min",
            "a retention is 0 (keep forever) or at least {min} day",
            {"min": MIN_RETENTION_DAYS},
        )
    return days


def preset_retention(name: str) -> tuple[Retention, float | None]:
    """Return the signal retention and the journal retention of a preset."""
    values = RETENTION_PRESETS[name]
    retention = Retention(
        raw_days=kept_days(values["history_raw_days"]),
        minute_days=kept_days(values["history_1m_days"]),
        quarter_days=kept_days(values["history_15m_days"]),
        hour_days=kept_days(values["history_1h_days"]),
    )
    return retention, kept_days(values["history_decision_days"])


class HistorySettings(FeatureSettings):
    """Retention and housekeeping of ``history.db`` (``history_*``)."""

    history_raw_days: float | None = Field(default=14.0, ge=0)
    history_1m_days: float | None = Field(default=90.0, ge=0)
    history_15m_days: float | None = Field(default=None, ge=0)
    history_1h_days: float | None = Field(default=None, ge=0)
    history_min_free_mb: int = Field(default=256, ge=0)
    history_queue_size: int = Field(default=20_000, ge=100)
    history_snapshot_hours: float | None = Field(default=6.0, gt=0)
    history_decision_days: float | None = Field(default=30.0, ge=0)
    history_archive_enabled: bool = True

    @field_validator(*RETENTION_FIELDS)
    @classmethod
    def _at_least_a_day(cls, value: float | None) -> float | None:
        return check_retention(value)

    def history_retention(self) -> Retention:
        """Return the retention of the signal history (``None`` keeps a resolution forever)."""
        return Retention(
            raw_days=kept_days(self.history_raw_days),
            minute_days=kept_days(self.history_1m_days),
            quarter_days=kept_days(self.history_15m_days),
            hour_days=kept_days(self.history_1h_days),
        )

    def history_journal_days(self) -> float | None:
        """Return the retention of the journals in days (``None`` keeps them forever)."""
        return kept_days(self.history_decision_days)
