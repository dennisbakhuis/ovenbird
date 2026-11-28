from __future__ import annotations

from itertools import pairwise

import pytest

from ovenbird_core.housefacts import (
    BUILD_PERIODS,
    ORIENTATIONS,
    FactEstimate,
    HouseFacts,
    estimate,
    facts_from_config,
    specific_loss_w_per_m2k,
)


def test_nothing_stated_gives_no_estimate() -> None:
    """Empty config gives empty facts and an empty estimate."""
    facts = facts_from_config({})
    assert facts == HouseFacts()
    assert not facts.stated
    assert estimate(facts) == FactEstimate()


def test_config_parsing_reads_every_fact() -> None:
    """Every house fact is read from the config and unrelated keys are ignored."""
    facts = facts_from_config(
        {
            "house_floor_area_m2": 130,
            "house_volume_m3": 340.0,
            "house_build_period": "1975_1991",
            "house_floor_heating_share": 0.6,
            "house_window_area_m2": 22.5,
            "house_window_orientation": "south",
            "house_occupants": 3,
            "control_comfort_c": 21.0,
        }
    )
    assert facts == HouseFacts(130.0, 340.0, "1975_1991", 22.5, "south", 3)
    assert facts.stated


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("house_floor_area_m2", 0.0),
        ("house_floor_area_m2", "120"),
        ("house_floor_area_m2", True),
        ("house_volume_m3", 20.0),
        ("house_volume_m3", float("nan")),
        ("house_build_period", "1900"),
        ("house_build_period", 1960),
        ("house_window_area_m2", -1.0),
        ("house_window_orientation", "up"),
        ("house_occupants", 2.5),
        ("house_occupants", 13),
        ("house_occupants", None),
    ],
)
def test_config_parsing_ignores_bad_values(name: str, value: object) -> None:
    """Out-of-range or wrongly typed values are ignored."""
    assert facts_from_config({name: value}) == HouseFacts()


def test_whole_occupant_count_as_float_is_accepted() -> None:
    """An occupant count given as a whole float is accepted."""
    assert facts_from_config({"house_occupants": 2.0}).occupants == 2


def test_ua_needs_a_size_and_a_period() -> None:
    """The heat-loss coefficient needs size and build period; area and volume agree."""
    assert estimate(HouseFacts(floor_area_m2=120.0)).ua_w_per_k is None
    assert estimate(HouseFacts(build_period="1992_2005")).ua_w_per_k is None
    by_volume = estimate(HouseFacts(volume_m3=312.0, build_period="1992_2005")).ua_w_per_k
    by_area = estimate(HouseFacts(floor_area_m2=120.0, build_period="1992_2005")).ua_w_per_k
    assert by_volume == pytest.approx(by_area)


def test_older_periods_lose_more_heat() -> None:
    """Older build periods have a higher specific loss within plausible bounds."""
    losses = [specific_loss_w_per_m2k(p) for p in BUILD_PERIODS]
    assert losses == sorted(losses, reverse=True)
    assert 3.0 < losses[0] < 5.0
    assert 0.4 < losses[-1] < 1.0


@pytest.mark.parametrize("period", BUILD_PERIODS)
def test_ua_grows_with_area_and_stays_sane(period: str) -> None:
    """The loss coefficient grows linearly with floor area and stays in a plausible W/K range."""
    values = [
        estimate(HouseFacts(floor_area_m2=a, build_period=period)).ua_w_per_k
        for a in (60.0, 120.0, 240.0)
    ]
    assert all(v is not None for v in values)
    small, mid, large = (float(v or 0.0) for v in values)
    assert small < mid < large
    assert mid == pytest.approx(2 * small)
    assert 30.0 < mid < 600.0


def test_volume_refines_only_the_ventilation() -> None:
    """A given volume changes only the ventilation part of the loss."""
    base = HouseFacts(floor_area_m2=100.0, build_period="2006_2014")
    tall = HouseFacts(floor_area_m2=100.0, volume_m3=400.0, build_period="2006_2014")
    low = HouseFacts(floor_area_m2=100.0, volume_m3=200.0, build_period="2006_2014")
    ua = [estimate(f).ua_w_per_k or 0.0 for f in (low, base, tall)]
    assert ua[0] < ua[1] < ua[2]
    ventilation_per_m3 = 1206.0 / 3600.0 * 0.35
    assert ua[2] - ua[0] == pytest.approx(200.0 * ventilation_per_m3)


def test_solar_aperture_from_windows() -> None:
    """Solar aperture follows window area and orientation, south best and north worst."""
    assert estimate(HouseFacts(window_orientation="south")).solar_aperture_m2 is None
    mixed = estimate(HouseFacts(window_area_m2=20.0)).solar_aperture_m2
    assert mixed == pytest.approx(20.0 * 0.65 * 0.3)
    by_side = {
        o: estimate(HouseFacts(window_area_m2=20.0, window_orientation=o)).solar_aperture_m2 or 0.0
        for o in ORIENTATIONS
    }
    assert by_side["south"] > by_side["east"] == by_side["west"] > by_side["north"]
    assert by_side["mixed"] == pytest.approx(mixed)
    double = estimate(HouseFacts(window_area_m2=40.0, window_orientation="south"))
    assert double.solar_aperture_m2 == pytest.approx(2 * by_side["south"])
    assert estimate(HouseFacts(window_area_m2=0.0)).solar_aperture_m2 == 0.0


def test_internal_gains_from_occupants() -> None:
    """Internal gains grow with occupants from a base load and stay below 2 kW."""
    gains = [estimate(HouseFacts(occupants=n)).internal_gain_w or 0.0 for n in range(13)]
    assert gains[0] == pytest.approx(120.0)
    assert gains[2] == pytest.approx(280.0)
    assert all(b > a for a, b in pairwise(gains))
    assert gains[-1] <= 2000.0


def test_a_retired_floor_heating_share_is_ignored() -> None:
    """The retired floor-heating share key is ignored."""
    facts = facts_from_config({"house_floor_heating_share": 0.25, "house_occupants": 2})
    assert facts == HouseFacts(occupants=2)
    assert not hasattr(estimate(facts), "floor_share")


def test_estimate_is_deterministic() -> None:
    """The same facts always give the same estimate."""
    facts = HouseFacts(150.0, 400.0, "1945_1974", 30.0, "west", 4)
    assert estimate(facts) == estimate(facts)
