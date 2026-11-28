"""Notification settings (``notify_*``): ntfy alarms and the dead-man check."""

from __future__ import annotations

from typing import Any

from pydantic import Field, SecretStr, field_validator

from ovenbird.config.fromcore import FeatureSettings
from ovenbird.config.validation.notify import (
    check_deadman_url,
    check_ntfy_topic,
    check_ntfy_url,
)
from ovenbird.config.values import NotifyLanguage, NotifySeverity


class NotifySettings(FeatureSettings):
    """Alarm notifications and the dead-man check (``notify_*``)."""

    notify_ntfy_url: str | None = None
    notify_ntfy_topic: SecretStr | None = None
    notify_ntfy_token: SecretStr | None = None
    notify_min_severity: NotifySeverity = "warning"
    notify_events: bool = False
    notify_deadman_url: SecretStr | None = None
    notify_deadman_interval_s: float = Field(default=300.0, ge=60.0, le=3600.0)
    notify_deadman_allow_http: bool = False
    notify_language: NotifyLanguage = "en"

    @field_validator(
        "notify_ntfy_topic",
        "notify_ntfy_token",
        "notify_deadman_url",
        "notify_ntfy_url",
        mode="before",
    )
    @classmethod
    def _empty_notify_secret_is_unset(cls, value: Any) -> Any:
        """Treat an empty secret as unset."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("notify_ntfy_url")
    @classmethod
    def _valid_ntfy_url(cls, value: str | None) -> str | None:
        """Check the ntfy server URL."""
        return check_ntfy_url(value)

    @field_validator("notify_ntfy_topic")
    @classmethod
    def _valid_ntfy_topic(cls, value: SecretStr | None) -> SecretStr | None:
        """Check the ntfy topic."""
        return check_ntfy_topic(value)

    @field_validator("notify_deadman_url")
    @classmethod
    def _valid_deadman_url(cls, value: SecretStr | None) -> SecretStr | None:
        """Check the dead-man ping URL."""
        return check_deadman_url(value)
