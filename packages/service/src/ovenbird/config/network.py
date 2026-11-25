"""Hosts, brokers, origins and topics: normalisation and the loopback checks."""

from __future__ import annotations

import ipaddress
from typing import Final
from urllib.parse import urlsplit

LOOPBACK_NAMES: Final = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})
WILDCARDS: Final = frozenset("+#")
DEFAULT_PORTS: Final = {"http": 80, "https": 443}
DEV_BROKER_NAMES: Final = frozenset({"mosquitto"})


def is_loopback(host: str) -> bool:
    """Whether ``host`` names a loopback interface only.

    Parameters
    ----------
    host
        Bind address or host name.

    Returns
    -------
    bool
        ``True`` for ``localhost`` and loopback IP addresses; ``False`` for wildcard
        addresses, other names and other IPs.
    """
    if host.strip().lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def is_simulation_broker(host: str) -> bool:
    """Whether ``host`` may be used in simulation mode: loopback or the dev stack's broker.

    Parameters
    ----------
    host
        Broker host, optionally ``host:port``.

    Returns
    -------
    bool
        ``True`` for loopback names and addresses and the dev compose service names
        (:data:`DEV_BROKER_NAMES`); ``False`` for everything else.
    """
    try:
        name = normalise_broker(host)
    except ValueError:
        return False
    if name.startswith("["):
        name = name[1 : name.index("]")]
    elif name.count(":") == 1:
        name = name.partition(":")[0]
    return name in DEV_BROKER_NAMES or is_loopback(name)


def check_topic(topic: str, what: str) -> str:
    """Return ``topic`` when it has no wildcards, control characters or outer slashes."""
    if not topic or topic != topic.strip():
        raise ValueError(f"{what} must be a non-empty topic without surrounding spaces")
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in topic):
        raise ValueError(f"{what} must not contain control characters")
    if WILDCARDS & set(topic):
        raise ValueError(f"{what} must not contain MQTT wildcards")
    if topic.startswith("/") or topic.endswith("/"):
        raise ValueError(f"{what} must not start or end with '/'")
    return topic


def normalise_origin(raw: str) -> str:
    """Return ``scheme://host[:port]`` in lower case, without a default port.

    Parameters
    ----------
    raw
        An origin such as ``https://ha.example:8123``.

    Returns
    -------
    str
        The normalised origin.

    Raises
    ------
    ValueError
        When ``raw`` is not an http(s) origin without path, query or credentials.
    """
    parts = urlsplit(raw.strip())
    if parts.scheme.lower() not in DEFAULT_PORTS or not parts.hostname:
        raise ValueError("an allowed origin must be an http(s) origin")
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username:
        raise ValueError("an allowed origin must not have a path, query or credentials")
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    if port is None or port == DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def normalise_broker(entry: str) -> str:
    """Return a broker allowlist entry as lower-case ``host`` or ``host:port``.

    IPv6 addresses with a port are written ``[addr]:port``.

    Raises
    ------
    ValueError
        When the entry is empty, has a scheme, a path, credentials or a wildcard,
        or a bad port.
    """
    text = entry.strip().lower()
    if not text or any(char in text for char in "/*@ +#"):
        raise ValueError("a command broker must be a plain host or host:port")
    if text.startswith("["):
        host, _, rest = text.partition("]")
        host += "]"
        port = rest.removeprefix(":") if rest.startswith(":") else None
        if rest and port is None:
            raise ValueError("a command broker must be a plain host or host:port")
    elif text.count(":") == 1:
        host, _, port = text.partition(":")
    else:
        host, port = text, None
    if port is None:
        return host
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError("a command broker port must be within 1..65535")
    return f"{host}:{int(port)}"
