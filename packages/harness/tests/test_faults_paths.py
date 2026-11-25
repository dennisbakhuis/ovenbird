"""``ovenbird_harness.faults`` keeps every former public name after becoming a package."""

from __future__ import annotations

import importlib
from typing import Final

OLD_NAMES: Final = (
    "ABOVE_MAX_K",
    "BAND_K",
    "BrokerDrop",
    "COMFORT_FLOOR_K",
    "CONTROL",
    "CYCLE_S",
    "Check",
    "CommandLost",
    "ConfigApply",
    "DEFROST_TOPIC",
    "DhwRun",
    "ENVELOPE_ALARM",
    "EPSILON",
    "EnvelopeCorrection",
    "FOREIGN_STEP_K",
    "ForeignWriter",
    "HARNESS_ADMIN",
    "HA_LINK_ALARM",
    "HA_SCENARIOS",
    "HOLD_START_S",
    "HOUR",
    "HaLinkDown",
    "HaRereadFails",
    "HeishaMonRestart",
    "MAX_SHIFT_K",
    "ModeChange",
    "OUTSIDE_TOPIC",
    "OvenbirdRestart",
    "PumpSettingWrite",
    "QUIET_ALARM",
    "RESTART_BURST_S",
    "RULE_MARGIN_K",
    "RULE_PERIOD_S",
    "RoomSensorDiesWarm",
    "RoomSensorFailsHigh",
    "RoomSensorSilent",
    "SCENARIOS",
    "SILENT_ALARM",
    "SLACK_S",
    "STOVE_RAMP_TERMS",
    "STUCK_MAX_DROP_K",
    "Scenario",
    "Scheduler",
    "Seen",
    "SetpointAboveMax",
    "StoveEvening",
    "TAIL_S",
    "TICK_CYCLES",
    "TICK_S",
    "TROUBLE",
    "TopicStale",
    "WARMUP_S",
    "expected_authority",
    "seen",
    "verdict",
)


def test_every_former_name_still_resolves() -> None:
    """Each public name of the former single module is importable from the package."""
    module = importlib.import_module("ovenbird_harness.faults")
    missing = [name for name in OLD_NAMES if not hasattr(module, name)]
    assert missing == []
