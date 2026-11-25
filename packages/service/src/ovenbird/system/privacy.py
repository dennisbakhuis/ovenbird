"""Remove addresses and names from text that leaves the service.

Audit names carry the client address (``admin from 192.168.1.20``); the read role
and the diagnostics bundle get them without it (:func:`public_name`), and
:func:`scrub_addresses` replaces every IPv4 or IPv6 address in a string.
"""

from __future__ import annotations

import re
from typing import Final

ADDRESS: Final = "[address]"
IPV4: Final = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6: Final = re.compile(
    r"(?<![\w:])(?:(?:[0-9A-Fa-f]{1,4}:){3,7}[0-9A-Fa-f]{1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*)?::(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4})*)?)"
    r"(?![\w.])"
)
FROM_SOURCE: Final = re.compile(r" from \S+?(?=: |$)")


def scrub_addresses(text: str) -> str:
    """Return ``text`` with every IPv4 and IPv6 address replaced by ``[address]``."""
    return IPV6.sub(ADDRESS, IPV4.sub(ADDRESS, text))


def public_name(name: str | None) -> str | None:
    """Return an audit name without its client address (``admin from 10.0.0.2`` → ``admin``)."""
    if name is None:
        return None
    return FROM_SOURCE.sub("", scrub_addresses(name), count=1)
