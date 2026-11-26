"""Bodies of the pump settings router (:mod:`ovenbird.api.pump_api`)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ovenbird.api.models.base import ApiModel, Number, Scalar, absent
from ovenbird.api.models.control import CommandEvent

type OwnerName = Literal["operator", "controller", "pump"]


class PumpWrite(ApiModel):
    """The last operator write of a setting and how it ended."""

    at: str
    by: str
    from_: int | None = Field(alias="from")
    to: int | None
    status: str | None


class PumpSetting(ApiModel):
    """One row of the pump settings; only the writable rows carry the write keys."""

    id: str
    signal: str
    value: Scalar
    unit: str | None
    label: str | None
    fresh: bool
    age: Number | None
    supported: bool
    access: Literal["read", "write"]
    owner: OwnerName
    command: str = absent()
    min: int = absent()
    max: int = absent()
    last_write: PumpWrite | None = absent()


class PumpProfileInfo(ApiModel):
    """The model profile matched by ``Heat_Pump_Model``."""

    name: str
    source: str


class PumpSettingsPage(ApiModel):
    """``GET pump/settings``: whether writes are possible, the model and its profile, every row."""

    writable: bool
    refusals: list[str]
    model: Scalar
    profile: PumpProfileInfo | None
    settings: list[PumpSetting]


class PumpWriteResult(ApiModel):
    """``202`` of ``POST pump/settings/{id}``: the queued command event."""

    command: CommandEvent
