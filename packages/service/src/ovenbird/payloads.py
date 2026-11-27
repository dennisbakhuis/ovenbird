"""JSON bodies of the API v1 (see ``docs/api-v1.md``)."""

from __future__ import annotations

from typing import Any, Final

from ovenbird import __version__
from ovenbird.clock import iso_z
from ovenbird_core import (
    CATALOGUE,
    Derived,
    SignalView,
    Snapshot,
    Value,
    ValueKind,
    compressor_running,
    defrost_active,
    dhw_active,
    heat_delivered_w,
)

API_VERSION: Final = 1
AGE_DECIMALS: Final = 1
POWER_DECIMALS: Final = 1
NO_VALUE_REASON: Final = "input has no usable value"

type Json = dict[str, Any]


def _age(age: float | None) -> float | None:
    return None if age is None else round(age, AGE_DECIMALS)


def enum_label(signal: str, value: Value) -> str | None:
    """Return the catalogue meaning of an enum signal's code, otherwise ``None``."""
    spec = CATALOGUE.get(signal)
    if spec is None or spec.kind is not ValueKind.ENUM:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return spec.meaning(value)


def signal_payload(view: SignalView) -> Json:
    """Return one entry of the snapshot's ``signals`` object.

    ``reason`` is ``None`` unless a later live delivery made the value unusable
    (``"unavailable: entity has no state"``); ``fresh`` is then false. ``age`` is
    the time since the last proof of life (the value or, via ``alive_by``, one of
    its liveness signals), ``held`` the time since the value last changed and
    ``max_age`` the limit in effect. ``source_unit`` is only present when the value
    was converted at ingest (a Home Assistant temperature in °F or K): the unit the
    source reported.
    """
    body: Json = {
        "value": view.value,
        "unit": view.unit,
        "label": enum_label(view.signal, view.value),
        "age": _age(view.age),
        "held": _age(view.held),
        "max_age": view.max_age,
        "alive_by": view.alive_by,
        "fresh": view.fresh,
        "source": view.source.value,
        "retained": view.retained,
        "reason": view.reason,
    }
    if view.source_unit is not None:
        body["source_unit"] = view.source_unit
    return body


def derived_payload[T](derived: Derived[T], decimals: int | None = None) -> Json:
    """Return ``{"value", "reason"}`` for a derived signal.

    Parameters
    ----------
    derived
        Derived value with provenance.
    decimals
        Round a float value to this many decimals.

    Returns
    -------
    dict
        ``reason`` is ``None`` when there is a value, otherwise a human explanation.
    """
    value: Any = derived.value
    if value is None:
        return {"value": None, "reason": derived.reason or NO_VALUE_REASON}
    if decimals is not None and isinstance(value, float):
        value = round(value, decimals)
    return {"value": value, "reason": None}


def defrost_payload(
    active: bool,
    *,
    mode: int | None = None,
    since: str | None = None,
    inlet_c: float | None = None,
    outside_c: float | None = None,
    max_s: float | None = None,
) -> Json:
    """Return the snapshot's ``defrost`` object.

    Parameters
    ----------
    active
        Whether the pump defrosts now.
    mode
        Deice mode the unit picks (1 or 2); ``None`` for an unknown model or outside
        a defrost.
    since
        When the safety monitor saw the defrost start (ISO 8601).
    inlet_c, outside_c
        ``Main_Inlet_Temp`` and ``Outside_Temp`` at the start.
    max_s
        Duration after which the defrost counts as stuck (``defrost_stuck``).

    Returns
    -------
    dict
        ``active``, ``mode``, ``since``, ``inlet_at_start_c``, ``outside_at_start_c``
        and ``max_s``; all but ``active`` ``None`` outside a defrost.
    """
    return {
        "active": active,
        "mode": mode if active else None,
        "since": since if active else None,
        "inlet_at_start_c": inlet_c if active else None,
        "outside_at_start_c": outside_c if active else None,
        "max_s": max_s if active else None,
    }


def snapshot_payload(snapshot: Snapshot, defrost: Json | None = None) -> Json:
    """Return the body of ``GET api/v1/snapshot``.

    Parameters
    ----------
    snapshot
        State snapshot from the core's store.
    defrost
        The safety monitor's view of the current defrost (:func:`defrost_payload`);
        without a monitor only ``active``, from ``Defrosting_State``.

    Returns
    -------
    dict
        ``at``, ``heishamon``, ``links`` (source kind to up), ``signals`` (sorted by
        id), ``derived`` and ``defrost``.
    """
    status = snapshot.heishamon
    lwt = None if status.lwt_online is None else ("Online" if status.lwt_online else "Offline")
    return {
        "at": iso_z(snapshot.now.wall),
        "heishamon": {
            "alive": status.alive,
            "last_heartbeat_age": _age(status.heartbeat_age),
            "lwt": lwt,
        },
        "links": {source.value: up for source, up in sorted(snapshot.links.items())},
        "signals": {
            signal: signal_payload(snapshot.signals[signal]) for signal in sorted(snapshot.signals)
        },
        "derived": {
            "compressor_running": derived_payload(compressor_running(snapshot)),
            "defrost_active": derived_payload(defrost_active(snapshot)),
            "dhw_active": derived_payload(dhw_active(snapshot)),
            "heat_delivered_w": derived_payload(heat_delivered_w(snapshot), POWER_DECIMALS),
        },
        "defrost": defrost
        if defrost is not None
        else defrost_payload(defrost_active(snapshot).value is True),
    }


def health_payload(
    *,
    live: bool,
    mqtt: str,
    heishamon: str,
    ha: str,
    history: str,
    alarms: str = "disabled",
    weather: str = "disabled",
) -> Json:
    """Return the body of ``GET api/v1/health``.

    Parameters
    ----------
    live
        The process works (false only when it is broken).
    mqtt, heishamon, ha, history
        Check values: ``connected``/``disconnected``, ``alive``/``dead``,
        ``connected``/``disconnected``/``disabled`` and ``ok``/``starting``/``error``.
    alarms
        Highest active alarm severity: ``ok``/``info``/``warning``/``critical``,
        ``starting`` before the first safety evaluation or ``disabled``.
    weather
        Forecast: ``disabled``/``starting``/``ok``/``stale``; never affects ``ready``.

    Returns
    -------
    dict
        ``ready`` is true while live, MQTT is connected, HeishaMon is alive and no
        critical alarm is active.
    """
    return {
        "live": live,
        "ready": live and mqtt == "connected" and heishamon == "alive" and alarms != "critical",
        "version": __version__,
        "api_version": API_VERSION,
        "checks": {
            "mqtt": mqtt,
            "heishamon": heishamon,
            "ha": ha,
            "history": history,
            "alarms": alarms,
            "weather": weather,
        },
    }
