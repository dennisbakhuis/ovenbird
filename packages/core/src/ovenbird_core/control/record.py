"""Decision records and their JSON form.

The open-loop result database and the live decision log store exactly the dictionary
produced by :meth:`DecisionRecord.to_json_dict`. Its layout is versioned by
:data:`DECISION_SCHEMA_VERSION`; any change to field names or meanings bumps it.
Every value in it is a JSON scalar, list or object, so ``json.dumps`` needs no
custom encoder, and :meth:`DecisionRecord.from_json_dict` restores an equal record.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Final

from ovenbird_core.control.types import CommandIntent, IntentKind, LadderLevel, Mode, ReasonCode
from ovenbird_core.instant import Instant
from ovenbird_core.readings import SignalId

DECISION_SCHEMA_VERSION: Final = 1

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonDict = dict[str, JsonValue]
type StateValue = float | int | str | bool | None
type InputValue = float | int | str | bool | None


@dataclass(frozen=True, slots=True)
class Term:
    """One named contribution to the water setpoint.

    Parameters
    ----------
    name
        Term name (``curve``, ``room_feedback``, ``plan``, ``start_ramp``, ...).
    raw
        Value before the term's own clamp.
    value
        Value after the term's own clamp.
    unit
        ``"K"`` for additive contributions, ``"°C"`` for absolute values (the curve
        itself and the safety stage, which maps a setpoint to a setpoint).
    note
        Short human explanation.
    """

    name: str
    raw: float
    value: float
    unit: str = "K"
    note: str = ""

    def to_json_dict(self) -> JsonDict:
        """Return the JSON form."""
        return {
            "name": self.name,
            "raw": _finite(self.raw),
            "value": _finite(self.value),
            "unit": self.unit,
            "note": self.note,
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, JsonValue]) -> Term:
        """Rebuild a term from :meth:`to_json_dict` output."""
        return cls(
            name=_str(data["name"]),
            raw=_float(data["raw"]),
            value=_float(data["value"]),
            unit=_str(data["unit"]),
            note=_str(data["note"]),
        )


@dataclass(frozen=True, slots=True)
class InputRef:
    """An input a decision used, with its provenance.

    Parameters
    ----------
    signal
        Signal id.
    value
        Value used (``None`` when unavailable).
    age
        Seconds since confirmation, when known.
    fresh
        Whether it was usable.
    source
        Source kind or description.
    issued
        Issue time for forecasts and plans.
    """

    signal: SignalId
    value: InputValue
    age: float | None
    fresh: bool
    source: str | None = None
    issued: datetime | None = None

    def to_json_dict(self) -> JsonDict:
        """Return the JSON form."""
        value: JsonValue = _finite(self.value) if isinstance(self.value, float) else self.value
        return {
            "signal": self.signal,
            "value": value,
            "age": None if self.age is None else _finite(self.age),
            "fresh": self.fresh,
            "source": self.source,
            "issued": None if self.issued is None else self.issued.isoformat(),
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, JsonValue]) -> InputRef:
        """Rebuild an input reference from :meth:`to_json_dict` output."""
        issued = data["issued"]
        age = data["age"]
        return cls(
            signal=_str(data["signal"]),
            value=_scalar(data["value"]),
            age=None if age is None else _float(age),
            fresh=bool(data["fresh"]),
            source=_opt_str(data["source"]),
            issued=None if issued is None else datetime.fromisoformat(_str(issued)),
        )


def intent_to_json_dict(intent: CommandIntent) -> JsonDict:
    """Return the JSON form of a command intent."""
    return {"kind": intent.kind.value, "value": intent.value, "reason": intent.reason.value}


def intent_from_json_dict(data: Mapping[str, JsonValue]) -> CommandIntent:
    """Rebuild a command intent from :func:`intent_to_json_dict` output."""
    return CommandIntent(
        kind=IntentKind(_str(data["kind"])),
        value=_int(data["value"]),
        reason=ReasonCode(_str(data["reason"])),
    )


def instant_to_json(instant: Instant) -> JsonDict:
    """Return the JSON form of an instant (both axes)."""
    return {"monotonic": _finite(instant.monotonic), "wall": instant.wall.isoformat()}


def instant_from_json(data: JsonValue) -> Instant:
    """Rebuild an instant from :func:`instant_to_json` output."""
    if not isinstance(data, dict):
        raise TypeError("instant must be a JSON object")
    return Instant(_float(data["monotonic"]), datetime.fromisoformat(_str(data["wall"])))


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Complete explanation of one controller tick.

    Parameters
    ----------
    at
        The tick's instant.
    controller
        Controller name.
    mode
        Operating mode during the tick.
    ladder
        Degradation-ladder level that produced the decision.
    terms
        Named contributions in pipeline order, each before and after its clamp.
    pre_round
        Setpoint after all terms and the safety clamp, before rounding, deadband
        and dwell; ``None`` when nothing was computed.
    setpoint
        Desired integer water setpoint; ``None`` when there is none.
    binding
        The stage or constraint that determined the result, if any.
    flip_distance
        How far :attr:`flip_input` must move (in its own unit, K) to change the
        integer setpoint.
    flip_input
        The input :attr:`flip_distance` refers to (a room signal id,
        ``main/Outside_Temp`` or ``pre_round``).
    inputs_used
        Inputs with value, age and source.
    controller_state
        Flat, JSON-friendly controller state after the tick.
    reason
        Primary reason code.
    note
        One human sentence.
    intents
        Intents returned with this record.
    actor
        Who caused an override or plan (``None`` for automatic decisions).
    """

    at: Instant
    controller: str
    mode: Mode
    ladder: LadderLevel
    terms: tuple[Term, ...]
    pre_round: float | None
    setpoint: int | None
    binding: str | None
    flip_distance: float | None
    inputs_used: tuple[InputRef, ...]
    controller_state: Mapping[str, StateValue]
    reason: ReasonCode
    note: str
    flip_input: str | None = None
    intents: tuple[CommandIntent, ...] = ()
    actor: str | None = None
    schema: int = field(default=DECISION_SCHEMA_VERSION)

    def __post_init__(self) -> None:
        """Freeze the controller state mapping."""
        object.__setattr__(self, "controller_state", MappingProxyType(dict(self.controller_state)))

    def term(self, name: str) -> Term | None:
        """Return the term called ``name``, if present."""
        return next((term for term in self.terms if term.name == name), None)

    def to_json_dict(self) -> JsonDict:
        """Return the stable JSON form (see the module docstring)."""
        state: JsonDict = {
            key: (_finite(value) if isinstance(value, float) else value)
            for key, value in sorted(self.controller_state.items())
        }
        return {
            "schema": self.schema,
            "at": instant_to_json(self.at),
            "controller": self.controller,
            "mode": self.mode.value,
            "ladder": self.ladder.value,
            "terms": [term.to_json_dict() for term in self.terms],
            "pre_round": None if self.pre_round is None else _finite(self.pre_round),
            "setpoint": self.setpoint,
            "binding": self.binding,
            "flip_distance": None if self.flip_distance is None else _finite(self.flip_distance),
            "flip_input": self.flip_input,
            "inputs_used": [ref.to_json_dict() for ref in self.inputs_used],
            "controller_state": state,
            "reason": self.reason.value,
            "note": self.note,
            "intents": [intent_to_json_dict(intent) for intent in self.intents],
            "actor": self.actor,
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, JsonValue]) -> DecisionRecord:
        """Rebuild a record from :meth:`to_json_dict` output.

        Raises
        ------
        ValueError
            When the schema version is not :data:`DECISION_SCHEMA_VERSION`.
        """
        schema = _int(data["schema"])
        if schema != DECISION_SCHEMA_VERSION:
            raise ValueError(f"unsupported decision schema {schema}")
        pre_round = data["pre_round"]
        setpoint = data["setpoint"]
        flip = data["flip_distance"]
        state = data["controller_state"]
        if not isinstance(state, dict):
            raise TypeError("controller_state must be a JSON object")
        return cls(
            at=instant_from_json(data["at"]),
            controller=_str(data["controller"]),
            mode=Mode(_str(data["mode"])),
            ladder=LadderLevel(_str(data["ladder"])),
            terms=tuple(Term.from_json_dict(_obj(item)) for item in _list(data["terms"])),
            pre_round=None if pre_round is None else _float(pre_round),
            setpoint=None if setpoint is None else _int(setpoint),
            binding=_opt_str(data["binding"]),
            flip_distance=None if flip is None else _float(flip),
            flip_input=_opt_str(data["flip_input"]),
            inputs_used=tuple(
                InputRef.from_json_dict(_obj(item)) for item in _list(data["inputs_used"])
            ),
            controller_state={key: _scalar(value) for key, value in state.items()},
            reason=ReasonCode(_str(data["reason"])),
            note=_str(data["note"]),
            intents=tuple(intent_from_json_dict(_obj(item)) for item in _list(data["intents"])),
            actor=_opt_str(data["actor"]),
            schema=schema,
        )


def _finite(value: float) -> float:
    """Return ``value`` when finite, else raise ``ValueError``."""
    if not math.isfinite(value):
        raise ValueError(f"decision records hold finite numbers only, got {value!r}")
    return value


def _float(value: JsonValue) -> float:
    """Return a JSON number as float (booleans rejected), else raise ``TypeError``."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"expected a number, got {value!r}")
    return float(value)


def _int(value: JsonValue) -> int:
    """Return a JSON integer (booleans rejected), else raise ``TypeError``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected an integer, got {value!r}")
    return value


def _str(value: JsonValue) -> str:
    """Return a JSON string, else raise ``TypeError``."""
    if not isinstance(value, str):
        raise TypeError(f"expected a string, got {value!r}")
    return value


def _opt_str(value: JsonValue) -> str | None:
    """Return a JSON string or ``None``, else raise ``TypeError``."""
    return None if value is None else _str(value)


def _scalar(value: JsonValue) -> InputValue:
    """Return a JSON scalar (neither list nor object), else raise ``TypeError``."""
    if isinstance(value, list | dict):
        raise TypeError(f"expected a scalar, got {value!r}")
    return value


def _list(value: JsonValue) -> list[JsonValue]:
    """Return a JSON array, else raise ``TypeError``."""
    if not isinstance(value, list):
        raise TypeError(f"expected a list, got {value!r}")
    return value


def _obj(value: JsonValue) -> dict[str, JsonValue]:
    """Return a JSON object, else raise ``TypeError``."""
    if not isinstance(value, dict):
        raise TypeError(f"expected an object, got {value!r}")
    return value
