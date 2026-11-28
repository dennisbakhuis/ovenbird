"""The house facts: ranges, enums, their group, and the settings 0.6 retired."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.configstore.effective import merge
from ovenbird.configstore.fields import EDITABLE, FIELDS, GROUP_ORDER, schema_payload
from ovenbird.configstore.store import Origin
from ovenbird.testing import FakeClock

RANGES = [
    ("house_volume_m3", 50, 5000),
    ("house_window_area_m2", 0, 200),
    ("house_occupants", 0, 12),
]
FACTS = [
    "house_floor_area_m2",
    "house_volume_m3",
    "house_build_period",
    "house_window_area_m2",
    "house_window_orientation",
    "house_occupants",
]
RETIRED = {
    "house_ua_min_w_per_k": 120.0,
    "house_ua_max_w_per_k": 180.0,
    "house_time_constant_min_h": 20.0,
    "house_time_constant_max_h": 90.0,
    "house_solar_aperture_min_m2": 1.0,
    "house_solar_aperture_max_m2": 4.0,
    "house_internal_gain_min_w": 100.0,
    "house_internal_gain_max_w": 400.0,
    "house_learn_enabled": False,
    "house_learn_interval_h": 72.0,
    "house_learn_fit_days": 45,
    "house_learn_test_days": 10,
    "house_learn_tolerance_k": 0.05,
    "house_learn_excluded_days": ["2026-11-01", "2026-11-02"],
    "control_model_use": "shadow",
    "control_model_max_setback_k": 0.4,
    "control_model_max_preheat_k": 0.2,
    "control_model_horizon_h": 8.0,
    "control_model_max_rmse_k": 0.5,
    "house_floor_heating_share": 0.6,
}


@pytest.fixture
def manager(make_settings: Callable[..., Settings]) -> ConfigManager:
    """Open a configuration manager on the default test settings."""
    return ConfigManager.open(make_settings(), FakeClock())


def test_defaults(make_settings: Callable[..., Settings]) -> None:
    """Every house fact is unset by default."""
    settings = make_settings()
    for name in FACTS:
        assert getattr(settings, name) is None, name


@pytest.mark.parametrize(("name", "low", "high"), RANGES)
def test_ranges_accept_the_ends_and_refuse_beyond(
    manager: ConfigManager, name: str, low: float, high: float
) -> None:
    """A house fact accepts both ends of its range and refuses values just outside."""
    assert manager.validate({name: low}).valid, name
    assert manager.validate({name: high}).valid, name
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
    """Enumerated house facts accept their options and refuse anything else."""
    assert manager.validate({name: good}).valid
    assert [e.code for e in manager.validate({name: bad}).errors] == ["not_allowed"]


def test_occupants_are_whole(manager: ConfigManager) -> None:
    """A fractional number of occupants is invalid."""
    assert not manager.validate({"house_occupants": 2.5}).valid


def test_the_facts_are_editable_in_one_group() -> None:
    """The house facts are editable, share the house group and carry their tiers."""
    for name in FACTS:
        assert name in EDITABLE
    groups = {FIELDS[name].group for name in FIELDS if name.startswith("house_")}
    assert groups == {"house"}
    assert FIELDS["house_volume_m3"].tier.value == "advanced"
    assert FIELDS["house_build_period"].tier.value == "basic"
    assert not {"house_bounds", "house_learning", "model_plan"} & set(GROUP_ORDER)


@pytest.mark.parametrize("name", sorted(RETIRED))
def test_a_retired_setting_is_gone(make_settings: Callable[..., Settings], name: str) -> None:
    """A retired setting is absent from the fields, the settings model and the schema."""
    assert name not in FIELDS
    assert name not in Settings.model_fields
    assert name not in schema_payload(make_settings())["fields"]


@pytest.mark.parametrize("name", sorted(RETIRED))
def test_a_new_retired_setting_is_an_unknown_field(manager: ConfigManager, name: str) -> None:
    """Submitting a retired setting is rejected as an unknown field."""
    result = manager.validate({name: RETIRED[name]})
    assert [e.code for e in result.errors] == ["unknown_field"]


def test_merge_ignores_stored_retired_values(
    make_settings: Callable[..., Settings], caplog: pytest.LogCaptureFixture
) -> None:
    """Merging a stored document drops retired values with a warning and keeps valid ones."""
    doc = {**RETIRED, "house_occupants": 2}
    with caplog.at_level("WARNING"):
        merged = merge(make_settings(), {}, doc)
    assert merged.house_occupants == 2
    for name in RETIRED:
        assert not hasattr(merged, name), name
    assert "house_learn_enabled" in caplog.text


def test_a_store_from_0_5_0_loads_without_the_retired_settings(
    make_settings: Callable[..., Settings],
) -> None:
    """A store written by 0.5.0 reopens with its valid values and without the retired ones."""
    settings = make_settings()
    first = ConfigManager.open(settings, FakeClock())
    first.store.append(
        {**RETIRED, "control_comfort_c": 20.5, "house_floor_area_m2": 120.0},
        actor="admin",
        origin=Origin.UI,
        now_ts=1.0,
    )
    first.close()
    reopened = ConfigManager.open(settings, FakeClock())
    try:
        assert reopened.settings.control_comfort_c == 20.5
        assert reopened.settings.house_floor_area_m2 == 120.0
        assert not reopened.hold.active
        fields = reopened.payload()["fields"]
        for name in RETIRED:
            assert name not in fields, name
            assert not hasattr(reopened.settings, name), name
        assert reopened.validate({"control_comfort_c": 21.0}).valid
    finally:
        reopened.close()


def test_schema_lists_the_house_facts(make_settings: Callable[..., Settings]) -> None:
    """The schema lists the house group and the build period options."""
    payload = schema_payload(make_settings())
    ids = [group["id"] for group in payload["groups"]]
    assert "house" in ids
    assert payload["fields"]["house_build_period"]["options"][0] == "before_1945"
