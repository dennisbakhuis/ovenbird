"""The adapter's view of the HeishaMon link: mode, firmware and restarts.

Nothing is published while ``Heating_Mode`` is not Direct or ``Operating_Mode_State``
not heat (or either is not fresh), nor, in simulation mode, while HeishaMon does not
report simulated firmware. A heartbeat back after a gap, an uptime reset or an LWT
Offline then Online marks a restart: read-back differences right after it are
attributed to the restart, not to a foreign writer.
"""

from __future__ import annotations

from typing import Final

from ovenbird.control.adapter.holds import HoldsMixin
from ovenbird.control.adapter.model import (
    LOGGER,
    Reader,
    reported_int,
)
from ovenbird.control.alarms import AlarmCode
from ovenbird_core import (
    HeishaMonStatus,
    HeishaSignal,
    Instant,
)

SIM_VERSION_SUFFIX: Final = "-sim"
UPTIME_TOLERANCE_S: Final = 1.0


class LinkMixin(HoldsMixin):
    """Mode gating, simulator gating and restart detection of the adapter."""

    def _check_mode(self, now: Instant, read: Reader) -> None:
        heating = reported_int(read(HeishaSignal.HEATING_MODE))
        operating = reported_int(read(HeishaSignal.OPERATING_MODE_STATE))
        problem: str | None = None
        if heating is None or operating is None:
            problem = "Heating_Mode or Operating_Mode_State not fresh"
        elif heating != self.config.direct_heating_mode:
            problem = f"Heating_Mode is {heating}, not Direct"
        elif operating not in self.config.allowed_operating_modes:
            problem = f"Operating_Mode_State is {operating}, not heat"
        if problem == self._mode_problem:
            return
        self._mode_problem = problem
        if problem is None:
            self.alarms.clear(AlarmCode.MODE_MISMATCH, now, "Direct mode and heat again")
            return
        if heating is not None and operating is not None:
            self._verified.clear()
            if self.alarms.is_active(AlarmCode.MODE_MISMATCH):
                self.alarms.clear(AlarmCode.MODE_MISMATCH, now, "mode changed again")
            self.alarms.raise_alarm(AlarmCode.MODE_MISMATCH, problem, now)
        self._drop_queue(now, problem)

    def _check_board(self, now: Instant, board: HeishaMonStatus | None) -> None:
        if not self.config.require_simulated_board:
            return
        version = board.version if board is not None else None
        problem = None
        if version is None or not version.endswith(SIM_VERSION_SUFFIX):
            problem = (
                f"simulation mode: HeishaMon reports firmware {version!r}, "
                f"not a simulator ('*{SIM_VERSION_SUFFIX}')"
            )
        if problem == self._board_problem:
            return
        self._board_problem = problem
        if problem is None:
            LOGGER.warning("simulation mode: HeishaMon reports firmware %r; publishing", version)
            return
        LOGGER.error("%s; nothing is published", problem)
        self._drop_queue(now, problem)

    def _watch_board(self, now: Instant, board: HeishaMonStatus | None) -> None:
        if board is None:
            return
        state = self._board
        why: list[str] = []
        if state.alive is False and board.alive:
            why.append("heartbeat back after a gap")
        if (
            board.uptime_s is not None
            and state.uptime_s is not None
            and board.uptime_s + UPTIME_TOLERANCE_S < state.uptime_s
        ):
            why.append("uptime reset")
        if state.lwt_online is False and board.lwt_online is True:
            why.append("LWT Offline then Online")
        state.alive = board.alive
        if board.uptime_s is not None:
            state.uptime_s = board.uptime_s
        if board.lwt_online is not None:
            state.lwt_online = board.lwt_online
        if why:
            state.restarted_at = now.monotonic
            state.why = ", ".join(why)
            LOGGER.warning("HeishaMon restart or reconnect detected (%s)", state.why)
