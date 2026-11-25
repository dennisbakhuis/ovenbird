"""``ovenbird.control.adapter`` keeps every former public name after becoming a package."""

from __future__ import annotations

import importlib
from typing import Final

OLD_NAMES: Final = (
    "AdapterConfig",
    "AdapterCounters",
    "BAND_EPSILON_K",
    "BUDGET_WARNING_SHARE",
    "CHANGE_NOTICE_S",
    "COMMANDS",
    "CONFIRM_CODES",
    "Command",
    "CommandAdapter",
    "CommandEvent",
    "CommandKind",
    "CommandLink",
    "CommandSender",
    "CommandStatus",
    "CommandWorker",
    "HoldRecord",
    "LOGGER",
    "OPERATOR_DAY_LIMIT",
    "OPERATOR_PREFIX",
    "OPERATOR_REASON",
    "OPERATOR_SPACING_S",
    "OPERATOR_WINDOW_S",
    "OperatorWrite",
    "PublishingClient",
    "QUIET_RANGE",
    "RESTORE_PREFIX",
    "RESTORE_REASON",
    "Reader",
    "RestoredAdapter",
    "SAFETY_REASON",
    "SETPOINT_COMMANDS",
    "SIM_VERSION_SUFFIX",
    "SettingRefusedError",
    "UPTIME_TOLERANCE_S",
    "VERIFY_SIGNALS",
    "WORKER_POLL_S",
    "reported_int",
    "restore_target",
    "verify_signal",
)


def test_every_former_name_still_resolves() -> None:
    """Each public name of the former single module is importable from the package."""
    module = importlib.import_module("ovenbird.control.adapter")
    missing = [name for name in OLD_NAMES if not hasattr(module, name)]
    assert missing == []


def test_the_adapter_logs_under_its_former_name() -> None:
    """Every part of the package logs to the logger the single module used."""
    module = importlib.import_module("ovenbird.control.adapter")
    assert module.LOGGER.name == "ovenbird.control.adapter"
