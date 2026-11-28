"""House settings: the owner's facts (`house_*`), the house basics and the hot-water display."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.config.fromcore import FeatureSettings

type HotWater = Literal["auto", "on", "off"]
type BuildPeriod = Literal[
    "before_1945", "1945_1974", "1975_1991", "1992_2005", "2006_2014", "2015_later"
]
type WindowOrientation = Literal["north", "east", "south", "west", "mixed"]


class HouseSettings(FeatureSettings):
    """House facts (``house_*``), the house basics switch and the hot-water display."""

    house_floor_area_m2: float | None = Field(default=None, gt=0.0, le=10_000.0)
    house_volume_m3: float | None = Field(default=None, ge=50.0, le=5000.0)
    house_build_period: BuildPeriod | None = None
    house_window_area_m2: float | None = Field(default=None, ge=0.0, le=200.0)
    house_window_orientation: WindowOrientation | None = None
    house_occupants: int | None = Field(default=None, ge=0, le=12)
    house_basics_enabled: bool = True
    hot_water: HotWater = "auto"
