"""Every switchable feature with its state: ``GET api/v1/control/features``.

A feature is ``off`` when it is switched off (or cannot work, such as room feedback
without a room sensor), ``shadow`` when it is on but its output is not applied (the
controller is not in ``auto`` mode, or the day shift is set to ``shadow``), ``active_now``
when it is on, applied and acting at the latest tick, and ``on`` otherwise. The house
basics and the start-count alarm only observe, so they are never ``shadow``. ``active``
says whether the feature acts at the latest tick whatever the mode, so a shadow run
shows what it would do. ``experimental`` marks a feature whose evaluation did not pass
(:data:`EXPERIMENTAL`, the sun day shift); ``on_available`` says whether it may be
fully switched on: always for the others, for an experimental one only once the owner
accepted that it is experimental (``control_dayshift_experimental_ok``).

The ids are :class:`~ovenbird.configstore.fields.Feature`, the same ids the settings
schema gives each field (``feature``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ovenbird.configstore.fields import Feature
from ovenbird.control.alarms import AlarmCode
from ovenbird_core.control import Mode, RampPhase

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.control.loop import ControlLoop

OBSERVING: frozenset[Feature] = frozenset({Feature.HOUSE_BASICS, Feature.STARTS_ALARM})
EXPERIMENTAL: frozenset[Feature] = frozenset({Feature.DAYSHIFT})
"""Features shipped as an explicit opt-in because their simulator evaluation did not pass."""


class FeatureState(StrEnum):
    """Where a feature stands."""

    OFF = "off"
    SHADOW = "shadow"
    ON = "on"
    ACTIVE_NOW = "active_now"


@dataclass(frozen=True, slots=True)
class FeatureView:
    """One feature as the API shows it.

    Parameters
    ----------
    feature
        The feature.
    enabled
        Switched on (and able to work).
    shadow
        On, but its output is not applied.
    active
        Acting at the latest tick.
    on_available
        May be fully switched on (an experimental feature only once acknowledged).
    """

    feature: Feature
    enabled: bool
    shadow: bool
    active: bool
    on_available: bool = True

    @property
    def state(self) -> FeatureState:
        """The state of the feature (see the module docstring)."""
        if not self.enabled:
            return FeatureState.OFF
        if self.shadow:
            return FeatureState.SHADOW
        return FeatureState.ACTIVE_NOW if self.active else FeatureState.ON

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "id": self.feature.value,
            "state": self.state.value,
            "enabled": self.enabled,
            "active": self.active,
            "experimental": self.feature in EXPERIMENTAL,
            "on_available": self.on_available,
        }


def _enabled(loop: ControlLoop, settings: Settings) -> dict[Feature, bool]:
    """Return whether every feature is switched on (and able to work)."""
    config = loop.controller.config
    limits = loop.targets.limits
    return {
        Feature.WEATHER_COMPENSATION: config.weather_compensation,
        Feature.ROOM_FEEDBACK: config.feedback.kp > 0.0 and loop.room_signal is not None,
        Feature.SLOW_START: config.ramp.enabled,
        Feature.MINIMUM_RUN: config.cycling.enabled,
        Feature.PUMP_DUTY: config.pump_duty is not None,
        Feature.QUIET: config.quiet is not None or config.quiet_start is not None,
        Feature.STOVE: config.stove is not None,
        Feature.DAYSHIFT: settings.control_dayshift_use != "off",
        Feature.SUMMER: config.summer is not None,
        Feature.AWAY: limits.away_enabled,
        Feature.BOOST: limits.boost_enabled,
        Feature.HOUSE_BASICS: settings.house_basics_enabled,
        Feature.STARTS_ALARM: settings.safety_starts_alarm_enabled,
    }


def on_available(feature: Feature, settings: Settings) -> bool:
    """Return whether ``feature`` may be fully switched on with ``settings``.

    Parameters
    ----------
    feature
        The feature.
    settings
        The settings in effect (the acknowledgement of the experimental day shift).
    """
    if feature is Feature.DAYSHIFT:
        return settings.control_dayshift_experimental_ok
    return True


def _active(loop: ControlLoop) -> dict[Feature, bool]:
    """Return whether every feature acts at the latest tick."""
    config = loop.controller.config
    state = loop.state
    latest = loop.latest_state or {}
    wall = loop.runtime.clock().wall
    dayshift = loop.dayshift.status() if loop.dayshift is not None else {}
    quiet = state.quiet_level
    duty = config.pump_duty
    return {
        Feature.WEATHER_COMPENSATION: loop.latest_state is not None,
        Feature.ROOM_FEEDBACK: latest.get("room_target_c") is not None and not state.stove_active,
        Feature.SLOW_START: state.ramp_phase not in (None, RampPhase.IDLE),
        Feature.MINIMUM_RUN: loop.latest_binding == "cycling_floor",
        Feature.PUMP_DUTY: duty is not None and state.pump_duty == duty.idle,
        Feature.QUIET: quiet is not None and quiet > 0,
        Feature.STOVE: state.stove_active,
        Feature.DAYSHIFT: abs(float(dayshift.get("offset_k") or 0.0)) > 0.0,
        Feature.SUMMER: state.summer_active,
        Feature.AWAY: loop.targets.away_active(wall),
        Feature.BOOST: loop.targets.boost is not None and not loop.targets.boost.expired(wall),
        Feature.HOUSE_BASICS: False,
        Feature.STARTS_ALARM: loop.alarms.is_active(AlarmCode.COMPRESSOR_STARTS),
    }


def feature_views(loop: ControlLoop, settings: Settings) -> list[FeatureView]:
    """Return every feature in :class:`~ovenbird.configstore.fields.Feature` order.

    Parameters
    ----------
    loop
        The control loop (the controller configuration and the latest tick).
    settings
        The settings in effect (the switches the loop does not hold).
    """
    enabled, active = _enabled(loop, settings), _active(loop)
    mode_shadow = loop.effective_mode is not Mode.AUTO
    views = []
    for feature in Feature:
        shadow = feature not in OBSERVING and mode_shadow
        if feature is Feature.DAYSHIFT:
            shadow = shadow or settings.control_dayshift_use == "shadow"
        views.append(
            FeatureView(
                feature,
                enabled[feature],
                shadow,
                active[feature],
                on_available(feature, settings),
            )
        )
    return views


def features_payload(loop: ControlLoop, settings: Settings) -> dict[str, Any]:
    """Return the body of ``GET api/v1/control/features``."""
    return {
        "mode": loop.effective_mode.value,
        "features": [view.to_json() for view in feature_views(loop, settings)],
    }
