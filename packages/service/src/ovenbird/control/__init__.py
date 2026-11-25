"""Control path of the service: loop, arbiter, publish guard and command adapter.

The loop's names load on first use, so modules the loop itself imports (the wood-stove
session, for example) can import from this package without a cycle.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from ovenbird.control.adapter import (
    AdapterConfig,
    Command,
    CommandAdapter,
    CommandEvent,
    CommandLink,
    CommandStatus,
    CommandWorker,
)
from ovenbird.control.alarms import Alarm, AlarmBoard, AlarmCode
from ovenbird.control.arbiter import Action, AdapterView, Arbitration, arbitrate
from ovenbird.control.guard import CommandsRefusedError, PublishGuard

if TYPE_CHECKING:
    from ovenbird.control.loop import CommandJournal, ControlLoop, controller_config

LAZY = frozenset({"CommandJournal", "ControlLoop", "controller_config"})

__all__ = [
    "Action",
    "AdapterConfig",
    "AdapterView",
    "Alarm",
    "AlarmBoard",
    "AlarmCode",
    "Arbitration",
    "Command",
    "CommandAdapter",
    "CommandEvent",
    "CommandJournal",
    "CommandLink",
    "CommandStatus",
    "CommandWorker",
    "CommandsRefusedError",
    "ControlLoop",
    "PublishGuard",
    "arbitrate",
    "controller_config",
]


def __getattr__(name: str) -> Any:
    """Load the control loop's names on first use."""
    if name in LAZY:
        return getattr(importlib.import_module("ovenbird.control.loop"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
