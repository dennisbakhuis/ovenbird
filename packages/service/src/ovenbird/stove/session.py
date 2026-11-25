"""The control loop's side of wood-stove mode: the manual request, its events and status.

:class:`StoveSession` keeps the operator's manual request
(:class:`~ovenbird.stove.request.StoveRequest`), saves it with the controller state,
drops it when it expires (or, for a one-shot stop, once the controller acted on it),
journals every entry into and exit from wood-stove mode as an informational
``stove_mode`` event and raises ``stove_reference_missing`` while an episode runs
without a fresh reference room. The control loop calls it around every tick.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from ovenbird.control.alarms import AlarmBoard, AlarmCode
from ovenbird.history.journal import StateRow
from ovenbird.stove.request import (
    MANUAL_DEFAULT_S,
    STOVE_KEY,
    StoveRequest,
    StoveRequestError,
    encode_request,
    new_request,
    stove_event,
)
from ovenbird_core import Instant
from ovenbird_core.control import DecisionRecord, OvenbirdState, StoveConfig

LOGGER = logging.getLogger("ovenbird.control")


class StoveHost(Protocol):
    """The owner of a :class:`StoveSession` (the control loop): its current collaborators."""

    @property
    def alarms(self) -> AlarmBoard:
        """The alarm board (``stove_mode`` events, ``stove_reference_missing``)."""
        ...

    @property
    def state_sink(self) -> Callable[[StateRow], None] | None:
        """Saves the request with the controller state, if set."""
        ...


class StoveSession:
    """The manual wood-stove request of a control loop, with its events and status.

    The alarm board and the state sink are read from ``host`` at every use, so a
    loop whose ``alarms`` or ``state_sink`` is rebound after construction is honoured.

    Parameters
    ----------
    clock
        The service clock.
    host
        The owner whose ``alarms`` and ``state_sink`` the session uses.
    request
        Manual request to start with (restored after a restart).
    """

    def __init__(
        self,
        clock: Callable[[], Instant],
        host: StoveHost,
        request: StoveRequest | None = None,
    ) -> None:
        self.clock = clock
        self.host = host
        self.request = request

    @property
    def alarms(self) -> AlarmBoard:
        """The host's current alarm board."""
        return self.host.alarms

    @property
    def state_sink(self) -> Callable[[StateRow], None] | None:
        """The host's current state sink."""
        return self.host.state_sink

    def accept(
        self,
        config: StoveConfig | None,
        on: bool,
        until: datetime | None,
        actor: str,
        now: Instant | None = None,
    ) -> StoveRequest:
        """Accept a manual request; it takes effect at the next tick.

        Parameters
        ----------
        config
            The controller's wood-stove configuration (``None`` when it is off).
        on
            Start (or keep) wood-stove mode; ``False`` stops it.
        until
            End of the request; a start without one lasts 8 h (at most the episode
            cap), a stop without one is one-shot.
        actor
            Who asks.
        now
            Current instant; the clock when omitted.

        Returns
        -------
        StoveRequest
            The stored request.

        Raises
        ------
        StoveRequestError
            When wood-stove mode is not enabled or ``until`` is not acceptable.
        """
        if config is None:
            raise StoveRequestError("wood-stove mode is not enabled (control_stove_enabled)")
        moment = now or self.clock()
        default_s = min(MANUAL_DEFAULT_S, config.max_active_s)
        request = new_request(on, until, actor, moment.wall, default_s)
        self.set(request, moment)
        LOGGER.warning("wood-stove request by %s: %s", actor, request.to_json())
        return request

    def set(self, request: StoveRequest | None, moment: Instant) -> None:
        """Store ``request`` (``None`` drops it) and save it with the controller state."""
        self.request = request
        sink = self.state_sink
        if sink is not None:
            sink(StateRow(STOVE_KEY, moment.wall.timestamp(), encode_request(request)))

    def live(self, moment: Instant) -> StoveRequest | None:
        """Return the request in force at ``moment``, dropping it once it has expired."""
        request = self.request
        if request is not None and request.expired(moment.wall):
            LOGGER.info("wood-stove request ended: %s", request.to_json())
            self.set(None, moment)
            return None
        return request

    def after(self, decision: DecisionRecord, moment: Instant) -> None:
        """Drop a one-shot stop the controller acted on and journal entries and exits."""
        request = self.request
        acted = decision.controller_state.get("stove_state") is not None
        if request is not None and not request.on and request.until is None and acted:
            self.set(None, moment)
        event = stove_event(decision)
        if event is not None:
            LOGGER.warning("%s", event.message)
            self.alarms.record(event)

    def reference_alarm(
        self, config: StoveConfig | None, decision: DecisionRecord, moment: Instant
    ) -> None:
        """Raise ``stove_reference_missing`` while an episode lacks its reference room."""
        code = AlarmCode.STOVE_REFERENCE_MISSING
        state = decision.controller_state
        reference = None if config is None else config.reference
        if reference is None or state.get("stove_state") != "active":
            self.alarms.clear(code, moment, "no wood-stove episode with a reference room")
            return
        if state.get("stove_reference_c") is not None:
            self.alarms.clear(code, moment, "the reference room reports a temperature again")
            return
        share = state.get("stove_reference_share")
        kept = f"{share * 100:.0f} %" if isinstance(share, int | float) else "half"
        self.alarms.raise_alarm(
            code,
            f"wood-stove mode is active but the reference room {reference} has no fresh "
            f"temperature (unknown, stale or not in °C); only {kept} of the back-off is kept "
            "until it reports again, so the rest of the house is not protected as configured",
            moment,
        )

    def status(
        self,
        config: StoveConfig | None,
        state: OvenbirdState,
        latest: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Return the API form of wood-stove mode: configuration, state and request.

        Parameters
        ----------
        config
            The controller's wood-stove configuration.
        state
            The controller state.
        latest
            The controller state of the latest decision record, if any.
        """
        seen = latest or {}
        request = self.request
        return {
            "enabled": config is not None,
            "auto": config is not None and config.auto,
            "active": state.stove_active,
            "source": None if state.stove_source is None else state.stove_source.value,
            "trigger": None if state.stove_trigger is None else state.stove_trigger.value,
            "since": seen.get("stove_started") if state.stove_active else None,
            "entry_c": state.stove_entry_c,
            "integral_k": state.stove_integral_k,
            "blocked": state.stove_blocked,
            "level_blocked": state.stove_level_blocked,
            "reentry_wait": state.stove_reentry_wait,
            "backoff_k": seen.get("stove_backoff_k") if state.stove_active else None,
            "enter_c": seen.get("stove_enter_c"),
            "exit_c": seen.get("stove_exit_c"),
            "reference_c": seen.get("stove_reference_c"),
            "request": None if request is None else request.to_json(),
        }
