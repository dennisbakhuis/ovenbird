"""Candidates for the configuration's signal pickers (``GET api/v1/config/signals``).

Home Assistant candidates come from the entity index the HA input refreshes at every
``get_states`` re-read (read-only): temperature sensors (device class ``temperature``
or a temperature unit) and thermostats (``climate.*`` read through their
``current_temperature``, as ``ha/climate.x#current_temperature``, in HA's temperature
unit) for the room, cross-check and stove reference signals, every sensor for the
liveness signals. Each carries its entity id and, when HA's registry was read, its
area and device. MQTT inputs come from the settings, HeishaMon's
``main/Room_Thermostat_Temp`` from the catalogue; their values from the state store.

**Pump mirrors.** Home Assistant often has its own HeishaMon integration: one device
whose entities copy the heat pump's values that ovenbird already reads over MQTT. A
device is a pump mirror when at least :data:`MIRROR_MIN_SIGNALS` of its entities hold
pairwise different numbers, each within :data:`MIRROR_TOLERANCE` of the current value
of a different HeishaMon ``main/*`` signal. A number that more than
:data:`MIRROR_MAX_SHARED` ``main/*`` signals hold at once (``0`` and ``1`` of the flags
and modes) proves nothing and is not counted. Every HA candidate on such a device
carries ``pump_mirror: true``; the pickers list them apart. Nothing is hidden.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Final

from ovenbird.config import Settings
from ovenbird.runtime import Runtime
from ovenbird_core import HeishaSignal, Instant, Snapshot, SourceKind
from ovenbird_core.control.observe import as_number
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
HEISHAMON_MAIN_PREFIX: Final = "main/"
MIRROR_MIN_SIGNALS: Final = 3
MIRROR_TOLERANCE: Final = 0.05
MIRROR_MAX_SHARED: Final = 3
FLOAT_SLACK: Final = 1e-9

type PumpValues = tuple[tuple[float, ...], tuple[str, ...]]


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
    entity_id: str,
    state: EntityState,
    now: Instant,
    ha: HaInput | None,
    mirrors: frozenset[str] = frozenset(),
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
        "pump_mirror": False,
        "entity_id": entity_id,
    }
    if ha is not None:
        area = ha.area_of(entity_id)
        device = ha.device_of(entity_id)
        if area is not None:
            entry["area"] = area
        if device is not None:
            entry["device_id"] = device
            entry["pump_mirror"] = device in mirrors
    return entry


def _climate_entry(
    entity_id: str, state: EntityState, now: Instant, ha: HaInput, mirrors: frozenset[str]
) -> dict[str, Any] | None:
    raw = state.attributes.get(CURRENT_TEMPERATURE)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    entry = _ha_entry(entity_id, state, now, ha, mirrors)
    updated = state.last_updated
    entry |= {
        "signal": ha_attribute_signal(entity_id, CURRENT_TEMPERATURE),
        "unit": ha.temperature_unit,
        "value": float(raw),
        "held_s": None if updated is None else round(max(0.0, now.wall.timestamp() - updated), 1),
    }
    return entry


def _entity_number(entity_id: str, state: EntityState) -> float | None:
    """Return an entity's number: a thermostat's current temperature, else its state."""
    if entity_id.startswith(f"{CLIMATE_DOMAIN}."):
        return as_number(state.attributes.get(CURRENT_TEMPERATURE))
    return _number(state.state)


def pump_values(snapshot: Snapshot) -> PumpValues:
    """Return the usable numeric HeishaMon ``main/*`` values, sorted, with their signals.

    Parameters
    ----------
    snapshot
        State snapshot.

    Returns
    -------
    tuple
        Sorted values and, at the same positions, their signal ids.
    """
    pairs = sorted(
        (number, signal)
        for signal, view in snapshot.signals.items()
        if signal.startswith(HEISHAMON_MAIN_PREFIX)
        and view.reason is None
        and (number := as_number(view.value)) is not None
    )
    return tuple(value for value, _ in pairs), tuple(signal for _, signal in pairs)


def _signals_at(values: PumpValues, number: float) -> frozenset[str]:
    """Return the ``main/*`` signals whose value lies within the tolerance of ``number``."""
    numbers, signals = values
    reach = MIRROR_TOLERANCE + FLOAT_SLACK
    low = bisect_left(numbers, number - reach)
    high = bisect_right(numbers, number + reach)
    return frozenset(signals[low:high])


def _matching(options: list[frozenset[str]]) -> int:
    """Size of the largest pairing of numbers to different signals (augmenting paths)."""
    owner: dict[str, int] = {}

    def assign(index: int, seen: set[str]) -> bool:
        """Pair number ``index`` with a free signal, moving earlier pairs where needed."""
        for signal in options[index]:
            if signal in seen:
                continue
            seen.add(signal)
            if signal not in owner or assign(owner[signal], seen):
                owner[signal] = index
                return True
        return False

    return sum(assign(index, set()) for index in range(len(options)))


def _mirrors(numbers: Iterable[float], values: PumpValues) -> bool:
    """Whether a device's numbers pair with enough different ``main/*`` signals."""
    options: list[frozenset[str]] = []
    last: float | None = None
    for number in sorted(numbers):
        if last is not None and number - last <= MIRROR_TOLERANCE:
            continue
        last = number
        found = _signals_at(values, number)
        if found and len(found) <= MIRROR_MAX_SHARED:
            options.append(found)
    return len(options) >= MIRROR_MIN_SIGNALS and _matching(options) >= MIRROR_MIN_SIGNALS


def pump_mirror_devices(
    index: Mapping[str, EntityState],
    device_of: Callable[[str], str | None],
    values: PumpValues,
) -> frozenset[str]:
    """Return the HA devices whose entities mirror the heat pump's HeishaMon values.

    Parameters
    ----------
    index
        HA entity states by entity id.
    device_of
        HA device id of an entity; ``None`` without one.
    values
        HeishaMon ``main/*`` values (:func:`pump_values`).

    Returns
    -------
    frozenset
        Device ids of the pump mirrors; empty without HeishaMon values.
    """
    if not values[0]:
        return frozenset()
    numbers: dict[str, list[float]] = {}
    for entity_id, state in index.items():
        device = device_of(entity_id)
        number = _entity_number(entity_id, state)
        if device is not None and number is not None:
            numbers.setdefault(device, []).append(number)
    return frozenset(
        device
        for device, found in numbers.items()
        if len(found) >= MIRROR_MIN_SIGNALS and _mirrors(found, values)
    )


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
        "pump_mirror": False,
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
    index = ha.index if ha is not None else {}
    mirrors = (
        frozenset()
        if ha is None
        else pump_mirror_devices(index, ha.device_of, pump_values(runtime.store.snapshot(moment)))
    )
    room: list[dict[str, Any]] = []
    liveness: list[dict[str, Any]] = []
    crosscheck: list[dict[str, Any]] = []
    for entity_id in sorted(index):
        state = index[entity_id]
        if entity_id.startswith(f"{CLIMATE_DOMAIN}."):
            climate = None if ha is None else _climate_entry(entity_id, state, moment, ha, mirrors)
            if climate is not None:
                room.append(climate)
                crosscheck.append(climate)
            continue
        entry = _ha_entry(entity_id, state, moment, ha, mirrors)
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
