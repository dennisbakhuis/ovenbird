"""The controller module keeps every former public name after the core split."""

from __future__ import annotations

import importlib
from typing import Final

OLD_NAMES: Final = (
    "BINDINGS",
    "CELSIUS",
    "CONTROLLER_NAME",
    "CROSSCHECK_HYSTERESIS_K",
    "CROSSCHECK_LEARN_HELD_S",
    "HELD_INTEGRAL_FADE_S",
    "PRE_ROUND_INPUT",
    "REFERENCE_MAX_C",
    "REFERENCE_MIN_C",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_MINUTE",
    "STATS_SIGNAL",
    "TERMS",
    "OvenbirdController",
    "OvenbirdState",
    "RampPhase",
    "StoveExit",
    "StoveSource",
    "StoveTrigger",
    "carry_state",
    "duration_text",
    "liveness_label",
    "room_status",
    "round_half_up",
)


def test_every_former_name_still_resolves() -> None:
    """Each public name of the former single module is importable from it."""
    module = importlib.import_module("ovenbird_core.control.ovenbird")
    missing = [name for name in OLD_NAMES if not hasattr(module, name)]
    assert missing == []
