"""The "about" page (``GET api/v1/system/about``) and the service start count."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from ovenbird import __version__
from ovenbird.clock import iso_from_unix, iso_z
from ovenbird_core import Instant

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.control.loop import ControlLoop
    from ovenbird.runtime import Runtime
    from ovenbird.system.facts import Facts

STARTS_KEY: Final = "service_starts"


def record_start(facts: Facts, now: Instant) -> dict[str, Any]:
    """Count this service start (kept across restarts); returns the new count."""
    stored = facts.get(STARTS_KEY)
    count = int(stored.get("count", 0)) if isinstance(stored, dict) else 0
    previous = stored.get("last_ts") if isinstance(stored, dict) else None
    value = {"count": count + 1, "last_ts": now.wall.timestamp(), "previous_ts": previous}
    facts.set(STARTS_KEY, value)
    return value


def about_body(
    settings: Settings,
    runtime: Runtime,
    loop: ControlLoop | None,
    started: Instant,
    starts: dict[str, Any] | None,
    moment: Instant,
) -> dict[str, Any]:
    """Return the body of ``GET api/v1/system/about``.

    Parameters
    ----------
    settings
        The effective settings.
    runtime
        Clock, state store and component health.
    loop
        The control loop, if any.
    started
        When this service instance started.
    starts
        The service start count (see :func:`record_start`).
    moment
        Current instant.
    """
    found = starts or {}
    previous = found.get("previous_ts")
    control = None
    if loop is not None:
        hold = loop.guard.hold
        control = {
            "mode": loop.effective_mode.value,
            "configured_mode": loop.mode.value,
            "interval_s": loop.interval_s,
            "ticks": loop.ticks,
            "last_tick_at": None if loop.last_tick is None else iso_z(loop.last_tick.wall),
            "publishing": loop.guard.permits,
            "paused": hold.paused,
            "releasing": hold.releasing,
            "restored_state": loop.restored,
        }
    return {
        "version": __version__,
        "api_version": 1,
        "service_time": iso_z(moment.wall),
        "timezone": settings.control_timezone,
        "started_at": iso_z(started.wall),
        "uptime_s": round(moment.since(started), 1),
        "service_starts": found.get("count"),
        "previous_start": None if previous is None else iso_from_unix(float(previous)),
        "failing_components": dict(runtime.crashes),
        "restored_state": None if loop is None else loop.restored,
        "setpoint_register": settings.command_setpoint_register,
        "control_interval_s": settings.control_interval_s,
        "control": control,
        "connections": {
            "mqtt": {
                "connected": runtime.mqtt_connected,
                "tls": settings.mqtt_tls,
                "heishamon_base": settings.heishamon_base,
                "heishamon_alive": runtime.store.heishamon_alive(moment),
            },
            "ha": {
                "configured": settings.ha_enabled,
                "connected": runtime.ha_connected if settings.ha_enabled else None,
            },
            "integration_token": settings.operate_token is not None,
        },
        "simulation": settings.simulation,
        "clock_speed": settings.clock_speed,
        "safety_net": None
        if loop is None or loop.envelope is None
        else loop.envelope.status(moment),
    }
