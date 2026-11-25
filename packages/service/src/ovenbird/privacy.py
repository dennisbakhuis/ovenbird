"""Former home of :mod:`ovenbird.system.privacy`; re-exports its names for one release."""

from ovenbird.system.privacy import (
    ADDRESS,
    FROM_SOURCE,
    IPV4,
    IPV6,
    public_name,
    scrub_addresses,
)

__all__ = [
    "ADDRESS",
    "FROM_SOURCE",
    "IPV4",
    "IPV6",
    "public_name",
    "scrub_addresses",
]
