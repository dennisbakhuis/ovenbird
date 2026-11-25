"""The controller protocol shared by every controller and harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ovenbird_core.control.record import DecisionRecord, JsonDict, intent_to_json_dict
from ovenbird_core.control.types import CommandIntent, ControlInputs, IntentKind


@dataclass(frozen=True, slots=True)
class StepResult[S]:
    """Outcome of one controller tick.

    Parameters
    ----------
    state
        Controller state replacing the previous one.
    intents
        Desired pump settings this tick (possibly empty).
    decision
        Explanation of the tick.
    """

    state: S
    intents: tuple[CommandIntent, ...]
    decision: DecisionRecord

    def intent(self, kind: IntentKind) -> CommandIntent | None:
        """Return the intent of ``kind``, if any."""
        return next((intent for intent in self.intents if intent.kind is kind), None)

    def intents_json(self) -> list[JsonDict]:
        """Return the intents in their JSON form."""
        return [intent_to_json_dict(intent) for intent in self.intents]


class Controller[S](Protocol):
    """A pure controller: ``step`` maps (state, inputs) to (state, intents, record).

    ``step`` is called on a fixed tick by whoever drives time. It never sleeps,
    never reads clocks and never mutates its arguments; the returned state
    replaces the old one.
    """

    @property
    def name(self) -> str:
        """Controller name, recorded in every decision."""
        ...

    def initial_state(self) -> S:
        """Return the state before the first tick."""
        ...

    def step(self, state: S, inputs: ControlInputs) -> StepResult[S]:
        """Advance one tick."""
        ...
