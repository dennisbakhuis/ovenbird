"""Candidates for the configuration's signal pickers (``GET api/v1/config/signals``).

Home Assistant candidates come from the entity index the HA input refreshes at every
``get_states`` re-read (read-only): temperature sensors (device class ``temperature``
or a temperature unit) and thermostats (``climate.*`` read through their
``current_temperature``, as ``ha/climate.x#current_temperature``, in HA's temperature
unit) for the room, cross-check and stove reference signals, every sensor for the
liveness signals. Each carries its entity id and, when HA's registry was read, its
area and device. MQTT inputs come from the settings, HeishaMon's
``main/Room_Thermostat_Temp`` from the catalogue; their values from the state store.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from ovenbird.config import Settings
from ovenbird.runtime import Runtime
from ovenbird_core import HeishaSignal, Instant, SourceKind
from ovenbird_core.inputs import (
    CLIMATE_DOMAIN,
    CURRENT_TEMPERATURE,
    HA_SIGNAL_PREFIX,
    ha_attribute_signal,
)

if TYPE_CHECKING:
    from ovenbird.ha import EntityState, HaInput

TEMPERATURE_UNITS: Final = frozenset({"°C", "°F", "K"})
TEMPERATURE_CLASS: Final = "temperature"
CROSSCHECK_SIGNALS: Final = (HeishaSignal.ROOM_THERMOSTAT_TEMP,)


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def _is_temperature(state: EntityState) -> bool:
    return (
        state.attributes.get("device_class") == TEMPERATURE_CLASS or state.unit in TEMPERATURE_UNITS
    )


def _ha_entry(
    entity_id: str, state: EntityState, now: Instant, ha: HaInput | None
) -> dict[str, Any]:
    name = state.attributes.get("friendly_name")
    changed = state.last_changed
    entry: dict[str, Any] = {
        "signal": f"{HA_SIGNAL_PREFIX}{entity_id}",
        "name": name if isinstance(name, str) else None,
        "unit": state.unit,
        "value": _number(state.state),
        "held_s": None if changed is None else round(max(0.0, now.wall.timestamp() - changed), 1),
        "source": SourceKind.HA.value,
        "entity_id": entity_id,
    }
    if ha is not None:
        area = ha.area_of(entity_id)
        device = ha.device_of(entity_id)
        if area is not None:
            entry["area"] = area
        if device is not None:
            entry["device_id"] = device
    return entry


def _climate_entry(
    entity_id: str, state: EntityState, now: Instant, ha: HaInput
) -> dict[str, Any] | None:
    raw = state.attributes.get(CURRENT_TEMPERATURE)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    entry = _ha_entry(entity_id, state, now, ha)
    updated = state.last_updated
    entry |= {
        "signal": ha_attribute_signal(entity_id, CURRENT_TEMPERATURE),
        "unit": ha.temperature_unit,
        "value": float(raw),
        "held_s": None if updated is None else round(max(0.0, now.wall.timestamp() - updated), 1),
    }
    return entry


def _store_entry(
    runtime: Runtime, signal: str, name: str | None, unit: str | None, source: str, now: Instant
) -> dict[str, Any]:
    view = runtime.store.view(signal, now)
    value = view.value if view is not None and view.reason is None else None
    number = value if isinstance(value, int | float) and not isinstance(value, bool) else None
    return {
        "signal": signal,
        "name": name,
        "unit": unit if unit is not None else (view.unit if view is not None else None),
        "value": number,
        "held_s": None if view is None or view.held is None else round(view.held, 1),
        "source": source,
    }


def signal_candidates(
    settings: Settings, runtime: Runtime, ha: HaInput | None, now: Instant | None = None
) -> dict[str, Any]:
    """Return the body of ``GET api/v1/config/signals``.

    Parameters
    ----------
    settings
        Effective settings (MQTT inputs, HA configuration).
    runtime
        State store and clock.
    ha
        The HA input (its entity index); ``None`` without HA.
    now
        Current instant; the runtime clock when omitted.

    Returns
    -------
    dict
        ``ha`` (enabled, link up, HA's temperature unit) and the ``room``,
        ``liveness`` and ``crosscheck`` candidates.
    """
    moment = now or runtime.clock()
    room: list[dict[str, Any]] = []
    liveness: list[dict[str, Any]] = []
    crosscheck: list[dict[str, Any]] = []
    index = ha.index if ha is not None else {}
    for entity_id in sorted(index):
        state = index[entity_id]
        if entity_id.startswith(f"{CLIMATE_DOMAIN}."):
            climate = None if ha is None else _climate_entry(entity_id, state, moment, ha)
            if climate is not None:
                room.append(climate)
                crosscheck.append(climate)
            continue
        entry = _ha_entry(entity_id, state, moment, ha)
        liveness.append(entry)
        if _is_temperature(state):
            room.append(entry)
            crosscheck.append(entry)
    for item in settings.mqtt_inputs:
        entry = _store_entry(
            runtime, item.signal_id, item.topic, item.unit, SourceKind.MQTT.value, moment
        )
        liveness.append(entry)
        if item.unit in TEMPERATURE_UNITS:
            room.append(entry)
            crosscheck.append(entry)
    for signal in CROSSCHECK_SIGNALS:
        crosscheck.append(
            _store_entry(runtime, signal, None, None, SourceKind.HEISHAMON.value, moment)
        )
    link: dict[str, Any] = {
        "enabled": settings.ha_enabled,
        "link_up": settings.ha_enabled and runtime.store.link_up(SourceKind.HA, moment),
    }
    if ha is not None and settings.ha_enabled:
        link["temperature_unit"] = ha.temperature_unit
    return {
        "ha": link,
        "room": room,
        "liveness": liveness,
        "crosscheck": crosscheck,
    }
