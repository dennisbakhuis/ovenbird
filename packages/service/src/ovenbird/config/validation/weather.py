"""Cross-field rules of the weather location."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird.config.values import Issue

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


def weather_issues(settings: Settings) -> list[Issue]:
    """Return the violated rules of the weather location."""
    has_lat = settings.weather_latitude is not None
    has_lon = settings.weather_longitude is not None
    if has_lat != has_lon:
        field = "weather_longitude" if has_lat else "weather_latitude"
        return [Issue(field, "location_pair", "set both latitude and longitude, or neither")]
    if settings.weather_location_source != "ha_zone_home" and not has_lat:
        return [
            Issue(
                "weather_latitude",
                "location_required",
                "a manual or browser location needs latitude and longitude",
            )
        ]
    return []
