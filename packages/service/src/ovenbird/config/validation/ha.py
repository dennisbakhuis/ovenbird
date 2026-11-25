"""Rules of the Home Assistant input: its URL, the entity ids, signals and the token pairing."""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from ovenbird.config.values import ENTITY_ID_RE
from ovenbird_core.inputs import attribute_supported, split_ha_signal

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings

URL_SCHEMES = frozenset({"http", "https", "ws", "wss"})


def check_ha_url(value: str | None) -> str | None:
    """Return the HA URL stripped of spaces (``None`` when blank).

    Any host works: Home Assistant itself (``http://homeassistant.local:8123``, plain
    http to a LAN host included), a reverse proxy (``https://ha.example/prefix``) or
    the Supervisor proxy. Credentials in the URL are refused: they would end up in
    logs; the token goes in ``ha_token``.

    Raises
    ------
    ValueError
        When it is not an http(s) or ws(s) URL with a host, or carries credentials,
        a query or a fragment.
    """
    if value is None or not value.strip():
        return None
    text = value.strip()
    parts = urlsplit(text)
    try:
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("ha_url has an invalid port") from None
    if port == 0:
        raise ValueError("ha_url has an invalid port")
    if parts.scheme.lower() not in URL_SCHEMES or not host:
        raise ValueError("ha_url must be an http(s) or ws(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("ha_url must not contain a user name or password; use ha_token")
    if parts.query or parts.fragment:
        raise ValueError("ha_url must not have a query or a fragment")
    return text


def check_entities(value: tuple[str, ...]) -> tuple[str, ...]:
    """Return the entity ids without duplicates.

    Raises
    ------
    ValueError
        When one is not an entity id.
    """
    for entity_id in value:
        if ENTITY_ID_RE.fullmatch(entity_id) is None:
            raise ValueError(f"not an entity id: {entity_id!r}")
    return tuple(dict.fromkeys(value))


def valid_ha_signal(signal: str) -> bool:
    """Whether ``signal`` is ``ha/<entity_id>`` or a supported ``ha/<entity_id>#<attribute>``."""
    parts = split_ha_signal(signal)
    if parts is None:
        return False
    entity_id, attribute = parts
    if ENTITY_ID_RE.fullmatch(entity_id) is None:
        return False
    return attribute is None or attribute_supported(entity_id, attribute)


def check_ha(settings: Settings) -> None:
    """Check that URL and token come together.

    HA needs no entity list: the input follows the ``ha/`` signals of the
    configuration (``ha_entities`` only adds entities to read).

    Raises
    ------
    ValueError
        When one of the rules is broken.
    """
    if settings.ha_url is not None and settings.ha_token is None:
        raise ValueError("ha_url is set but ha_token is missing")
    if settings.ha_token is not None and settings.ha_url is None:
        raise ValueError("ha_token is set but ha_url is missing")
