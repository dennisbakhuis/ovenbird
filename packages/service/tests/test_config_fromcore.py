from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import annotated_types
import pytest
from pydantic import ValidationError

from ovenbird.config.fromcore import CORE_FIELDS, FeatureSettings, core_field, core_source
from ovenbird_core.setting import setting, setting_metadata


class Kind(StrEnum):
    """Toy enumeration used as a core setting type."""

    ONE = "one"
    TWO = "two"


@dataclass(frozen=True, slots=True)
class Toy:
    """Core settings dataclass with bounded fields for exercising ``core_field``."""

    limit: float = field(metadata=setting_metadata(gt=0.0, le=10.0, unit="K", doc="Limit."))
    gain: float = setting(2.0, ge=0.0, le=6.0, unit="K/K", doc="Gain.")
    kind: Kind = setting(Kind.ONE, doc="Kind.")


class ToySettings(FeatureSettings):
    """Service settings whose fields are derived from ``Toy`` via ``core_field``."""

    toy_gain: float = core_field(Toy, "gain")
    toy_gain_unset: float | None = core_field(Toy, "gain", unset=True)
    toy_limit: float | None = core_field(Toy, "limit", unset=True, ge=1.0)
    toy_kind: str = core_field(Toy, "kind")
    toy_plain: int = 3


def test_default_and_bounds_come_from_core() -> None:
    """Service fields inherit default and bounds from the core setting and enforce them."""
    info = ToySettings.model_fields["toy_gain"]
    assert info.default == 2.0
    assert info.metadata == [annotated_types.Ge(0.0), annotated_types.Le(6.0)]
    assert ToySettings.model_fields["toy_gain_unset"].default is None
    assert ToySettings.model_fields["toy_kind"].default == "one"
    assert type(ToySettings.model_fields["toy_kind"].default) is str
    with pytest.raises(ValidationError):
        ToySettings(toy_gain=7.0)


def test_narrowed_bound_replaces_its_side() -> None:
    """A tighter service bound replaces only its own side of the core bound."""
    info = ToySettings.model_fields["toy_limit"]
    assert info.metadata == [annotated_types.Ge(1.0), annotated_types.Le(10.0)]
    source = core_source("toy_limit")
    assert source is not None
    assert source.spec.ge == 1.0
    assert source.spec.gt is None
    assert source.core_spec.gt == 0.0


def test_fields_are_bound_to_their_service_names() -> None:
    """Core fields are registered under the service field names and plain fields are not."""
    assert CORE_FIELDS["toy_gain"].owner is Toy
    assert CORE_FIELDS["toy_gain"].name == "gain"
    assert CORE_FIELDS["toy_gain_unset"].unset
    assert core_source("toy_plain") is None


def test_rejects_a_required_setting_without_unset() -> None:
    """A core setting with no default is refused unless marked unset."""
    with pytest.raises(TypeError, match="no default"):
        core_field(Toy, "limit")


def test_rejects_a_bound_outside_the_core_range() -> None:
    """A service bound wider than the core range is refused."""
    with pytest.raises(ValueError, match="outside the core range"):
        core_field(Toy, "gain", le=8.0)
