from __future__ import annotations

import argparse
import math
from typing import Any

import pytest

from ovenbird_core.housefacts import HouseFacts, estimate
from ovenbird_sim.identify.building import (
    BOUNDS,
    DEFAULT_PRIORS,
    LIN_FIELDS,
    LOG_FIELDS,
    PRIOR_MEAN,
    PRIOR_SD,
    ConstraintError,
    ParamPrior,
    Priors,
)
from ovenbird_sim.learn.__main__ import build_parser, options_from_args
from ovenbird_sim.learn.priors import (
    UA_FACT_SD,
    HouseBounds,
    SettingError,
    build_priors,
    house_settings,
    read_bounds,
    read_learning,
)
from ovenbird_sim.learn.run import DEFAULT_LEARN, apply_learning


def priors_of(facts: HouseFacts) -> Priors:
    return build_priors(facts, HouseBounds())[0]


def test_default_priors_are_the_module_constants() -> None:
    for name in (*LOG_FIELDS, *LIN_FIELDS):
        assert DEFAULT_PRIORS.params[name] == ParamPrior(
            PRIOR_MEAN[name], PRIOR_SD[name], *BOUNDS[name]
        )
    assert DEFAULT_PRIORS.pinned == {}
    assert DEFAULT_PRIORS.time_constant_h is None
    assert priors_of(HouseFacts()) == DEFAULT_PRIORS
    assert build_priors(HouseFacts(), HouseBounds())[1] == set()


def test_facts_shape_the_priors() -> None:
    facts = HouseFacts(
        floor_area_m2=120.0,
        volume_m3=1000.0,
        build_period="1992_2005",
        window_area_m2=20.0,
        window_orientation="north",
        occupants=2,
    )
    priors, used = build_priors(facts, HouseBounds())
    told = estimate(facts)
    ua = priors.params["h_air_out"]
    assert (ua.mean, ua.sd) == (told.ua_w_per_k, UA_FACT_SD)
    assert ua.sd >= math.log(2.0)
    solar = priors.params["solar_aperture_m2"]
    assert solar.mean == pytest.approx(20.0 * 0.3 * 0.3)
    assert solar.sd == 2.0
    gains = priors.params["q_int_w"]
    assert (gains.mean, gains.sd) == (280.0, 150.0)
    assert priors.params["h_water_mass"] == DEFAULT_PRIORS.params["h_water_mass"]
    assert priors.fixed == DEFAULT_PRIORS.fixed
    assert priors.params["c_air"].lower == pytest.approx(1206.0 * 1000.0)
    assert priors.params["c_air"].mean == PRIOR_MEAN["c_air"]
    assert priors.pinned == {}
    assert used == {
        "house_floor_area_m2",
        "house_volume_m3",
        "house_build_period",
        "house_window_area_m2",
        "house_window_orientation",
        "house_occupants",
    }


def test_facts_that_imply_nothing_leave_the_priors_alone() -> None:
    priors, used = build_priors(
        HouseFacts(floor_area_m2=120.0, window_orientation="south", volume_m3=100.0),
        HouseBounds(),
    )
    assert priors == DEFAULT_PRIORS
    assert used == set()


def test_orientation_moves_only_the_solar_mean() -> None:
    north = priors_of(HouseFacts(window_area_m2=20.0, window_orientation="north"))
    south = priors_of(HouseFacts(window_area_m2=20.0, window_orientation="south"))
    changed = {n for n in north.params if north.params[n] != south.params[n]}
    assert changed == {"solar_aperture_m2"}
    assert south.params["solar_aperture_m2"].mean > north.params["solar_aperture_m2"].mean


def test_constraints_that_cannot_hold_raise() -> None:
    with pytest.raises(ConstraintError, match="outside the model's bounds"):
        DEFAULT_PRIORS.restricted("h_air_out", 2000.0, 3000.0)
    with pytest.raises(ConstraintError, match="above upper bound"):
        DEFAULT_PRIORS.restricted("h_air_out", 300.0, 200.0)
    with pytest.raises(ConstraintError, match="outside the model's bounds"):
        DEFAULT_PRIORS.pin("q_int_w", 5000.0)
    with pytest.raises(ConstraintError, match="time constant"):
        DEFAULT_PRIORS.with_time_constant(60.0, 40.0)
    narrowed = DEFAULT_PRIORS.restricted("c_air", 1.0e8, None)
    with pytest.raises(ConstraintError, match="c_air"):
        narrowed.restricted("c_air", None, 5.0e7)


@pytest.mark.parametrize(
    ("config", "setting"),
    [
        ({"house_ua_min_w_per_k": 500.0, "house_ua_max_w_per_k": 300.0}, "house_ua_min_w_per_k"),
        ({"house_time_constant_max_h": 900.0}, "house_time_constant_max_h"),
        ({"house_solar_aperture_min_m2": "3"}, "house_solar_aperture_min_m2"),
        ({"house_internal_gain_min_w": -5.0}, "house_internal_gain_min_w"),
        ({"house_learn_fit_days": 10}, "house_learn_fit_days"),
        ({"house_learn_test_days": 7.5}, "house_learn_test_days"),
        ({"house_learn_fit_days": 21, "house_learn_test_days": 14}, "house_learn_fit_days"),
        ({"house_learn_tolerance_k": 0.5}, "house_learn_tolerance_k"),
        ({"house_learn_excluded_days": ["2026-02-30"]}, "house_learn_excluded_days"),
        ({"house_learn_excluded_days": "2026-01-01"}, "house_learn_excluded_days"),
        ({"house_learn_excluded_days": ["2026-01-01"] * 61}, "house_learn_excluded_days"),
    ],
)
def test_invalid_settings_name_the_setting(config: dict[str, Any], setting: str) -> None:
    with pytest.raises(SettingError) as raised:
        house_settings(config)
    assert raised.value.setting == setting
    assert setting in str(raised.value)


def test_settings_from_the_effective_configuration() -> None:
    config: dict[str, Any] = {
        "control_comfort_c": 21.0,
        "house_floor_area_m2": 130.0,
        "house_build_period": "1975_1991",
        "house_window_orientation": "south",
        "house_occupants": None,
        "house_ua_min_w_per_k": 150.0,
        "house_ua_max_w_per_k": None,
        "house_time_constant_min_h": 40.0,
        "house_time_constant_max_h": 40.0,
        "house_internal_gain_min_w": 100.0,
        "house_internal_gain_max_w": 100.0,
        "house_learn_fit_days": 45,
        "house_learn_test_days": 10,
        "house_learn_tolerance_k": 0.05,
        "house_learn_excluded_days": ["2026-01-02", "2026-01-01", "2026-01-02"],
    }
    settings = house_settings(config)
    assert settings.constraints == {
        "house_floor_area_m2": 130.0,
        "house_build_period": "1975_1991",
        "house_ua_min_w_per_k": 150.0,
        "house_time_constant_min_h": 40.0,
        "house_time_constant_max_h": 40.0,
        "house_internal_gain_min_w": 100.0,
        "house_internal_gain_max_w": 100.0,
    }
    priors = settings.priors
    assert priors.params["h_air_out"].lower == 150.0
    assert priors.params["h_air_out"].upper == BOUNDS["h_air_out"][1]
    assert priors.pinned == {"q_int_w": 100.0}
    assert priors.time_constant_h == (40.0, 40.0)
    assert settings.told.ua_w_per_k == pytest.approx(130.0 * 2.0434, rel=1e-3)
    learning = settings.learning
    assert (learning.fit_days, learning.test_days, learning.tolerance_k) == (45.0, 10, 0.05)
    assert learning.excluded_days == ("2026-01-01", "2026-01-02")
    assert read_bounds({}) == HouseBounds()
    assert read_learning({}).fit_days is None


def test_cli_flags_win_over_the_configuration() -> None:
    learning = read_learning(
        {"house_learn_fit_days": 30, "house_learn_test_days": 7, "house_learn_tolerance_k": 0.1}
    )
    parser = build_parser()
    base = ["--history", "h.db", "--config", "c.json", "--models", "m"]
    plain = options_from_args(parser.parse_args(base))
    assert plain.explicit == frozenset()
    assert (plain.fit_days, plain.test_days, plain.tolerance_k) == (60.0, 14, 0.0)
    merged = apply_learning(plain, learning)
    assert (merged.fit_days, merged.test_days, merged.tolerance_k) == (30.0, 7, 0.1)
    flagged = options_from_args(parser.parse_args([*base, "--fit-days", "50", "--test-days", "9"]))
    assert flagged.explicit == frozenset({"fit_days", "test_days"})
    kept = apply_learning(flagged, learning)
    assert (kept.fit_days, kept.test_days, kept.tolerance_k) == (50.0, 9, 0.1)
    assert apply_learning(DEFAULT_LEARN, read_learning({})) is DEFAULT_LEARN


def test_parser_has_no_hidden_defaults_for_the_learning_flags() -> None:
    args = build_parser().parse_args(["--history", "h", "--config", "c", "--models", "m"])
    assert isinstance(args, argparse.Namespace)
    assert (args.fit_days, args.test_days, args.tolerance_k) == (None, None, None)
