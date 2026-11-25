"""House settings: the model's floor area (``house_*``) and whether the pump heats hot water."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.config.fromcore import FeatureSettings

type HotWater = Literal["auto", "on", "off"]


class HouseSettings(FeatureSettings):
    """House model (``house_*``) and the hot-water display (``hot_water``)."""

    house_floor_area_m2: float | None = Field(default=None, gt=0.0, le=10_000.0)
    hot_water: HotWater = "auto"
