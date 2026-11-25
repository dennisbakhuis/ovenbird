"""Home Assistant MQTT discovery definitions (read-only entities).

Only the definitions live here: discovery topics, config payloads and state payloads.
Nothing in this module publishes; the publishing guarantee (exactly one publish call in
the package, in the command adapter) is unchanged, and a discovery publisher has to be
added with its own guard. Every entity is read-only (``binary_sensor`` / ``sensor``):
HA writes go through the custom integration and the HTTP API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from ovenbird import __version__

DISCOVERY_PREFIX: Final = "homeassistant"
NODE_ID: Final = "ovenbird"
STATE_BASE: Final = "ovenbird"
AVAILABILITY_TOPIC: Final = f"{STATE_BASE}/status"


@dataclass(frozen=True, slots=True)
class Entity:
    """One discovery entity.

    Parameters
    ----------
    component
        HA component (``binary_sensor`` or ``sensor``).
    object_id
        Entity id below the node.
    name
        English display name.
    icon
        MDI icon.
    extra
        Further config keys.
    """

    component: str
    object_id: str
    name: str
    icon: str
    extra: tuple[tuple[str, Any], ...] = ()

    @property
    def config_topic(self) -> str:
        """Discovery config topic (retained)."""
        return f"{DISCOVERY_PREFIX}/{self.component}/{NODE_ID}/{self.object_id}/config"

    @property
    def state_topic(self) -> str:
        """State topic."""
        return f"{STATE_BASE}/{self.object_id}/state"

    @property
    def attributes_topic(self) -> str:
        """JSON attributes topic."""
        return f"{STATE_BASE}/{self.object_id}/attributes"

    def config(self) -> dict[str, Any]:
        """Return the discovery config payload."""
        return {
            "name": self.name,
            "unique_id": f"{NODE_ID}_{self.object_id}",
            "object_id": f"{NODE_ID}_{self.object_id}",
            "state_topic": self.state_topic,
            "json_attributes_topic": self.attributes_topic,
            "availability_topic": AVAILABILITY_TOPIC,
            "icon": self.icon,
            "device": {
                "identifiers": [NODE_ID],
                "name": "ovenbird",
                "manufacturer": "ovenbird",
                "model": "heat-pump controller",
                "sw_version": __version__,
            },
            **dict(self.extra),
        }


STOVE_MODE: Final = Entity(
    "binary_sensor",
    "stove_mode",
    "Stove mode",
    "mdi:fireplace",
    (("payload_on", "ON"), ("payload_off", "OFF"), ("entity_category", "diagnostic")),
)
ENTITIES: Final = (STOVE_MODE,)


def stove_state(stove: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Return the state payload and attributes of the stove-mode binary sensor.

    Parameters
    ----------
    stove
        The ``stove`` block of the control status (``None`` without a control loop).

    Returns
    -------
    tuple of str and dict
        ``"ON"``/``"OFF"`` and the attributes (source, trigger, since, back-off).
    """
    if not stove:
        return "OFF", {}
    keys = ("enabled", "source", "trigger", "since", "entry_c", "backoff_k", "exit_c")
    return ("ON" if stove.get("active") else "OFF"), {key: stove.get(key) for key in keys}
