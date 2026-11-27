"""Every service field built from a controller setting matches it, and none is missing."""

from __future__ import annotations

import types
from collections import Counter
from enum import Enum
from typing import Annotated, Any, Final, Literal, TypeAliasType, Union, get_args, get_origin
from typing import get_type_hints as hints

import annotated_types
import pytest

from ovenbird.config import Settings
from ovenbird.config.fromcore import CORE_FIELDS, CoreSource
from ovenbird.configstore.fields import FIELDS, unit_of
from ovenbird_core.control import (
    CyclingConfig,
    ModelPlanConfig,
    OutsideSource,
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
from ovenbird_core.control.planner import PlannerConfig
from ovenbird_core.setting import specs

CONFIGS: Final = (
    CyclingConfig,
    ModelPlanConfig,
    OutsideSource,
    OvenbirdConfig,
    PlannerConfig,
    PumpDutyConfig,
    QuietModeConfig,
    RoomFeedbackConfig,
    RoomSensorProfile,
    SafetyLimits,
    SetpointStageConfig,
    StartRampConfig,
    StoveConfig,
)
CORE_ONLY: Final = frozenset(
    {
        (OvenbirdConfig, "plan_max_water_k"),
        (OvenbirdConfig, "compressor_min_hz"),
        (RoomFeedbackConfig, "held_step_max_k"),
        (StoveConfig, "reference_gap_k"),
        (StoveConfig, "fault_step_k"),
        (StoveConfig, "fault_step_window_s"),
        (StoveConfig, "crosscheck_allow_k"),
        (PlannerConfig, "max_setback_k"),
        (PlannerConfig, "max_preheat_k"),
        (PlannerConfig, "gain"),
        (PlannerConfig, "dead_zone_k"),
        (PlannerConfig, "quantum_k"),
        (PlannerConfig, "rate_k_per_slice"),
        (PlannerConfig, "slice_s"),
        (PlannerConfig, "grace_s"),
        (PlannerConfig, "outside_weight"),
        (PlannerConfig, "outside_filter_tau_s"),
        (PlannerConfig, "weather_compensation"),
        (PlannerConfig, "max_outside_mismatch_k"),
    }
)
SWITCHED: Final = frozenset({"control_stove_rise_k"})
BOUNDS: Final = {
    annotated_types.Gt: "gt",
    annotated_types.Ge: "ge",
    annotated_types.Lt: "lt",
    annotated_types.Le: "le",
}


def bound() -> dict[str, CoreSource]:
    return {name: CORE_FIELDS[name] for name in Settings.model_fields if name in CORE_FIELDS}


def split_none(annotation: Any) -> tuple[Any, bool]:
    if get_origin(annotation) in (Union, types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        rest = args[0] if len(args) == 1 else Union[tuple(args)]  # noqa: UP007
        return rest, len(args) < len(get_args(annotation))
    return annotation, False


def normal(annotation: Any) -> Any:
    if isinstance(annotation, TypeAliasType):
        return normal(annotation.__value__)
    if get_origin(annotation) is Annotated:
        return normal(get_args(annotation)[0])
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return ("literal", frozenset(member.value for member in annotation))
    if get_origin(annotation) is Literal:
        return ("literal", frozenset(get_args(annotation)))
    if get_origin(annotation) is tuple:
        return ("tuple", tuple(normal(arg) for arg in get_args(annotation)))
    return annotation


def core_type(source: CoreSource) -> Any:
    return hints(source.owner)[source.name]


@pytest.mark.parametrize("name", sorted(bound()))
def test_annotation_matches_the_core_type(name: str) -> None:
    source = CORE_FIELDS[name]
    service, service_none = split_none(Settings.model_fields[name].annotation)
    core, core_none = split_none(core_type(source))
    assert normal(service) == normal(core)
    if name in SWITCHED:
        assert core_none
        assert not service_none
    else:
        assert service_none == (core_none or source.unset)


@pytest.mark.parametrize("name", sorted(bound()))
def test_default_and_range_come_from_core(name: str) -> None:
    source = CORE_FIELDS[name]
    info = Settings.model_fields[name]
    assert info.default == (None if source.unset else source.default)
    found = {
        BOUNDS[type(item)]: getattr(item, BOUNDS[type(item)])
        for item in info.metadata
        if type(item) in BOUNDS
    }
    offered = source.spec
    assert found == {
        key: value
        for key, value in (
            ("gt", offered.gt),
            ("ge", offered.ge),
            ("lt", offered.lt),
            ("le", offered.le),
        )
        if value is not None
    }


@pytest.mark.parametrize("name", sorted(bound()))
def test_a_narrowed_range_stays_inside_the_core_range(name: str) -> None:
    source = CORE_FIELDS[name]
    offered, core = source.spec, source.core_spec
    for value in (offered.gt, offered.ge, offered.lt, offered.le):
        if value is not None:
            assert core.admits(value) or value in {core.gt, core.ge, core.lt, core.le}


def test_every_core_setting_has_exactly_one_service_field() -> None:
    counts = Counter((source.owner, source.name) for source in bound().values())
    assert all(count == 1 for count in counts.values()), counts
    for owner in CONFIGS:
        for name in specs(owner):
            exposed = (owner, name) in counts
            assert exposed != ((owner, name) in CORE_ONLY), f"{owner.__name__}.{name}"


def test_units_of_core_fields_are_not_repeated() -> None:
    for name, source in bound().items():
        assert name not in FIELDS or FIELDS[name].unit is None, name
        assert unit_of(name) == source.spec.unit
