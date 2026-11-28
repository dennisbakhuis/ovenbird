"""HeishaMon command adapter: the only code path in the service that publishes.

Layers, outermost last:

- :class:`CommandAdapter` (pure state machine, no I/O) turns arbiter requests into
  commands: a closed allowlist of three settings (water setpoint via the configured
  register, maximum pump duty, quiet mode), integer clamps to the safety limits,
  mode gating on a fresh ``Heating_Mode`` (Direct) and ``Operating_Mode_State``
  (heat), a serial queue (one command in flight, the newest value per setting
  queued, values the controller no longer wants dropped) with a minimum spacing,
  effect verification against ``Z1_Water_Target_Temp`` / ``Max_Pump_Duty`` /
  ``Quiet_Mode_Level`` with retries and an alarm plus hold when they run out (a
  value the pump already reported counts as verified when no change follows within
  the verify timeout: HeishaMon publishes only changes, so a write that changes
  nothing is never echoed before the next full dump), a
  per-day write budget with an alarm, foreign-writer detection (a verified value
  later read back different) with a hold and an alarm, escalation of repeated holds
  (longer, then latched until an operator releases it), safety corrections and the
  safety hold (see :meth:`CommandAdapter.tick`), and HeishaMon restart detection.
  A second closed allowlist holds the three pump settings an operator may write
  (:class:`~ovenbird_core.PumpSetting`: heating delta-T, flow-rate mode, heating-off
  outdoor temperature; see :meth:`CommandAdapter.request_setting`): one-shot requests
  through the same queue, guard, spacing, verification, budget and journal, refused
  instead of clamped, compare-and-set on the fresh reported value, refused during a
  defrost, a DHW run or any hold, and a failed verification raises
  ``verification_failed`` without holding setpoint control. A later change of such a
  value that ovenbird did not make raises the info alarm ``pump_setting_changed``.
  When the owner declared the HeishaMon envelope rule installed, a read-back
  difference of the water setpoint that the rule explains (ovenbird's value outside
  the envelope band at the current ``Outside_Temp``, the pump now reporting what the
  rule writes there) is not a foreign writer: it is journalled
  (``envelope_correction``), counted and adopted, and ``envelope_mismatch`` is raised
  when ovenbird's value already lay outside the band when it was set.
  A third kind of request restores the pump-state snapshot taken at go-live
  (:meth:`CommandAdapter.request_restore`, "Release control"): the controller's own
  allowlist, clamps, queue, spacing, budget and verification, refused during any
  hold.
- :class:`CommandLink` is the publishing MQTT connection. It cannot be constructed
  unless the :class:`~ovenbird.control.guard.PublishGuard` permits publishing, has
  no last will, re-checks the guard before every publish and publishes only to
  the adapter's allowlisted topics (never retained).
- :class:`CommandWorker` drives the adapter on the service clock and hands released
  commands to the link.

**Modules**
``model``
    Commands, events, records and the shared constants.
``publish``
    :class:`AdapterConfig` (the topic allowlist and payloads) and :class:`CommandLink`,
    the only publishing code.
``base``
    The adapter's state and event emission.
``envelope``, ``holds``, ``link``, ``settings``
    Envelope-rule recognition; holds, escalation and foreign writers; mode, firmware
    and restart gating of the HeishaMon link; operator pump-setting writes and the
    go-live restore.
``commands``
    :class:`CommandAdapter`: queue, de-duplication, release, verification, retries and
    the safety correction.
``worker``
    :class:`CommandWorker`.

Every name of the former single module is re-exported here.
"""

from ovenbird.control.adapter.commands import BUDGET_WARNING_SHARE, CommandAdapter
from ovenbird.control.adapter.envelope import BAND_EPSILON_K
from ovenbird.control.adapter.holds import CONFIRM_CODES
from ovenbird.control.adapter.link import SIM_VERSION_SUFFIX, UPTIME_TOLERANCE_S
from ovenbird.control.adapter.model import (
    LOGGER,
    OPERATOR_PREFIX,
    OPERATOR_REASON,
    OPERATOR_WINDOW_S,
    RESTORE_PREFIX,
    RESTORE_REASON,
    SAFETY_REASON,
    VERIFY_SIGNALS,
    AdapterCounters,
    Command,
    CommandEvent,
    CommandKind,
    CommandStatus,
    HoldRecord,
    OperatorWrite,
    Reader,
    RestoredAdapter,
    SettingRefusedError,
    reported_int,
    verify_signal,
)
from ovenbird.control.adapter.publish import (
    COMMANDS,
    QUIET_RANGE,
    SETPOINT_COMMANDS,
    AdapterConfig,
    CommandLink,
    CommandSender,
    PublishingClient,
)
from ovenbird.control.adapter.settings import (
    CHANGE_NOTICE_S,
    OPERATOR_DAY_LIMIT,
    OPERATOR_SPACING_S,
    restore_target,
)
from ovenbird.control.adapter.worker import WORKER_POLL_S, CommandWorker

__all__ = [
    "BAND_EPSILON_K",
    "BUDGET_WARNING_SHARE",
    "CHANGE_NOTICE_S",
    "COMMANDS",
    "CONFIRM_CODES",
    "LOGGER",
    "OPERATOR_DAY_LIMIT",
    "OPERATOR_PREFIX",
    "OPERATOR_REASON",
    "OPERATOR_SPACING_S",
    "OPERATOR_WINDOW_S",
    "QUIET_RANGE",
    "RESTORE_PREFIX",
    "RESTORE_REASON",
    "SAFETY_REASON",
    "SETPOINT_COMMANDS",
    "SIM_VERSION_SUFFIX",
    "UPTIME_TOLERANCE_S",
    "VERIFY_SIGNALS",
    "WORKER_POLL_S",
    "AdapterConfig",
    "AdapterCounters",
    "Command",
    "CommandAdapter",
    "CommandEvent",
    "CommandKind",
    "CommandLink",
    "CommandSender",
    "CommandStatus",
    "CommandWorker",
    "HoldRecord",
    "OperatorWrite",
    "PublishingClient",
    "Reader",
    "RestoredAdapter",
    "SettingRefusedError",
    "reported_int",
    "restore_target",
    "verify_signal",
]
