"""Rules of the notification settings: the ntfy server and topic and the dead-man URL."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import SecretStr

from ovenbird.config.values import NTFY_TOPIC_RE

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings


def check_ntfy_url(value: str | None) -> str | None:
    """Return the ntfy server URL without trailing slash; refuse credentials and queries.

    Raises
    ------
    ValueError
        When it is not a plain http(s) URL.
    """
    if value is None:
        return None
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("notify_ntfy_url must be an http(s) URL")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError(
            "notify_ntfy_url must not carry credentials; use notify_ntfy_token instead"
        )
    if parts.query or parts.fragment:
        raise ValueError("notify_ntfy_url must not have a query or fragment")
    return value.strip().rstrip("/")


def check_ntfy_topic(value: SecretStr | None) -> SecretStr | None:
    """Return the ntfy topic when it is 1-64 letters, digits, ``-`` or ``_``.

    Raises
    ------
    ValueError
        Otherwise.
    """
    if value is not None and NTFY_TOPIC_RE.fullmatch(value.get_secret_value()) is None:
        raise ValueError("notify_ntfy_topic must be 1-64 letters, digits, '-' or '_'")
    return value


def check_deadman_url(value: SecretStr | None) -> SecretStr | None:
    """Return the dead-man URL stripped of surrounding spaces.

    Raises
    ------
    ValueError
        When it is not an http(s) URL.
    """
    if value is None:
        return None
    parts = urlsplit(value.get_secret_value().strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("notify_deadman_url must be an http(s) URL")
    return SecretStr(value.get_secret_value().strip())


def check_notify(settings: Settings) -> None:
    """Check that ntfy's URL and topic come together and the dead-man URL is https.

    Raises
    ------
    ValueError
        When one of the rules is broken.
    """
    if (settings.notify_ntfy_url is None) != (settings.notify_ntfy_topic is None):
        raise ValueError("notify_ntfy_url and notify_ntfy_topic must be set together")
    deadman = settings.notify_deadman_url
    if (
        deadman is not None
        and urlsplit(deadman.get_secret_value()).scheme != "https"
        and not settings.notify_deadman_allow_http
    ):
        raise ValueError(
            "notify_deadman_url must be https (set notify_deadman_allow_http to accept http)"
        )
