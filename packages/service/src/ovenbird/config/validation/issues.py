"""Cross-field rules of the settings, gathered from the feature modules.

Cross-field rules are :class:`~ovenbird.config.values.Issue` objects
(:func:`control_issues`), so the configuration API reports them per field with a
stable code; at load time they are raised as one validation error
(:func:`raise_issues`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_core import PydanticCustomError

import ovenbird.stove.validation as stove_validation
from ovenbird.config.validation.duty import duty_issues
from ovenbird.config.validation.house import house_issues
from ovenbird.config.validation.inputs import input_issues
from ovenbird.config.validation.limits import limit_issues
from ovenbird.config.validation.modelplan import model_use_issues
from ovenbird.config.validation.room import outside_issues, room_issues
from ovenbird.config.validation.weather import weather_issues
from ovenbird.config.values import Issue

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


def control_issues(settings: Settings) -> list[Issue]:
    """Return every violated cross-field rule of ``settings``.

    The rules: plain MQTT inputs that never stand in for the pump's own data, room
    signal consistency, a known outside thermometer in °C, pump duty
    order and clamp, the wood-stove thresholds, timers and reference room, minimum setpoint
    below the maximum supply, an explicit curve inside ``[minimum setpoint, maximum
    supply]`` and the safety envelope, the integrator limit within the output
    limit, the start ramp inside the envelope, a complete weather location, the house bounds
    in order with enough training days, the lock on ``control_model_use`` = ``on`` and
    finally the controller's own checks on the merged configuration.

    Parameters
    ----------
    settings
        Field-validated settings.

    Returns
    -------
    list of Issue
        Empty when the settings are consistent.
    """
    issues = [
        *input_issues(settings),
        *room_issues(settings),
        *outside_issues(settings),
        *duty_issues(settings),
        *stove_validation.stove_issues(settings),
        *limit_issues(settings),
        *weather_issues(settings),
        *house_issues(settings),
        *model_use_issues(settings),
    ]
    if issues:
        return issues
    try:
        settings.controller_config()
    except ValueError as exc:
        return [Issue(None, "invalid", str(exc))]
    return []


def raise_issues(settings: Settings) -> None:
    """Raise every violated cross-field rule of ``settings`` as one validation error.

    Raises
    ------
    PydanticCustomError
        ``config_issues``, with the issues' API form in its context.
    """
    issues = control_issues(settings)
    if issues:
        raise PydanticCustomError(
            "config_issues",
            "{summary}",
            {
                "summary": "; ".join(issue.message for issue in issues),
                "issues": [issue.to_json() for issue in issues],
            },
        )
