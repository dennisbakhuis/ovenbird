"""Rules of access: the operate token, the bind address and simulation mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from ovenbird.config.network import DEV_BROKER_NAMES, is_loopback, is_simulation_broker
from ovenbird.config.values import MIN_OPERATE_TOKEN

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


def check_operate_token(value: SecretStr | None) -> SecretStr | None:
    """Return the operate token when it is long enough.

    Raises
    ------
    ValueError
        When it is shorter than :data:`MIN_OPERATE_TOKEN` characters.
    """
    if value is not None and len(value.get_secret_value()) < MIN_OPERATE_TOKEN:
        raise ValueError(f"operate_token must have at least {MIN_OPERATE_TOKEN} characters")
    return value


def check_simulation(settings: Settings) -> None:
    """Check that simulation mode only talks to a loopback or dev-stack broker.

    Raises
    ------
    ValueError
        For another broker, another command broker or the Home Assistant app.
    """
    if not is_simulation_broker(settings.mqtt_host):
        raise ValueError(
            "OVENBIRD_SIMULATION requires a loopback broker or the dev stack's "
            f"{'/'.join(sorted(DEV_BROKER_NAMES))}"
        )
    if any(not is_simulation_broker(entry) for entry in settings.command_brokers):
        raise ValueError(
            "OVENBIRD_SIMULATION forbids command brokers other than loopback or "
            f"{'/'.join(sorted(DEV_BROKER_NAMES))}"
        )
    if settings.ingress_mode:
        raise ValueError("OVENBIRD_SIMULATION cannot run as a Home Assistant app")


def check_bind(settings: Settings) -> None:
    """Refuse a non-loopback bind address without a password (outside ingress).

    Raises
    ------
    ValueError
        When the HTTP server would be reachable without credentials.
    """
    if (
        not is_loopback(settings.http_host)
        and settings.admin_password is None
        and not settings.ingress_mode
    ):
        raise ValueError(
            f"refusing to bind non-loopback address {settings.http_host!r} without "
            "OVENBIRD_ADMIN_PASSWORD"
        )
