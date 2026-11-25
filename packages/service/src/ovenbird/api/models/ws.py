"""Messages of the live WebSocket (``WS api/v1/ws``), ``{"type", "data"}`` each.

They are not HTTP responses, so :func:`ovenbird.api.openapi.contract` adds them to
the schema's components by hand.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ovenbird.api.models.app import Health, Snapshot
from ovenbird.api.models.base import ApiModel
from ovenbird.api.models.control import Decision


class ConfigNotice(ApiModel):
    """A configuration version took effect."""

    version: int | None
    applied_at: str


class SnapshotMessage(ApiModel):
    """The latest snapshot (at most once per snapshot interval)."""

    type: Literal["snapshot"]
    data: Snapshot


class HealthMessage(ApiModel):
    """The health body, whenever it changed."""

    type: Literal["health"]
    data: Health


class DecisionMessage(ApiModel):
    """A new controller decision."""

    type: Literal["decision"]
    data: Decision


class ConfigMessage(ApiModel):
    """A configuration version took effect."""

    type: Literal["config"]
    data: ConfigNotice


ServerMessage = Annotated[
    SnapshotMessage | HealthMessage | DecisionMessage | ConfigMessage, Field(discriminator="type")
]
