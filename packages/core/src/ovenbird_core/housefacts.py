"""Facts the owner states about the house, and the rough values they imply.

The house model is learned from history; the owner can add what they know about the
house (floor area, volume, build period, emitters, windows, occupants). The learner
uses the rough values below as *weak* starting beliefs that the data can overrule,
and the service shows them next to the learned values as "an estimate from your
answers, not measured". Everything here is pure Python and deterministic.

Heat-loss coefficient (UA, W/K, ventilation included)
    ``UA = A_floor x (transmission + ventilation)`` per m2 of heated floor area:

    * transmission: a reference two-storey terraced or semi-detached dwelling has,
      per m2 of floor area, about 0.75 m2 of opaque wall, 0.5 m2 of roof, 0.5 m2 of
      ground floor (losing at 0.6 of its U-value, as the ground buffers it) and 0.2 m2
      of window; each build period has typical U-values as such homes are found today
      (older homes mostly with double glazing and some roof insulation added);
    * ventilation and infiltration: ``rho c_p / 3600 x n x V`` with ``rho c_p`` =
      1206 J/(m3 K), the period's typical air change rate ``n`` (per hour, the
      effective rate after heat recovery for the newest homes) and ``V`` the stated
      volume, or 2.6 m of room height times the floor area without one.

    The resulting specific losses (W per m2 floor per K) are, oldest to newest,
    about 3.9, 3.3, 2.0, 1.35, 1.0 and 0.7: order-of-magnitude values. Homes of one
    period differ by up to a factor of two (form factor, renovation, airtightness,
    how much of the house is heated), so the learner trusts them only loosely.

Solar aperture (m2, applied to global horizontal irradiance)
    ``window area x orientation factor x 0.3``. The orientation factor is the
    heating-season irradiance on a vertical window relative to the horizontal at
    mid-northern latitudes (south 1.1, east and west 0.6, north 0.3, mixed 0.65, the
    mean of the four); 0.3 is a typical share reaching the room: a glazing solar
    factor of about 0.6, a glass share of the window of about 0.75 and about 0.7 for
    obstruction, frames, blinds and curtains.

Internal gains (W, daily mean)
    ``120 W + 80 W x occupants``: a base of standby, refrigeration, lighting and pipe
    losses, and per occupant the sensible body heat over the hours at home together
    with the cooking, appliance and hot-water losses one person brings.

Floor-heating share
    Passed through: the share of the emitters that is floor heating (the rest are
    radiators).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Final

BUILD_PERIODS: Final = (
    "before_1945",
    "1945_1974",
    "1975_1991",
    "1992_2005",
    "2006_2014",
    "2015_later",
)
ORIENTATIONS: Final = ("north", "east", "south", "west", "mixed")
FLOOR_AREA_RANGE: Final = (0.0, 10_000.0)
VOLUME_RANGE: Final = (50.0, 5000.0)
SHARE_RANGE: Final = (0.0, 1.0)
WINDOW_AREA_RANGE: Final = (0.0, 200.0)
OCCUPANTS_RANGE: Final = (0, 12)
AIR_HEAT_J_PER_M3_K: Final = 1206.0
SECONDS_PER_HOUR: Final = 3600.0
ROOM_HEIGHT_M: Final = 2.6
WALL_PER_FLOOR: Final = 0.75
ROOF_PER_FLOOR: Final = 0.5
GROUND_PER_FLOOR: Final = 0.5
WINDOW_PER_FLOOR: Final = 0.2
GROUND_FACTOR: Final = 0.6
GLAZING_FACTOR: Final = 0.3
BASE_GAIN_W: Final = 120.0
GAIN_PER_OCCUPANT_W: Final = 80.0


@dataclass(frozen=True, slots=True)
class Envelope:
    """Typical envelope of a build period.

    Parameters
    ----------
    wall, roof, ground, window
        U-values in W/(m2 K).
    air_changes_per_h
        Effective ventilation and infiltration air changes per hour.
    """

    wall: float
    roof: float
    ground: float
    window: float
    air_changes_per_h: float

    @property
    def transmission_w_per_m2k(self) -> float:
        """Transmission loss per m2 of floor area of the reference dwelling, in W/(m2 K)."""
        return (
            WALL_PER_FLOOR * self.wall
            + ROOF_PER_FLOOR * self.roof
            + GROUND_PER_FLOOR * GROUND_FACTOR * self.ground
            + WINDOW_PER_FLOOR * self.window
        )


ENVELOPES: Final[Mapping[str, Envelope]] = MappingProxyType(
    {
        "before_1945": Envelope(1.9, 1.3, 1.5, 3.0, 0.9),
        "1945_1974": Envelope(1.5, 1.0, 1.3, 2.9, 0.8),
        "1975_1991": Envelope(0.6, 0.6, 0.7, 2.8, 0.6),
        "1992_2005": Envelope(0.4, 0.35, 0.4, 1.8, 0.45),
        "2006_2014": Envelope(0.3, 0.25, 0.3, 1.4, 0.35),
        "2015_later": Envelope(0.2, 0.17, 0.22, 1.0, 0.2),
    }
)
ORIENTATION_FACTORS: Final[Mapping[str, float]] = MappingProxyType(
    {"north": 0.3, "east": 0.6, "south": 1.1, "west": 0.6, "mixed": 0.65}
)


@dataclass(frozen=True, slots=True)
class HouseFacts:
    """What the owner states about the house; ``None`` = not stated.

    Parameters
    ----------
    floor_area_m2
        Heated floor area.
    volume_m3
        Heated volume.
    build_period
        One of :data:`BUILD_PERIODS`.
    floor_heating_share
        Share of the emitters that is floor heating (0 radiators only, 1 floor only).
    window_area_m2
        Total window area.
    window_orientation
        Where most windows face, one of :data:`ORIENTATIONS`.
    occupants
        People living in the house.
    """

    floor_area_m2: float | None = None
    volume_m3: float | None = None
    build_period: str | None = None
    floor_heating_share: float | None = None
    window_area_m2: float | None = None
    window_orientation: str | None = None
    occupants: int | None = None

    @property
    def stated(self) -> bool:
        """Whether any fact is stated."""
        return any(getattr(self, f.name) is not None for f in fields(self))


@dataclass(frozen=True, slots=True)
class FactEstimate:
    """Rough values implied by the facts; ``None`` where the facts do not suffice.

    Parameters
    ----------
    ua_w_per_k
        Heat-loss coefficient, ventilation included (floor area or volume, and the
        build period).
    solar_aperture_m2
        Effective aperture for global horizontal irradiance (window area).
    internal_gain_w
        Mean internal gains (occupants).
    floor_share
        Share of floor heating among the emitters.
    """

    ua_w_per_k: float | None = None
    solar_aperture_m2: float | None = None
    internal_gain_w: float | None = None
    floor_share: float | None = None


def _number(value: object, low: float, high: float, *, low_open: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number) or number > high:
        return None
    if number < low or (low_open and number == low):
        return None
    return number


def _choice(value: object, options: tuple[str, ...]) -> str | None:
    return value if isinstance(value, str) and value in options else None


def _count(value: object, low: int, high: int) -> int | None:
    number = _number(value, low, high)
    if number is None or number != int(number):
        return None
    return int(number)


def facts_from_config(effective: Mapping[str, object]) -> HouseFacts:
    """Read the facts from an effective configuration (``house_*`` fields).

    Missing, ``None``, mistyped or out-of-range values count as not stated.

    Parameters
    ----------
    effective
        Flat ``field: value`` mapping.

    Returns
    -------
    HouseFacts
        The stated facts.
    """
    return HouseFacts(
        floor_area_m2=_number(
            effective.get("house_floor_area_m2"), *FLOOR_AREA_RANGE, low_open=True
        ),
        volume_m3=_number(effective.get("house_volume_m3"), *VOLUME_RANGE),
        build_period=_choice(effective.get("house_build_period"), BUILD_PERIODS),
        floor_heating_share=_number(effective.get("house_floor_heating_share"), *SHARE_RANGE),
        window_area_m2=_number(effective.get("house_window_area_m2"), *WINDOW_AREA_RANGE),
        window_orientation=_choice(effective.get("house_window_orientation"), ORIENTATIONS),
        occupants=_count(effective.get("house_occupants"), *OCCUPANTS_RANGE),
    )


def specific_loss_w_per_m2k(build_period: str, height_m: float = ROOM_HEIGHT_M) -> float:
    """Heat loss per m2 of floor area per K of a build period, ventilation included.

    Parameters
    ----------
    build_period
        One of :data:`BUILD_PERIODS`.
    height_m
        Mean room height (volume per floor area).

    Returns
    -------
    float
        W/(m2 K).
    """
    envelope = ENVELOPES[build_period]
    ventilation = AIR_HEAT_J_PER_M3_K / SECONDS_PER_HOUR * envelope.air_changes_per_h * height_m
    return envelope.transmission_w_per_m2k + ventilation


def ua_estimate(facts: HouseFacts) -> float | None:
    """Heat-loss coefficient in W/K implied by the facts (see the module docstring)."""
    if facts.build_period is None:
        return None
    area = facts.floor_area_m2
    if area is None and facts.volume_m3 is not None:
        area = facts.volume_m3 / ROOM_HEIGHT_M
    if area is None:
        return None
    envelope = ENVELOPES[facts.build_period]
    volume = facts.volume_m3 if facts.volume_m3 is not None else area * ROOM_HEIGHT_M
    ventilation = AIR_HEAT_J_PER_M3_K / SECONDS_PER_HOUR * envelope.air_changes_per_h * volume
    return area * envelope.transmission_w_per_m2k + ventilation


def solar_estimate(facts: HouseFacts) -> float | None:
    """Effective solar aperture in m2 implied by the window area and orientation."""
    if facts.window_area_m2 is None:
        return None
    factor = ORIENTATION_FACTORS[facts.window_orientation or "mixed"]
    return facts.window_area_m2 * factor * GLAZING_FACTOR


def gains_estimate(facts: HouseFacts) -> float | None:
    """Mean internal gains in W implied by the number of occupants."""
    if facts.occupants is None:
        return None
    return BASE_GAIN_W + GAIN_PER_OCCUPANT_W * facts.occupants


def estimate(facts: HouseFacts) -> FactEstimate:
    """Rough values implied by the facts (each ``None`` when not derivable).

    Parameters
    ----------
    facts
        The stated facts.

    Returns
    -------
    FactEstimate
        UA, solar aperture, internal gains and floor-heating share.
    """
    return FactEstimate(
        ua_w_per_k=ua_estimate(facts),
        solar_aperture_m2=solar_estimate(facts),
        internal_gain_w=gains_estimate(facts),
        floor_share=facts.floor_heating_share,
    )
