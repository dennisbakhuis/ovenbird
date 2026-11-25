"""Cross-field rules of the pump duty (circulation pump speed)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird.config.values import Issue

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


def duty_issues(settings: Settings) -> list[Issue]:
    """Return the violated rules of the pump duty: idle below heat, both within the clamp."""
    issues: list[Issue] = []
    low, high = settings.command_pump_duty_min, settings.command_pump_duty_max
    if settings.control_pump_duty_idle > settings.control_pump_duty_heat:
        issues.append(
            Issue(
                "control_pump_duty_idle",
                "pump_duty_order",
                "control_pump_duty_idle must not exceed control_pump_duty_heat",
            )
        )
    for name in ("control_pump_duty_idle", "control_pump_duty_heat"):
        if not low <= getattr(settings, name) <= high:
            issues.append(
                Issue(
                    name,
                    "pump_duty_clamp",
                    "control_pump_duty_idle and _heat must lie within "
                    f"command_pump_duty_min/_max ({low}-{high})",
                    {"min": low, "max": high},
                )
            )
    return issues


def check_duty_range(settings: Settings) -> None:
    """Refuse a pump duty clamp whose minimum lies above its maximum.

    Raises
    ------
    ValueError
        When ``command_pump_duty_min`` exceeds ``command_pump_duty_max``.
    """
    if settings.command_pump_duty_min > settings.command_pump_duty_max:
        raise ValueError("command_pump_duty_min must not exceed command_pump_duty_max")
