"""Fault scenarios injected into a full run, each with its expected behaviour.

Each scenario acts on the run at offsets from its start and records the decisions,
command events, alarm transitions and true room temperatures of its window; at the
end every expectation is ``pass`` or ``fail`` (see :mod:`.scenario`). The scenarios
are grouped by family:

``scenario``
    The framework: :class:`Scenario`, :class:`Check`, the decision view
    :class:`Seen` and the helpers the families share.
``link``
    The HeishaMon and broker link (``heishamon_restart``, ``broker_drop``,
    ``topic_stale``).
``pump``
    Pump states (``mode_change``, ``dhw_run``).
``actions``
    Operator actions and restarts (``ovenbird_restart``, ``config_apply``,
    ``pump_setting_write``).
``commands``
    The command path (``foreign_writer``, ``command_lost``, ``setpoint_above_max``,
    ``envelope_correction``).
``stove``
    Wood-stove mode (``stove_evening``).
``room``
    The room temperature (``ha_link_down``, ``room_sensor_silent``,
    ``room_sensor_dies_warm``, ``ha_reread_fails``, ``room_sensor_fails_high``).
``schedule``
    The catalogue :data:`SCENARIOS` and the :class:`Scheduler`.

Every name of the former single module is re-exported here.
"""

from ovenbird_harness.faults.actions import (
    DEFROST_TOPIC,
    HARNESS_ADMIN,
    RESTART_BURST_S,
    ConfigApply,
    OvenbirdRestart,
    PumpSettingWrite,
)
from ovenbird_harness.faults.commands import (
    ABOVE_MAX_K,
    ENVELOPE_ALARM,
    FOREIGN_STEP_K,
    MAX_SHIFT_K,
    OUTSIDE_TOPIC,
    RULE_MARGIN_K,
    RULE_PERIOD_S,
    CommandLost,
    EnvelopeCorrection,
    ForeignWriter,
    SetpointAboveMax,
)
from ovenbird_harness.faults.link import BrokerDrop, HeishaMonRestart, TopicStale
from ovenbird_harness.faults.pump import DhwRun, ModeChange
from ovenbird_harness.faults.room import (
    HA_LINK_ALARM,
    HOLD_START_S,
    QUIET_ALARM,
    SILENT_ALARM,
    STUCK_MAX_DROP_K,
    HaLinkDown,
    HaRereadFails,
    RoomSensorDiesWarm,
    RoomSensorFailsHigh,
    RoomSensorSilent,
    expected_authority,
)
from ovenbird_harness.faults.scenario import (
    BAND_K,
    COMFORT_FLOOR_K,
    CONTROL,
    CYCLE_S,
    EPSILON,
    HOUR,
    SLACK_S,
    TAIL_S,
    TICK_CYCLES,
    TICK_S,
    TROUBLE,
    WARMUP_S,
    Check,
    Scenario,
    Seen,
    seen,
    verdict,
)
from ovenbird_harness.faults.schedule import HA_SCENARIOS, SCENARIOS, Scheduler
from ovenbird_harness.faults.stove import STOVE_RAMP_TERMS, StoveEvening

__all__ = [
    "ABOVE_MAX_K",
    "BAND_K",
    "COMFORT_FLOOR_K",
    "CONTROL",
    "CYCLE_S",
    "DEFROST_TOPIC",
    "ENVELOPE_ALARM",
    "EPSILON",
    "FOREIGN_STEP_K",
    "HARNESS_ADMIN",
    "HA_LINK_ALARM",
    "HA_SCENARIOS",
    "HOLD_START_S",
    "HOUR",
    "MAX_SHIFT_K",
    "OUTSIDE_TOPIC",
    "QUIET_ALARM",
    "RESTART_BURST_S",
    "RULE_MARGIN_K",
    "RULE_PERIOD_S",
    "SCENARIOS",
    "SILENT_ALARM",
    "SLACK_S",
    "STOVE_RAMP_TERMS",
    "STUCK_MAX_DROP_K",
    "TAIL_S",
    "TICK_CYCLES",
    "TICK_S",
    "TROUBLE",
    "WARMUP_S",
    "BrokerDrop",
    "Check",
    "CommandLost",
    "ConfigApply",
    "DhwRun",
    "EnvelopeCorrection",
    "ForeignWriter",
    "HaLinkDown",
    "HaRereadFails",
    "HeishaMonRestart",
    "ModeChange",
    "OvenbirdRestart",
    "PumpSettingWrite",
    "RoomSensorDiesWarm",
    "RoomSensorFailsHigh",
    "RoomSensorSilent",
    "Scenario",
    "Scheduler",
    "Seen",
    "SetpointAboveMax",
    "StoveEvening",
    "TopicStale",
    "expected_authority",
    "seen",
    "verdict",
]
