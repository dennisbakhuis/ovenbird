"""Safety envelope applied as the last stage of every controller step."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from ovenbird_core.control.curve import HeatingCurve
from ovenbird_core.setting import check_settings, setting, setting_metadata

ABSOLUTE_MIN_SETPOINT_C: Final = 10.0
ABSOLUTE_MAX_SUPPLY_C: Final = 65.0
MAX_MIN_SETPOINT_C: Final = 45.0
MAX_ENVELOPE_BAND_K: Final = 15.0
EPSILON: Final = 1e-9


class EmitterType(StrEnum):
    """Heat emitters connected to the heating loop."""

    SCREED_FLOOR = "screed_floor"
    RADIATORS = "radiators"
    MIXED = "mixed"


DEFAULT_MAX_SUPPLY_C: Final = {
    EmitterType.SCREED_FLOOR: 40.0,
    EmitterType.MIXED: 40.0,
    EmitterType.RADIATORS: 55.0,
}


class Bound(StrEnum):
    """Which limit produced a safety bound."""

    MIN_SETPOINT = "safety_min"
    MAX_SUPPLY = "safety_max"
    ENVELOPE_MIN = "envelope_min"
    ENVELOPE_MAX = "envelope_max"


@dataclass(frozen=True, slots=True)
class SafetyBounds:
    """Allowed water setpoint range at one outside temperature.

    Parameters
    ----------
    low, high
        Inclusive bounds in °C (``low <= high``).
    low_source, high_source
        The limit each bound comes from.
    """

    low: float
    high: float
    low_source: Bound
    high_source: Bound

    @property
    def low_int(self) -> int:
        """Smallest allowed integer setpoint."""
        return min(math.ceil(self.low - EPSILON), self.high_int)

    @property
    def high_int(self) -> int:
        """Largest allowed integer setpoint."""
        return math.floor(self.high + EPSILON)

    def clamp(self, value: float) -> float:
        """Clamp a continuous setpoint."""
        return min(max(value, self.low), self.high)

    def clamp_int(self, value: int) -> int:
        """Clamp an integer setpoint."""
        return min(max(value, self.low_int), self.high_int)


@dataclass(frozen=True, slots=True)
class SafetyLimits:
    """Hard limits on the water setpoint.

    The envelope mirrors the stateless fallback rule installed on HeishaMon: a
    conservative curve evaluated at the *raw* ``Outside_Temp`` with a band
    ``[curve - below, curve + above]``. The absolute limits always win over the
    envelope: the result never exceeds ``max_supply_c`` and never drops below
    ``min_setpoint_c``.

    Parameters
    ----------
    max_supply_c, min_setpoint_c, envelope_below_k, envelope_above_k
        Settings, described on the fields; "off" is the low setpoint.
    envelope
        Conservative curve of the envelope.

    Raises
    ------
    ValueError
        When the limits are inconsistent or outside the absolute range.
    """

    max_supply_c: float = field(
        metadata=setting_metadata(
            ge=ABSOLUTE_MIN_SETPOINT_C + 1.0,
            le=ABSOLUTE_MAX_SUPPLY_C,
            unit="°C",
            doc="Hard maximum water setpoint.",
        )
    )
    envelope: HeatingCurve
    min_setpoint_c: float = setting(
        20.0,
        ge=ABSOLUTE_MIN_SETPOINT_C,
        le=MAX_MIN_SETPOINT_C,
        unit="°C",
        doc="Lowest water setpoint.",
    )
    envelope_below_k: float = setting(
        6.0,
        ge=0.0,
        le=MAX_ENVELOPE_BAND_K,
        unit="K",
        doc="Width of the safety envelope below its curve.",
    )
    envelope_above_k: float = setting(
        5.0,
        ge=0.0,
        le=MAX_ENVELOPE_BAND_K,
        unit="K",
        doc="Width of the safety envelope above its curve.",
    )

    def __post_init__(self) -> None:
        """Validate the limits."""
        check_settings(self)
        if not self.min_setpoint_c + 1.0 <= self.max_supply_c:
            raise ValueError("max_supply_c must exceed min_setpoint_c by at least 1 K")

    @classmethod
    def for_emitter(cls, emitter: EmitterType, envelope: HeatingCurve) -> SafetyLimits:
        """Default limits for an emitter type around ``envelope``."""
        return cls(max_supply_c=DEFAULT_MAX_SUPPLY_C[emitter], envelope=envelope)

    def bounds(self, outside_c: float) -> SafetyBounds:
        """Return the allowed setpoint range at raw outside temperature ``outside_c``."""
        reference = self.envelope.water(outside_c)
        high, high_source = self.max_supply_c, Bound.MAX_SUPPLY
        if reference + self.envelope_above_k < high:
            high, high_source = reference + self.envelope_above_k, Bound.ENVELOPE_MAX
        low, low_source = self.min_setpoint_c, Bound.MIN_SETPOINT
        if reference - self.envelope_below_k > low:
            low, low_source = reference - self.envelope_below_k, Bound.ENVELOPE_MIN
        if high < self.min_setpoint_c:
            high, high_source = self.min_setpoint_c, Bound.MIN_SETPOINT
        if low > high:
            low, low_source = high, high_source
        return SafetyBounds(low, high, low_source, high_source)

    def fallback_setpoint(self, outside_c: float) -> float:
        """Water setpoint the HeishaMon envelope rule writes at raw ``outside_c``.

        The rule rewrites a setpoint outside :meth:`bounds` (or above the maximum
        supply) to the envelope curve itself, kept within the bounds.
        """
        return self.bounds(outside_c).clamp(self.envelope.water(outside_c))

    def fallback_values(self, outside_c: float) -> frozenset[int]:
        """Integer setpoints the envelope rule may write at raw ``outside_c``.

        The rule's arithmetic may round or truncate :meth:`fallback_setpoint`, so both
        neighbouring integers count, limited to the integer bounds.
        """
        bounds = self.bounds(outside_c)
        value = self.fallback_setpoint(outside_c)
        near = {math.floor(value + EPSILON), math.ceil(value - EPSILON)}
        inside = frozenset(v for v in near if bounds.low_int <= v <= bounds.high_int)
        return inside or frozenset({bounds.clamp_int(round(value))})
