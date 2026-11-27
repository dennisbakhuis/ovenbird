"""The house facts, bounds and learning settings: ranges, enums, the day list, cross-field rules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ovenbird.config import Settings
from ovenbird.config.validation.house import check_excluded_days
from ovenbird.configstore import ConfigManager
from ovenbird.configstore.effective import merge
from ovenbird.configstore.fields import EDITABLE, FIELDS, schema_payload
from ovenbird.insight import house
from ovenbird.testing import FakeClock

PAIRS = [
    ("house_ua_min_w_per_k", "house_ua_max_w_per_k", 30.0, 1500.0),
    ("house_time_constant_min_h", "house_time_constant_max_h", 5.0, 500.0),
    ("house_solar_aperture_min_m2", "house_solar_aperture_max_m2", 0.0, 40.0),
    ("house_internal_gain_min_w", "house_internal_gain_max_w", 0.0, 2000.0),
]
RANGES = [
    ("house_volume_m3", 50, 5000),
    ("house_window_area_m2", 0, 200),
    ("house_occupants", 0, 12),
    ("house_learn_fit_days", 21, 90),
    ("house_learn_test_days", 7, 21),
    ("house_learn_tolerance_k", -0.1, 0.2),
    *[(name, low, high) for lo, hi, low, high in PAIRS for name in (lo, hi)],
]
NEW_FIELDS = [
    *[name for name, _, _ in RANGES],
    "house_build_period",
    "house_window_orientation",
    "house_learn_excluded_days",
]


@pytest.fixture
def manager(make_settings: Callable[..., Settings]) -> ConfigManager:
    return ConfigManager.open(make_settings(), FakeClock())


def test_defaults(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.house_volume_m3 is None
    assert settings.house_build_period is None
    assert settings.house_ua_min_w_per_k is None
    assert settings.house_learn_fit_days == 60
    assert settings.house_learn_test_days == 14
    assert settings.house_learn_tolerance_k == 0.0
    assert settings.house_learn_excluded_days == ()


@pytest.mark.parametrize(("name", "low", "high"), RANGES)
def test_ranges_accept_the_ends_and_refuse_beyond(
    manager: ConfigManager, name: str, low: float, high: float
) -> None:
    extra = {
        "house_learn_test_days": {"house_learn_fit_days": 90},
        "house_learn_fit_days": {"house_learn_test_days": 7},
    }.get(name, {})
    assert manager.validate({name: low, **extra}).valid, name
    assert manager.validate({name: high, **extra}).valid, name
    below = manager.validate({name: low - 1})
    assert [e.code for e in below.errors] == ["below_min"]
    above = manager.validate({name: high + 1})
    assert [e.code for e in above.errors] == ["above_max"]


@pytest.mark.parametrize(
    ("name", "good", "bad"),
    [
        ("house_build_period", "1975_1991", "1980"),
        ("house_window_orientation", "mixed", "up"),
    ],
)
def test_enums(manager: ConfigManager, name: str, good: str, bad: str) -> None:
    assert manager.validate({name: good}).valid
    assert [e.code for e in manager.validate({name: bad}).errors] == ["not_allowed"]


def test_occupants_are_whole(manager: ConfigManager) -> None:
    assert not manager.validate({"house_occupants": 2.5}).valid


def test_the_fields_are_editable_and_grouped() -> None:
    for name in NEW_FIELDS:
        assert name in EDITABLE
    groups = {FIELDS[name].group for name in FIELDS if name.startswith("house_")}
    assert groups == {"house", "house_bounds", "house_learning"}
    assert FIELDS["house_ua_min_w_per_k"].group == "house_bounds"
    assert FIELDS["house_volume_m3"].tier.value == "advanced"
    assert FIELDS["house_build_period"].tier.value == "basic"
    assert "house_floor_heating_share" not in FIELDS
    assert "house_floor_heating_share" not in Settings.model_fields


def test_a_stored_floor_heating_share_is_ignored(
    make_settings: Callable[..., Settings], caplog: pytest.LogCaptureFixture
) -> None:
    doc = {"house_floor_heating_share": 0.6, "house_occupants": 2}
    with caplog.at_level("WARNING"):
        merged = merge(make_settings(), {}, doc)
    assert merged.house_occupants == 2
    assert not hasattr(merged, "house_floor_heating_share")
    assert "house_floor_heating_share" in caplog.text


def test_a_new_floor_heating_share_is_an_unknown_field(manager: ConfigManager) -> None:
    result = manager.validate({"house_floor_heating_share": 0.6})
    assert [e.code for e in result.errors] == ["unknown_field"]


def test_schema_lists_the_groups_in_order(make_settings: Callable[..., Settings]) -> None:
    payload = schema_payload(make_settings())
    ids = [group["id"] for group in payload["groups"]]
    assert ids.index("house") < ids.index("house_bounds") < ids.index("house_learning")
    days = payload["fields"]["house_learn_excluded_days"]
    assert days["type"] == "dates"
    assert days["max_items"] == 60
    assert payload["fields"]["house_build_period"]["options"][0] == "before_1945"
    assert "house_floor_heating_share" not in payload["fields"]


@pytest.mark.parametrize(("low", "high", "_lo", "_hi"), PAIRS)
def test_a_minimum_above_the_maximum_names_both_fields(
    manager: ConfigManager, low: str, high: str, _lo: float, _hi: float
) -> None:
    result = manager.validate({low: _lo + 10, high: _lo + 5})
    (issue,) = result.errors
    assert issue.code == "house_bounds_order"
    assert issue.field == high
    assert issue.params["min_field"] == low
    assert issue.params["max_field"] == high
    assert low in issue.message
    assert high in issue.message


@pytest.mark.parametrize(("low", "high", "_lo", "_hi"), PAIRS)
def test_equal_bounds_pin_and_one_side_is_enough(
    manager: ConfigManager, low: str, high: str, _lo: float, _hi: float
) -> None:
    assert manager.validate({low: _lo + 10, high: _lo + 10}).valid
    assert manager.validate({low: _lo + 10}).valid
    assert manager.validate({high: _lo + 10}).valid


def test_the_fit_window_needs_eight_days_beyond_the_test_window(manager: ConfigManager) -> None:
    result = manager.validate({"house_learn_fit_days": 21, "house_learn_test_days": 14})
    (issue,) = result.errors
    assert (issue.field, issue.code) == ("house_learn_fit_days", "house_fit_days_short")
    assert issue.params == {"fit_days": 21, "test_days": 14, "min": 22}
    assert manager.validate({"house_learn_fit_days": 22, "house_learn_test_days": 14}).valid
    assert manager.validate({"house_learn_test_days": 21}).valid


def test_excluded_days_are_sorted_on_save(manager: ConfigManager) -> None:
    today = datetime.now(UTC).date()
    days = [(today - timedelta(days=n)).isoformat() for n in (3, 40, 10)]
    result = manager.validate({"house_learn_excluded_days": days})
    assert result.valid
    assert result.doc["house_learn_excluded_days"] == sorted(days)
    assert result.effective["house_learn_excluded_days"] == sorted(days)


@pytest.mark.parametrize(
    ("days", "code"),
    [
        (["2026-13-01"], "date_format"),
        (["27-11-2026"], "date_format"),
        (["2026-1-5"], "date_format"),
        (["tomorrow"], "date_format"),
        (["2026-11-01", "2026-11-01"], "date_repeated"),
        ([(datetime.now(UTC).date() + timedelta(days=2)).isoformat()], "date_future"),
    ],
)
def test_excluded_day_errors(manager: ConfigManager, days: list[str], code: str) -> None:
    result = manager.validate({"house_learn_excluded_days": days})
    assert [(e.field, e.code) for e in result.errors] == [("house_learn_excluded_days", code)]


def test_excluded_days_allow_tomorrow_and_at_most_sixty(manager: ConfigManager) -> None:
    today = datetime.now(UTC).date()
    tomorrow = (today + timedelta(days=1)).isoformat()
    assert manager.validate({"house_learn_excluded_days": [tomorrow]}).valid
    many = [(today - timedelta(days=n)).isoformat() for n in range(61)]
    assert manager.validate({"house_learn_excluded_days": many[:60]}).valid
    result = manager.validate({"house_learn_excluded_days": many})
    assert [e.code for e in result.errors] == ["too_many"]


def test_check_excluded_days_uses_the_given_date() -> None:
    today = date(2026, 11, 27)
    assert check_excluded_days(("2026-11-28", "2026-01-02"), today) == ("2026-01-02", "2026-11-28")
    with pytest.raises(ValueError, match="future"):
        check_excluded_days(("2026-11-29",), today)


def test_the_environment_list_is_split(
    make_settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OVENBIRD_HOUSE_LEARN_EXCLUDED_DAYS", "2026-01-05, 2026-01-02")
    assert make_settings().house_learn_excluded_days == ("2026-01-02", "2026-01-05")


def test_the_learner_config_carries_every_house_field(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(
        house_volume_m3=420.0,
        house_build_period="1992_2005",
        house_ua_min_w_per_k=200.0,
        house_ua_max_w_per_k=200.0,
        house_learn_excluded_days=("2026-02-01",),
    )
    effective = house.learner_config(settings, 3)["effective"]
    for name in NEW_FIELDS:
        assert name in effective, name
    assert effective["house_volume_m3"] == 420.0
    assert effective["house_build_period"] == "1992_2005"
    assert effective["house_ua_min_w_per_k"] == effective["house_ua_max_w_per_k"] == 200.0
    assert effective["house_learn_excluded_days"] == ["2026-02-01"]
    assert effective["house_learn_fit_days"] == 60
    assert effective["house_learn_test_days"] == 14
    assert effective["house_learn_tolerance_k"] == 0.0
    assert effective["house_window_orientation"] is None


def test_settings_construction_refuses_bad_bounds(
    make_settings: Callable[..., Settings],
) -> None:
    kwargs: dict[str, Any] = {"house_ua_min_w_per_k": 300.0, "house_ua_max_w_per_k": 200.0}
    with pytest.raises(ValueError, match="house_ua_min_w_per_k"):
        make_settings(**kwargs)
