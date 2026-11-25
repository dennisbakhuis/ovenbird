"""Cross-field rules of the room signal, its liveness and cross-check, the outside sensor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ovenbird.stove.validation as stove_validation
from ovenbird.config.values import TEMPERATURE_DOMAINS, Issue

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


def room_issues(settings: Settings) -> list[Issue]:
    """Return the violated rules of the room signal, its liveness signals and its cross-check."""
    room = settings.control_room_signal
    liveness = settings.control_room_liveness_signals
    crosscheck = settings.control_room_crosscheck_signal
    issues: list[Issue] = []
    if room is None and (liveness or crosscheck is not None):
        field = "control_room_liveness_signals" if liveness else "control_room_crosscheck_signal"
        issues.append(
            Issue(
                field,
                "room_signal_required",
                "control_room_liveness_signals and _crosscheck_signal need control_room_signal",
            )
        )
    if room is not None and room in liveness:
        issues.append(
            Issue(
                "control_room_liveness_signals",
                "liveness_is_room",
                "control_room_liveness_signals must not list the room signal itself",
            )
        )
    if room is not None and crosscheck == room:
        issues.append(
            Issue(
                "control_room_crosscheck_signal",
                "crosscheck_is_room",
                "control_room_crosscheck_signal must differ from the room signal",
            )
        )
    if room is not None and not settings.signal_known(room, heishamon=False):
        issues.append(
            Issue(
                "control_room_signal",
                "signal_unknown",
                f"room signal {room!r} is neither ha/<entity_id> with HA configured "
                "nor the signal of a configured MQTT input",
                {"signal": room},
            )
        )
    for signal in liveness:
        if not settings.signal_known(signal, heishamon=False):
            issues.append(
                Issue(
                    "control_room_liveness_signals",
                    "signal_unknown",
                    f"liveness signal {signal!r} is neither ha/<entity_id> with HA configured "
                    "nor the signal of a configured MQTT input",
                    {"signal": signal},
                )
            )
    if crosscheck is not None and not settings.signal_known(crosscheck, heishamon=True):
        issues.append(
            Issue(
                "control_room_crosscheck_signal",
                "signal_unknown",
                f"crosscheck signal {crosscheck!r} is neither a HeishaMon main/* signal, "
                "ha/<entity_id> with HA configured, nor a configured MQTT input",
                {"signal": crosscheck},
            )
        )
    return issues


def outside_issues(settings: Settings) -> list[Issue]:
    """Return the violated rules of the chosen outside thermometer for the curve."""
    signal = settings.control_outside_signal
    if signal is None:
        return []
    if not settings.signal_known(signal, heishamon=False):
        return [
            Issue(
                "control_outside_signal",
                "signal_unknown",
                f"outside signal {signal!r} is neither ha/<entity_id> with HA configured "
                "nor the signal of a configured MQTT input",
                {"signal": signal},
            )
        ]
    if not stove_validation.temperature_signal(settings, signal):
        return [
            Issue(
                "control_outside_signal",
                "signal_not_temperature",
                f"outside signal {signal!r} is not a temperature in °C (an HA entity of the "
                f"domains {', '.join(TEMPERATURE_DOMAINS)}, a thermostat's attribute, or an "
                "MQTT input in °C)",
                {"signal": signal},
            )
        ]
    return []
