"""Cross-field rules of wood-stove mode: thresholds, timers and the reference room."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird.config.values import CELSIUS, TEMPERATURE_DOMAINS, Issue

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


from ovenbird_core.inputs import split_ha_signal


def stove_issues(settings: Settings) -> list[Issue]:
    """Return the violated rules of wood-stove mode: thresholds, timers and reference room."""
    issues: list[Issue] = []
    enter = settings.control_stove_enter_above_k
    if settings.control_stove_exit_hysteresis_k > enter:
        issues.append(
            Issue(
                "control_stove_exit_hysteresis_k",
                "stove_hysteresis",
                "control_stove_exit_hysteresis_k must not exceed control_stove_enter_above_k "
                "(an episode ends at or above the comfort temperature)",
                {"max": enter},
            )
        )
    if settings.control_stove_min_active_s > settings.control_stove_max_active_s:
        issues.append(
            Issue(
                "control_stove_min_active_s",
                "stove_min_above_max",
                "control_stove_min_active_s must not exceed control_stove_max_active_s",
                {"max": settings.control_stove_max_active_s},
            )
        )
    room = settings.control_room_signal
    if settings.control_stove_enabled and settings.control_stove_auto and room is None:
        issues.append(
            Issue(
                "control_stove_auto",
                "room_signal_required",
                "the automatic wood-stove detection needs control_room_signal",
            )
        )
    reference = settings.control_stove_reference_signal
    if reference is not None and reference == room:
        issues.append(
            Issue(
                "control_stove_reference_signal",
                "stove_reference_is_room",
                "control_stove_reference_signal must name another room than the room signal",
            )
        )
    elif reference is not None and not settings.signal_known(reference, heishamon=False):
        issues.append(
            Issue(
                "control_stove_reference_signal",
                "signal_unknown",
                f"stove reference signal {reference!r} is neither ha/<entity_id> with HA "
                "configured nor the signal of a configured MQTT input",
                {"signal": reference},
            )
        )
    elif reference is not None and not temperature_signal(settings, reference):
        issues.append(
            Issue(
                "control_stove_reference_signal",
                "signal_not_temperature",
                f"stove reference signal {reference!r} is not a room temperature in °C (an "
                f"HA entity of the domains {', '.join(TEMPERATURE_DOMAINS)}, a thermostat's "
                "current_temperature, or an MQTT input in °C)",
                {"signal": reference},
            )
        )
    return issues


def temperature_signal(settings: Settings, signal: str) -> bool:
    """Whether a known signal can be a room temperature in °C (HA domain or attribute, MQTT unit).

    Home Assistant temperatures in °F or K are converted to °C at ingest.
    """
    parts = split_ha_signal(signal)
    if parts is not None:
        entity_id, attribute = parts
        return attribute is not None or entity_id.split(".", 1)[0] in TEMPERATURE_DOMAINS
    units = {item.unit for item in settings.mqtt_inputs if item.signal_id == signal}
    return all(unit is None or unit == CELSIUS for unit in units)
