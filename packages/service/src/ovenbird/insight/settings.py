"""House settings: floor area, learner schedule (`house_*`) and the hot-water display."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.config.fromcore import FeatureSettings

type HotWater = Literal["auto", "on", "off"]


class HouseSettings(FeatureSettings):
    """House model (``house_*``) and the hot-water display (``hot_water``)."""

    house_floor_area_m2: float | None = Field(default=None, gt=0.0, le=10_000.0)
    house_learn_enabled: bool = True
    house_learn_interval_h: float = Field(default=168.0, ge=24.0, le=720.0)
    hot_water: HotWater = "auto"
