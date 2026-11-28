from __future__ import annotations

import math
from dataclasses import MISSING, dataclass, field, fields

import pytest

from ovenbird_core.control import (
    CyclingConfig,
    OvenbirdConfig,
    PumpDutyConfig,
    QuietModeConfig,
    RoomFeedbackConfig,
    RoomSensorProfile,
    SafetyLimits,
    SetpointStageConfig,
    StartRampConfig,
    StoveConfig,
)
from ovenbird_core.setting import (
    SettingSpec,
    check_settings,
    default_of,
    setting,
    setting_metadata,
    spec,
    specs,
)

CONFIGS = (
    CyclingConfig,
    OvenbirdConfig,
    PumpDutyConfig,
    QuietModeConfig,
    RoomFeedbackConfig,
    RoomSensorProfile,
    SafetyLimits,
    SetpointStageConfig,
    StartRampConfig,
    StoveConfig,
)


@dataclass(frozen=True, slots=True)
class Sample:
    """Sample config with one required and three optional bounded settings."""

    limit: float = field(metadata=setting_metadata(doc="Required.", gt=0.0, le=5.0, unit="K"))
    level: int = setting(2, ge=1, le=3, doc="Level.")
    gain: float | None = setting(None, ge=0.0, lt=1.0, doc="Optional.")
    flag: bool = setting(True, doc="Flag.")

    def __post_init__(self) -> None:
        """Validate the settings against their bounds."""
        check_settings(self)


def test_specs_follow_field_order() -> None:
    """Setting specs follow field order, give defaults and reject unknown names and other types."""
    assert list(specs(Sample)) == ["limit", "level", "gain", "flag"]
    assert spec(Sample, "limit") == SettingSpec(doc="Required.", unit="K", gt=0.0, le=5.0)
    assert default_of(Sample, "level") == 2
    assert default_of(Sample, "limit") is MISSING
    with pytest.raises(KeyError):
        spec(Sample, "missing")
    with pytest.raises(TypeError):
        specs(int)


def test_interval_text() -> None:
    """The interval text shows open and closed bounds and the unit."""
    assert spec(Sample, "limit").interval() == "(0, 5] K"
    assert spec(Sample, "level").interval() == "[1, 3]"
    assert spec(Sample, "gain").interval() == "[0, 1)"
    assert SettingSpec(doc="x", gt=0.0).interval() == "(0, inf)"
    assert not spec(Sample, "flag").bounded


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 0.0}, r"Sample\.limit must be in \(0, 5\] K"),
        ({"limit": 5.5}, "limit"),
        ({"limit": math.nan}, r"limit must be finite"),
        ({"limit": 1.0, "level": 4}, "level"),
        ({"limit": 1.0, "gain": 1.0}, "gain"),
    ],
)
def test_check_settings_rejects(kwargs: dict[str, float], message: str) -> None:
    """Out-of-range and non-finite values raise ValueError naming the setting."""
    with pytest.raises(ValueError, match=message):
        Sample(**kwargs)  # type: ignore[arg-type]


def test_check_settings_accepts_the_edges() -> None:
    """Values exactly on an inclusive bound are accepted."""
    Sample(limit=5.0, level=3, gain=0.0)
    Sample(limit=1e-9, level=1, gain=None)


@pytest.mark.parametrize("owner", CONFIGS)
def test_every_setting_documents_itself_and_admits_its_default(owner: type) -> None:
    """Every config setting has a sentence of documentation and a default inside its bounds."""
    found = specs(owner)
    assert found
    for name, item in found.items():
        assert item.doc.strip().endswith("."), name
        value = default_of(owner, name)
        if item.bounded and isinstance(value, int | float) and not isinstance(value, bool):
            assert item.admits(value), name


NOT_SETTINGS = frozenset({"direct_heating_mode"})


def test_every_number_of_a_config_is_a_setting() -> None:
    """Every numeric field of the config classes is declared as a setting."""
    for owner in CONFIGS:
        names = set(specs(owner))
        for item in fields(owner):
            if item.type in ("float", "float | None", "int"):
                assert item.name in names or item.name in NOT_SETTINGS, (
                    f"{owner.__name__}.{item.name}"
                )
