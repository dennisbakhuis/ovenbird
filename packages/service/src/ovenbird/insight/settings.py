"""House settings: facts, bounds on learned values, learner schedule (`house_*`), hot water."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from ovenbird.config.fromcore import FeatureSettings
from ovenbird.config.sources import split_list
from ovenbird.config.validation.house import MAX_EXCLUDED_DAYS, check_excluded_days

type HotWater = Literal["auto", "on", "off"]
type BuildPeriod = Literal[
    "before_1945", "1945_1974", "1975_1991", "1992_2005", "2006_2014", "2015_later"
]
type WindowOrientation = Literal["north", "east", "south", "west", "mixed"]


class HouseSettings(FeatureSettings):
    """House model (``house_*``) and the hot-water display (``hot_water``)."""

    house_floor_area_m2: float | None = Field(default=None, gt=0.0, le=10_000.0)
    house_volume_m3: float | None = Field(default=None, ge=50.0, le=5000.0)
    house_build_period: BuildPeriod | None = None
    house_floor_heating_share: float | None = Field(default=None, ge=0.0, le=1.0)
    house_window_area_m2: float | None = Field(default=None, ge=0.0, le=200.0)
    house_window_orientation: WindowOrientation | None = None
    house_occupants: int | None = Field(default=None, ge=0, le=12)
    house_ua_min_w_per_k: float | None = Field(default=None, ge=30.0, le=1500.0)
    house_ua_max_w_per_k: float | None = Field(default=None, ge=30.0, le=1500.0)
    house_time_constant_min_h: float | None = Field(default=None, ge=5.0, le=500.0)
    house_time_constant_max_h: float | None = Field(default=None, ge=5.0, le=500.0)
    house_solar_aperture_min_m2: float | None = Field(default=None, ge=0.0, le=40.0)
    house_solar_aperture_max_m2: float | None = Field(default=None, ge=0.0, le=40.0)
    house_internal_gain_min_w: float | None = Field(default=None, ge=0.0, le=2000.0)
    house_internal_gain_max_w: float | None = Field(default=None, ge=0.0, le=2000.0)
    house_learn_enabled: bool = True
    house_learn_interval_h: float = Field(default=168.0, ge=24.0, le=720.0)
    house_learn_fit_days: int = Field(default=60, ge=21, le=90)
    house_learn_test_days: int = Field(default=14, ge=7, le=21)
    house_learn_tolerance_k: float = Field(default=0.0, ge=-0.1, le=0.2)
    house_learn_excluded_days: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(), max_length=MAX_EXCLUDED_DAYS
    )
    hot_water: HotWater = "auto"

    @field_validator("house_learn_excluded_days", mode="before")
    @classmethod
    def _split_days(cls, value: Any) -> Any:
        return () if value is None else split_list(value)

    @field_validator("house_learn_excluded_days")
    @classmethod
    def _valid_days(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return check_excluded_days(value)
