"""The owner's house settings as the building fit's priors and constraints.

Three kinds of ``house_*`` settings reach the learner through the effective
configuration (absent or ``null`` = not set):

Facts (:mod:`ovenbird_core.housefacts`)
    Weak priors. A fact moves the prior mean of the quantity it informs to the rough
    value :func:`ovenbird_core.housefacts.estimate` derives and tightens its spread
    moderately, never below what the data overrule within days:

    * UA (``h_air_out``, floor area or volume with the build period): spread
      ``log(2)`` instead of ``log(5)``. Homes of one period differ by up to a factor
      of two and the learned UA is apparent (a single room sensor), so a factor of
      two is one standard deviation: a fact off by that much adds one unit to the
      cost, against several hundred observation residuals per day of data, so a
      UA the data determine moves away from it within days. Where the data do not
      determine it (no heating, a narrow outside-temperature range) the fact leads,
      which is what a prior is for.
    * Solar aperture (``window_area_m2``, orientation): spread the estimate itself,
      at least 2 m2, instead of 10 m2. The aperture is an effective one for global
      *horizontal* irradiance, which carries no direction, so the orientation is not
      identifiable from the data: it only moves the mean.
    * Internal gains (occupants): spread half the estimate, at least 150 W, instead of
      400 W. Gains and UA trade against each other (both set the balance
      temperature), so the spread stays wide enough not to steer the UA.
    * Volume: a lower bound on the building node's capacity (``c_air``), the heat
      capacity of the air alone (1206 J/(m3 K) x volume); that node holds the bulk of
      the building, so the fitted value is normally far above it.

    There is no fact for the share of floor heating: it would split the loop's
    conductance between a direct loop-to-room path and the emitter, which the data
    cannot tell apart, and the chain holds the direct path
    (:data:`ovenbird_sim.identify.building.CHAIN_FIXED`).

Bounds
    ``house_ua_*``, ``house_solar_aperture_*`` and ``house_internal_gain_*`` bound
    ``h_air_out``, ``solar_aperture_m2`` and ``q_int_w`` within their hard bounds
    (equal sides pin the parameter); ``house_time_constant_*`` bounds the slowest time
    constant through a penalty (:func:`ovenbird_sim.identify.building.fit_building`).

Learning options
    ``house_learn_fit_days``, ``house_learn_test_days``, ``house_learn_tolerance_k``
    and ``house_learn_excluded_days`` (local days left out of the fit, the scoring and
    the signature).

Invalid settings raise :class:`SettingError` naming the setting; the learner then
does not fit. With no facts and no bounds the priors are exactly the module constants.
:func:`unconstrained` drops the bounds, pins and time-constant range again (facts
kept) for the learner's reference fit.

The fit span must hold the test block plus :data:`MIN_TRAIN_DAYS` days: seven days to
train on and one for the partial first day and the alignment of the daily fit
windows. The learner (:mod:`ovenbird_sim.learn.run`) and the service's validation use
the same number.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Final

from ovenbird_core.housefacts import (
    AIR_HEAT_J_PER_M3_K,
    FactEstimate,
    HouseFacts,
    estimate,
    facts_from_config,
)
from ovenbird_sim.identify.building import (
    BOUNDS,
    DEFAULT_PRIORS,
    ConstraintError,
    ParamPrior,
    Priors,
)

__all__ = [
    "BOUND_SETTINGS",
    "FACT_SETTINGS",
    "MIN_TRAIN_DAYS",
    "HouseBounds",
    "HouseSettings",
    "LearnSettings",
    "ParamPrior",
    "Priors",
    "SettingError",
    "build_priors",
    "house_settings",
    "unconstrained",
]

UA_FACT_SD: Final = math.log(2.0)
SOLAR_FACT_MIN_SD_M2: Final = 2.0
GAINS_FACT_RELATIVE_SD: Final = 0.5
GAINS_FACT_MIN_SD_W: Final = 150.0
MAX_EXCLUDED_DAYS: Final = 60
MIN_TRAIN_DAYS: Final = 8
FACT_SETTINGS: Final = (
    "house_floor_area_m2",
    "house_volume_m3",
    "house_build_period",
    "house_window_area_m2",
    "house_window_orientation",
    "house_occupants",
)


@dataclass(frozen=True, slots=True)
class BoundSetting:
    """One learned quantity the owner can bound.

    Parameters
    ----------
    low_name, high_name
        Setting names of the lower and upper bound.
    parameter
        Building parameter it bounds (``None``: the slowest time constant).
    allowed
        Range a bound must lie in.
    """

    low_name: str
    high_name: str
    parameter: str | None
    allowed: tuple[float, float]


BOUND_SETTINGS: Final = (
    BoundSetting("house_ua_min_w_per_k", "house_ua_max_w_per_k", "h_air_out", (30.0, 1500.0)),
    BoundSetting("house_time_constant_min_h", "house_time_constant_max_h", None, (5.0, 500.0)),
    BoundSetting(
        "house_solar_aperture_min_m2",
        "house_solar_aperture_max_m2",
        "solar_aperture_m2",
        (0.0, 40.0),
    ),
    BoundSetting(
        "house_internal_gain_min_w", "house_internal_gain_max_w", "q_int_w", (0.0, 2000.0)
    ),
)
LEARN_RANGES: Final[Mapping[str, tuple[float, float]]] = {
    "house_learn_fit_days": (21.0, 90.0),
    "house_learn_test_days": (7.0, 21.0),
    "house_learn_tolerance_k": (-0.1, 0.2),
}


class SettingError(ValueError):
    """A house setting the learner cannot use; ``setting`` names it."""

    def __init__(self, setting: str, message: str) -> None:
        super().__init__(f"{setting}: {message}")
        self.setting = setting


@dataclass(frozen=True, slots=True)
class HouseBounds:
    """The owner's bounds per :data:`BOUND_SETTINGS` entry, keyed by the lower setting name.

    Parameters
    ----------
    ranges
        ``(min, max)`` per quantity; a side is ``None`` when not set.
    """

    ranges: Mapping[str, tuple[float | None, float | None]] = field(default_factory=dict)

    def get(self, spec: BoundSetting) -> tuple[float | None, float | None]:
        """Return the ``(min, max)`` of a quantity."""
        return self.ranges.get(spec.low_name, (None, None))


@dataclass(frozen=True, slots=True)
class LearnSettings:
    """Learning options from the configuration; ``None`` = not set.

    Parameters
    ----------
    fit_days, test_days, tolerance_k
        ``house_learn_fit_days``, ``house_learn_test_days``, ``house_learn_tolerance_k``.
    excluded_days
        ``house_learn_excluded_days``: local days ``YYYY-MM-DD``, sorted, unique.
    """

    fit_days: float | None = None
    test_days: int | None = None
    tolerance_k: float | None = None
    excluded_days: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HouseSettings:
    """Everything the learner takes from the ``house_*`` settings.

    Parameters
    ----------
    facts
        The stated facts.
    bounds
        The bounds on learned quantities.
    learning
        The learning options.
    priors
        The fit's priors and constraints.
    constraints
        The fact and bound settings that shaped the priors, ``{setting: value}``.
    told
        The rough values the facts imply.
    """

    facts: HouseFacts
    bounds: HouseBounds
    learning: LearnSettings
    priors: Priors
    constraints: dict[str, float | int | str]
    told: FactEstimate


def _bound(config: Mapping[str, object], name: str, allowed: tuple[float, float]) -> float | None:
    value = config.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SettingError(name, f"{value!r} is not a number")
    if not allowed[0] <= float(value) <= allowed[1]:
        raise SettingError(name, f"{value:g} is outside {allowed[0]:g}-{allowed[1]:g}")
    return float(value)


def read_bounds(config: Mapping[str, object]) -> HouseBounds:
    """Read and validate the bound settings.

    Raises
    ------
    SettingError
        When a bound is not a number, lies outside its allowed range, or a minimum
        exceeds its maximum.
    """
    ranges: dict[str, tuple[float | None, float | None]] = {}
    for spec in BOUND_SETTINGS:
        low = _bound(config, spec.low_name, spec.allowed)
        high = _bound(config, spec.high_name, spec.allowed)
        if low is not None and high is not None and low > high:
            raise SettingError(spec.low_name, f"{low:g} exceeds {spec.high_name} ({high:g})")
        if low is not None or high is not None:
            ranges[spec.low_name] = (low, high)
    return HouseBounds(ranges)


def _option(config: Mapping[str, object], name: str, *, whole: bool) -> float | None:
    value = config.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise SettingError(name, f"{value!r} is not a number")
    if whole and value != int(value):
        raise SettingError(name, f"{value:g} is not a whole number of days")
    low, high = LEARN_RANGES[name]
    if not low <= float(value) <= high:
        raise SettingError(name, f"{value:g} is outside {low:g}-{high:g}")
    return float(value)


def _days(config: Mapping[str, object]) -> tuple[str, ...]:
    name = "house_learn_excluded_days"
    value = config.get(name)
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise SettingError(name, "is not a list of days")
    if len(value) > MAX_EXCLUDED_DAYS:
        raise SettingError(name, f"{len(value)} days, at most {MAX_EXCLUDED_DAYS}")
    out = set()
    for item in value:
        try:
            if not isinstance(item, str) or len(item) != 10:
                raise ValueError(item)
            out.add(date.fromisoformat(item).isoformat())
        except ValueError:
            raise SettingError(name, f"{item!r} is not a YYYY-MM-DD date") from None
    return tuple(sorted(out))


def read_learning(config: Mapping[str, object]) -> LearnSettings:
    """Read and validate the learning options.

    Raises
    ------
    SettingError
        When an option is mistyped or out of range, the fit span is shorter than the
        test span plus :data:`MIN_TRAIN_DAYS`, or a left-out day is not a date.
    """
    fit = _option(config, "house_learn_fit_days", whole=True)
    test = _option(config, "house_learn_test_days", whole=True)
    tolerance = _option(config, "house_learn_tolerance_k", whole=False)
    if fit is not None and test is not None and fit < test + MIN_TRAIN_DAYS:
        raise SettingError(
            "house_learn_fit_days",
            f"{fit:g} days is shorter than house_learn_test_days ({test:g}) plus "
            f"{MIN_TRAIN_DAYS} training days",
        )
    return LearnSettings(
        fit_days=fit,
        test_days=None if test is None else int(test),
        tolerance_k=tolerance,
        excluded_days=_days(config),
    )


def _with_facts(priors: Priors, facts: HouseFacts, told: FactEstimate) -> tuple[Priors, set[str]]:
    used: set[str] = set()
    if told.ua_w_per_k is not None:
        priors = priors.with_prior("h_air_out", told.ua_w_per_k, UA_FACT_SD)
        used |= {"house_build_period"}
        used |= {"house_floor_area_m2"} if facts.floor_area_m2 is not None else set()
        used |= {"house_volume_m3"} if facts.volume_m3 is not None else set()
    if told.solar_aperture_m2 is not None:
        sd = max(told.solar_aperture_m2, SOLAR_FACT_MIN_SD_M2)
        priors = priors.with_prior("solar_aperture_m2", told.solar_aperture_m2, sd)
        used |= {"house_window_area_m2"}
        used |= {"house_window_orientation"} if facts.window_orientation is not None else set()
    if told.internal_gain_w is not None:
        sd = max(GAINS_FACT_RELATIVE_SD * told.internal_gain_w, GAINS_FACT_MIN_SD_W)
        priors = priors.with_prior("q_int_w", told.internal_gain_w, sd)
        used |= {"house_occupants"}
    if facts.volume_m3 is not None:
        air = AIR_HEAT_J_PER_M3_K * facts.volume_m3
        if air > priors.params["c_air"].lower:
            priors = priors.restricted("c_air", air, None)
            used |= {"house_volume_m3"}
    return priors, used


def build_priors(facts: HouseFacts, bounds: HouseBounds) -> tuple[Priors, set[str]]:
    """Return the fit's priors and constraints, and the settings that shaped them.

    Parameters
    ----------
    facts
        The stated facts (weak priors, see the module docstring).
    bounds
        The owner's bounds.

    Returns
    -------
    tuple
        The priors (:data:`~ovenbird_sim.identify.building.DEFAULT_PRIORS` when
        nothing is set) and the names of the settings used.

    Raises
    ------
    SettingError
        When a bound cannot hold within the model's hard bounds.
    """
    priors, used = _with_facts(DEFAULT_PRIORS, facts, estimate(facts))
    for spec in BOUND_SETTINGS:
        low, high = bounds.get(spec)
        if low is None and high is None:
            continue
        try:
            if spec.parameter is None:
                priors = priors.with_time_constant(low, high)
            else:
                priors = priors.restricted(spec.parameter, low, high)
        except ConstraintError as exc:
            raise SettingError(spec.low_name, str(exc)) from None
        sides = ((spec.low_name, low), (spec.high_name, high))
        used |= {name for name, value in sides if value is not None}
    return priors, used


def unconstrained(priors: Priors) -> Priors:
    """Return ``priors`` without the owner's bounds, pins and time-constant range.

    The prior means and spreads the facts set and the air-capacity floor the volume
    sets are kept: only what :data:`BOUND_SETTINGS` constrains is released.
    """
    params = dict(priors.params)
    for spec in BOUND_SETTINGS:
        if spec.parameter is not None:
            lower, upper = BOUNDS[spec.parameter]
            params[spec.parameter] = replace(params[spec.parameter], lower=lower, upper=upper)
    return Priors(params, fixed=priors.fixed)


def house_settings(config: Mapping[str, object]) -> HouseSettings:
    """Read the facts, bounds and learning options of an effective configuration.

    Parameters
    ----------
    config
        Flat ``field: value`` mapping (``effective`` of ``learner-config.json``).

    Returns
    -------
    HouseSettings
        Facts, bounds, learning options, priors, the constraints in force and the
        values the facts imply.

    Raises
    ------
    SettingError
        For an invalid bound or learning option (facts that are not valid are
        ignored, as :func:`ovenbird_core.housefacts.facts_from_config` does).
    """
    facts = facts_from_config(config)
    bounds = read_bounds(config)
    learning = read_learning(config)
    priors, used = build_priors(facts, bounds)
    order = (*FACT_SETTINGS, *(n for s in BOUND_SETTINGS for n in (s.low_name, s.high_name)))
    constraints: dict[str, float | int | str] = {}
    for name in order:
        value = config.get(name)
        if name in used and isinstance(value, int | float | str) and not isinstance(value, bool):
            constraints[name] = value
    return HouseSettings(facts, bounds, learning, priors, constraints, estimate(facts))


def told_json(told: FactEstimate) -> dict[str, float | None]:
    """Return the fact-based estimates of the insight (rounded; ``None`` when not derivable)."""

    def rounded(value: float | None, digits: int) -> float | None:
        return None if value is None else round(value, digits)

    return {
        "ua_w_per_k": rounded(told.ua_w_per_k, 1),
        "solar_aperture_m2": rounded(told.solar_aperture_m2, 2),
        "internal_gain_w": rounded(told.internal_gain_w, 0),
    }
