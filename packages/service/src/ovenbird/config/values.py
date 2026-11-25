"""Value types of the settings: limits, type aliases, :class:`Issue` and nested models."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import time
from typing import Any, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from ovenbird.config.network import check_topic
from ovenbird.config.validation.quiet import check_clock_time, check_window
from ovenbird_core import MqttSignal
from ovenbird_core.control import (
    HeatingCurve,
    QuietWindow,
)
from ovenbird_core.inputs import mqtt_signal

ENTITY_ID_RE: Final = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
TEMPERATURE_DOMAINS: Final = ("sensor", "input_number", "number")
CELSIUS: Final = "°C"
SNAPSHOT_NAME: Final = "history.snapshot.db"
NTFY_TOPIC_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
MIN_OPERATE_TOKEN: Final = 32
MIN_CURVE_POINTS: Final = 2
MAX_CURVE_POINTS: Final = 6
CURVE_OUTSIDE_MIN_C: Final = -30.0
CURVE_OUTSIDE_MAX_C: Final = 30.0
MAX_QUIET_WINDOWS: Final = 4
LOCATION_DECIMALS: Final = 2
MIN_INTEGRAL_TIME_S: Final = 1800.0
MAX_MQTT_INPUTS: Final = 32
MAX_MQTT_INPUT_TEXT: Final = 256
MAX_CLOCK_SPEED: Final = 1000.0


type ControlModeName = Literal["off", "shadow", "auto"]
type RoomProfileName = Literal["periodic", "on_change"]
type EmitterName = Literal["screed_floor", "radiators", "mixed"]
type SetpointRegister = Literal["setcurves_target_high", "z1_heat_request_temperature"]

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type LocationSource = Literal["ha_zone_home", "manual", "browser"]
type NotifySeverity = Literal["info", "warning", "critical"]
type NotifyLanguage = Literal["en", "nl"]
type CurvePairs = tuple[tuple[float, float], ...]


class ConfigError(ValueError):
    """The settings are invalid; the message is safe to log (no input values)."""


@dataclass(frozen=True, slots=True)
class Issue:
    """One violated cross-field rule.

    Parameters
    ----------
    field
        Field the rule is reported on; ``None`` for the configuration as a whole.
    code
        Stable code (see ``docs/api-v1.md``).
    message
        English explanation without secret values.
    params
        Values the UI renders the message from.
    """

    field: str | None
    code: str
    message: str
    params: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
            "params": self.params,
        }


def curve_from_pairs(pairs: CurvePairs) -> HeatingCurve:
    """Return the heating curve of ``(outside_c, water_c)`` pairs."""
    return HeatingCurve.of(*pairs)


class QuietWindowSetting(BaseModel):
    """A daily quiet-mode window as configured (``end`` before ``start`` wraps midnight).

    Parameters
    ----------
    start, end
        Local times ``HH:MM``.
    level
        Quiet level 1-3.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: str
    end: str
    level: int = Field(ge=1, le=3)

    @field_validator("start", "end")
    @classmethod
    def _clock_time(cls, value: str) -> str:
        return check_clock_time(value)

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        check_window(self.start, self.end)
        return self

    def to_core(self) -> QuietWindow:
        """Return the controller's window."""
        return QuietWindow(time.fromisoformat(self.start), time.fromisoformat(self.end), self.level)


class MqttInput(BaseModel):
    """A plain MQTT topic read as a numeric signal (e.g. a mirrored room temperature).

    Parameters
    ----------
    topic
        Full topic, without wildcards; at most 256 characters.
    signal
        Signal id; defaults to ``mqtt/<topic>``; at most 256 characters.
    unit
        Unit of the value.
    minimum, maximum
        Inclusive plausibility range: finite, ``minimum`` not above ``maximum``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str = Field(max_length=MAX_MQTT_INPUT_TEXT)
    signal: str | None = Field(default=None, max_length=MAX_MQTT_INPUT_TEXT)
    unit: str | None = Field(default=None, max_length=MAX_MQTT_INPUT_TEXT)
    minimum: float | None = None
    maximum: float | None = None

    @field_validator("topic")
    @classmethod
    def _valid_topic(cls, value: str) -> str:
        return check_topic(value, "topic")

    @model_validator(mode="after")
    def _valid_bounds(self) -> Self:
        bounds = [value for value in (self.minimum, self.maximum) if value is not None]
        if not all(math.isfinite(value) for value in bounds):
            raise PydanticCustomError("input_bounds", "the plausibility bounds must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise PydanticCustomError(
                "input_bounds", "the plausibility minimum is above the maximum"
            )
        return self

    @property
    def signal_id(self) -> str:
        """Signal id the readings get."""
        return self.signal or mqtt_signal(self.topic)

    def to_core(self) -> MqttSignal:
        """Return the core's parser specification for this topic."""
        return MqttSignal(self.signal_id, self.unit, self.minimum, self.maximum)


def pick[T](value: T | None, preset: T) -> T:
    """Return ``value``, or ``preset`` when it is unset."""
    return preset if value is None else value
