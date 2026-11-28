"""Settings of the installation itself: broker, Home Assistant, HTTP, access and clock.

They have no feature package of their own; the feature settings live with their
feature (:mod:`ovenbird.control.settings`, :mod:`ovenbird.stove.settings`, ...).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import NoDecode

from ovenbird.config.fromcore import FeatureSettings
from ovenbird.config.network import check_topic, normalise_origin
from ovenbird.config.sources import (
    DEFAULT_DATA_DIR,
    DEFAULT_HTTP_PORT,
    DEFAULT_UI_DIR,
    split_list,
)
from ovenbird.config.validation.access import check_operate_token
from ovenbird.config.validation.ha import check_entities, check_ha_url
from ovenbird.config.values import MAX_CLOCK_SPEED, MAX_MQTT_INPUTS, LogLevel, MqttInput
from ovenbird_core import DEFAULT_BASE


class InstallationSettings(FeatureSettings):
    """Broker, Home Assistant, HTTP, data directory and logging of the installation."""

    mqtt_host: str = "localhost"
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_tls: bool = False
    mqtt_ca_file: Path | None = None
    mqtt_client_id: str | None = None
    heishamon_base: str = DEFAULT_BASE
    mqtt_inputs: tuple[MqttInput, ...] = Field(default=(), max_length=MAX_MQTT_INPUTS)
    ha_url: str | None = None
    ha_token: SecretStr | None = None
    ha_entities: Annotated[tuple[str, ...], NoDecode] = ()
    data_dir: Path = DEFAULT_DATA_DIR
    ui_dir: Path = DEFAULT_UI_DIR
    http_host: str = "127.0.0.1"
    http_port: int = Field(default=DEFAULT_HTTP_PORT, ge=0, le=65535)
    admin_username: str = Field(default="admin", min_length=1)
    admin_password: SecretStr | None = None
    http_allowed_origins: Annotated[tuple[str, ...], NoDecode] = ()
    log_level: LogLevel = "INFO"
    ingress: bool | None = None

    @field_validator("heishamon_base")
    @classmethod
    def _valid_base(cls, value: str) -> str:
        """Check the HeishaMon base topic."""
        return check_topic(value, "heishamon_base")

    @field_validator("ha_entities", mode="before")
    @classmethod
    def _split_entities(cls, value: Any) -> Any:
        """Split a delimited entity list into items; an unset value is empty."""
        return () if value is None else split_list(value)

    @field_validator("ha_entities")
    @classmethod
    def _valid_entities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Check the Home Assistant entity ids."""
        return check_entities(value)

    @field_validator("http_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        """Split a delimited origin list into items; an unset value is empty."""
        return () if value is None else split_list(value)

    @field_validator("http_allowed_origins")
    @classmethod
    def _valid_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Normalise the allowed origins and drop duplicates."""
        return tuple(dict.fromkeys(normalise_origin(origin) for origin in value))

    @field_validator("mqtt_username", mode="before")
    @classmethod
    def _empty_username_is_unset(cls, value: Any) -> Any:
        """Treat a blank MQTT username as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ha_url")
    @classmethod
    def _valid_ha_url(cls, value: str | None) -> str | None:
        """Check the Home Assistant URL."""
        return check_ha_url(value)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_level(cls, value: Any) -> Any:
        """Upper-case the log level."""
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator(
        "mqtt_password",
        "ha_token",
        "admin_password",
        mode="before",
    )
    @classmethod
    def _empty_secret_is_unset(cls, value: Any) -> Any:
        """Treat a blank secret as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class AccessSettings(FeatureSettings):
    """Operate token and the configuration seed."""

    operate_token: SecretStr | None = None
    config_seed: Path | None = None

    @field_validator("operate_token", mode="before")
    @classmethod
    def _empty_token_is_unset(cls, value: Any) -> Any:
        """Treat an empty operate token as unset."""
        if isinstance(value, str) and not value:
            return None
        return value

    @field_validator("operate_token")
    @classmethod
    def _long_token(cls, value: SecretStr | None) -> SecretStr | None:
        """Check the operate token is long enough."""
        return check_operate_token(value)


class SimulationSettings(FeatureSettings):
    """Simulation mode and the service clock."""

    simulation: bool = False
    clock_speed: float = Field(default=1.0, gt=0.0, le=MAX_CLOCK_SPEED)
    clock_start: datetime | None = None

    @field_validator("clock_start")
    @classmethod
    def _aware_start(cls, value: datetime | None) -> datetime | None:
        """Make the clock start timezone-aware, as UTC."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
