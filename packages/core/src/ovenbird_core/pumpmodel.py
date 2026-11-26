"""Model profiles: what a heat pump does by design, keyed by its HeishaMon ID bytes.

HeishaMon identifies the unit only by ``main/Heat_Pump_Model``, ten bytes in hex. A
profile holds facts from Panasonic's own service manuals for a model whose bytes were
verified on a real unit; any other unit is generic and nothing is assumed about it.

The deice rules (Panasonic service manual PAPAMY2110029CE, WH-MXC09J3E8/WH-MXC12J9E8,
14.2.2 "Deice Operation"): deice mode 1 is the reverse-cycle defrost with the water
pump running; deice mode 2 is a hot-gas-bypass defrost with the water pump off by
design for most of it, at most 30 min. The unit picks mode 2 when the water inlet is
below 27 °C, or below 60 °C with the outdoor air below -10 °C (a rule on the unit's
outlet sensor 2 is not visible through HeishaMon). The manual covers WH-MXC09J3E8 too;
its ID bytes can be added once verified on a real unit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

MXC_MANUAL: Final = (
    "Panasonic service manual PAPAMY2110029CE (WH-MXC09J3E8/WH-MXC12J9E8), 14.2.2 Deice Operation"
)

type DeiceMode = Literal[1, 2]


@dataclass(frozen=True, slots=True)
class DeiceSpec:
    """When a model defrosts with its water pump off (deice mode 2).

    Parameters
    ----------
    mode2_inlet_below_c
        Mode 2 when the water inlet is below this.
    mode2_inlet_cold_below_c
        Mode 2 when the water inlet is below this and the outdoor air below
        ``mode2_outside_below_c``.
    mode2_outside_below_c
        Outdoor temperature of the cold rule.
    mode2_max_s
        Longest mode 2 defrost by design.
    """

    mode2_inlet_below_c: float = 27.0
    mode2_inlet_cold_below_c: float = 60.0
    mode2_outside_below_c: float = -10.0
    mode2_max_s: float = 1800.0

    def mode(self, inlet_c: float | None, outside_c: float | None) -> DeiceMode:
        """Return the deice mode the unit picks; mode 1 when the inlet is unknown."""
        if inlet_c is None:
            return 1
        cold = outside_c is not None and outside_c < self.mode2_outside_below_c
        if inlet_c < self.mode2_inlet_below_c or (inlet_c < self.mode2_inlet_cold_below_c and cold):
            return 2
        return 1


@dataclass(frozen=True, slots=True)
class PumpProfile:
    """What one heat pump model does by design.

    Parameters
    ----------
    name
        Model name.
    source
        Where the facts come from (manual and section).
    deice
        Deice rules; ``None`` when unknown.
    """

    name: str
    source: str
    deice: DeiceSpec | None = None

    def to_json(self) -> dict[str, Any]:
        """Return the API form."""
        return {"name": self.name, "source": self.source}


PROFILES: Final[Mapping[str, PumpProfile]] = MappingProxyType(
    {
        "32 D4 0B 88 84 73 90 0C 85 84": PumpProfile("WH-MXC12J9E8", MXC_MANUAL, DeiceSpec()),
    }
)


def profile_for(model: object) -> PumpProfile | None:
    """Return the profile of the ``Heat_Pump_Model`` bytes; ``None`` when unknown or missing."""
    return PROFILES.get(model.strip()) if isinstance(model, str) else None
