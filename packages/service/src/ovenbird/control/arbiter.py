"""The arbiter: compare the controller's intents with what the pump reports.

Intents are desired states. For every intent the arbiter decides one action:

- ``none``: nothing to do — the pump already reports the value, or the adapter has
  the same value in flight or queued;
- ``skip``: do not write now — the pump's current value is unknown or stale (never
  write blind), or the adapter holds after an alarm;
- ``send``: hand the value to the command adapter (in ``shadow`` the decision is only
  recorded as what would have been sent).

The arbiter is pure: its result depends only on its arguments.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ovenbird_core.control import ActualValue, CommandIntent, IntentKind, PumpActual


class Action(StrEnum):
    """What the arbiter decided for one intent."""

    NONE = "none"
    SKIP = "skip"
    SEND = "send"


@dataclass(frozen=True, slots=True)
class AdapterView:
    """What the arbiter needs to know about the command adapter.

    Parameters
    ----------
    in_flight
        Value per kind published and awaiting verification.
    queued
        Value per kind waiting to be published.
    hold
        Why the adapter refuses to publish right now, if it does.
    """

    in_flight: Mapping[IntentKind, int] = field(default_factory=dict)
    queued: Mapping[IntentKind, int] = field(default_factory=dict)
    hold: str | None = None


@dataclass(frozen=True, slots=True)
class Arbitration:
    """The arbiter's decision for one intent.

    Parameters
    ----------
    intent
        The controller's intent.
    actual
        Value the pump reports (``None`` when unknown).
    action
        Decided action.
    reason
        Short explanation.
    """

    intent: CommandIntent
    actual: int | None
    action: Action
    reason: str

    def to_json(self) -> dict[str, Any]:
        """Return the JSON form stored with the decision."""
        return {
            "kind": self.intent.kind.value,
            "intent": self.intent.value,
            "actual": self.actual,
            "action": self.action.value,
            "reason": self.reason,
        }


def actual_for(actual: PumpActual, kind: IntentKind) -> ActualValue | None:
    """Return the reported value matching an intent kind."""
    match kind:
        case IntentKind.WATER_SETPOINT:
            return actual.water_target
        case IntentKind.MAX_PUMP_DUTY:
            return actual.max_pump_duty
        case IntentKind.QUIET_MODE:
            return actual.quiet_mode


def arbitrate(
    intents: Sequence[CommandIntent],
    actual: PumpActual,
    adapter: AdapterView | None = None,
) -> tuple[Arbitration, ...]:
    """Decide what to do with each intent.

    Parameters
    ----------
    intents
        The controller's intents of this tick.
    actual
        The pump's reported settings.
    adapter
        Adapter state; ``None`` when no adapter runs (shadow).

    Returns
    -------
    tuple of Arbitration
        One decision per intent, in intent order.
    """
    view = adapter or AdapterView()
    decisions: list[Arbitration] = []
    for intent in intents:
        reported = actual_for(actual, intent.kind)
        value = reported.value if reported is not None else None
        if reported is None or not reported.fresh:
            decisions.append(Arbitration(intent, value, Action.SKIP, "actual unknown or stale"))
        elif reported.value == intent.value:
            decisions.append(Arbitration(intent, value, Action.NONE, "already applied"))
        elif view.in_flight.get(intent.kind) == intent.value:
            decisions.append(Arbitration(intent, value, Action.NONE, "in flight"))
        elif view.queued.get(intent.kind) == intent.value:
            decisions.append(Arbitration(intent, value, Action.NONE, "queued"))
        elif view.hold is not None:
            decisions.append(Arbitration(intent, value, Action.SKIP, f"hold: {view.hold}"))
        else:
            decisions.append(
                Arbitration(intent, value, Action.SEND, f"pump reports {reported.value}")
            )
    return tuple(decisions)
