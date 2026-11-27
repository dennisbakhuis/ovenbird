"""Shared state of the running service: the core's store plus component health.

Everything here runs on the event loop; the history writer is the only other
thread and is fed through its queue.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Final, Protocol

from ovenbird.clock import Clock, system_clock
from ovenbird.history.database import (
    HEAT_INPUTS,
    Sample,
    gap_sample,
    heat_sample,
    sample_from_reading,
)
from ovenbird.payloads import Json, health_payload, snapshot_payload
from ovenbird_core import (
    Instant,
    ParseError,
    ParseResult,
    Reading,
    Snapshot,
    SourceKind,
    StateStore,
)

LOGGER = logging.getLogger("ovenbird.runtime")
CRASH_LIMIT: Final = 5


class HistorySink(Protocol):
    """What the runtime needs from the history writer."""

    def offer(self, sample: Sample) -> None:
        """Queue a sample."""
        ...

    def healthy(self) -> bool:
        """Whether history is being written."""
        ...

    def starting(self) -> bool:
        """Whether the writer has not finished opening the database yet."""
        ...


class Runtime:
    """State store, change counter and component status of one service instance.

    Parameters
    ----------
    store
        The core's state store.
    clock
        Source of instants.
    history
        History writer; ``None`` disables history.
    ha_enabled
        Whether the Home Assistant input is configured.
    """

    def __init__(
        self,
        store: StateStore | None = None,
        *,
        clock: Clock = system_clock,
        history: HistorySink | None = None,
        ha_enabled: bool = False,
    ) -> None:
        self.store = store or StateStore()
        self.clock = clock
        self.history = history
        self.ha_enabled = ha_enabled
        self.version = 0
        self.mqtt_connected = False
        self.ha_connected = False
        self.crashes: dict[str, int] = {}
        self.alarm_level: str | None = None
        self.weather_check: Callable[[Instant], str] | None = None
        self.defrost: Callable[[Snapshot], Json] | None = None

    def apply(self, item: ParseResult) -> None:
        """Apply one parse result to the store and pass it on to history.

        Live readings become samples; a parse error that invalidated a value ends
        the value's held interval in history (a gap instead of a plateau). Every
        live reading of a loop-heat input also stores the derived loop heat
        (:func:`ovenbird.history.database.heat_sample`).
        """
        changed = self.store.apply(item)
        if changed:
            self.version += 1
        if self.history is None:
            return
        sample: Sample | None = None
        if isinstance(item, Reading):
            sample = sample_from_reading(item, self.store.policy)
        elif isinstance(item, ParseError) and changed:
            sample = gap_sample(item)
        if sample is not None:
            self.history.offer(sample)
        if isinstance(item, Reading) and not item.retained and item.signal in HEAT_INPUTS:
            snapshot = self.store.snapshot(item.observed)
            self.history.offer(heat_sample(snapshot, self.store.policy))

    def refuse(self, reading: Reading, error: ParseError) -> None:
        """Show a refused reading with its reason, without using or recording its value.

        The store keeps the value for display, invalidated at once by ``error`` (its
        view is not fresh and carries the reason); history gets no sample of it.
        """
        self.store.apply(reading)
        self.store.apply(error)
        self.version += 1
        sample = gap_sample(error)
        if self.history is not None and sample is not None:
            self.history.offer(sample)

    def set_link(self, source: SourceKind, *, up: bool, confirmed: bool = False) -> None:
        """Report the link to ``source`` to the store (``confirmed``: it proved to work now)."""
        self.store.set_link(source, up, self.clock() if up and confirmed else None)
        self.version += 1

    def record_crash(self, component: str) -> None:
        """Count an unexpected failure of a supervised component."""
        self.crashes[component] = self.crashes.get(component, 0) + 1
        if self.crashes[component] == CRASH_LIMIT:
            LOGGER.critical(
                "%s failed %d times in a row; reporting not live", component, CRASH_LIMIT
            )

    def record_recovery(self, component: str) -> None:
        """Reset the failure count of a component that ran stably."""
        self.crashes.pop(component, None)

    @property
    def live(self) -> bool:
        """False only while a component keeps crashing."""
        return all(count < CRASH_LIMIT for count in self.crashes.values())

    def health(self, now: Instant | None = None) -> Json:
        """Return the health body at ``now``."""
        moment = now or self.clock()
        if not self.ha_enabled:
            ha = "disabled"
        else:
            ha = "connected" if self.ha_connected else "disconnected"
        if self.history is None:
            history = "error"
        elif self.history.healthy():
            history = "ok"
        elif self.history.starting():
            history = "starting"
        else:
            history = "error"
        return health_payload(
            live=self.live,
            mqtt="connected" if self.mqtt_connected else "disconnected",
            heishamon="alive" if self.store.heishamon_alive(moment) else "dead",
            ha=ha,
            history=history,
            alarms=self.alarm_level or "disabled",
            weather=self.weather_check(moment) if self.weather_check is not None else "disabled",
        )

    def snapshot(self, now: Instant | None = None) -> Json:
        """Return the snapshot body at ``now``, with the safety monitor's defrost when set."""
        snapshot = self.store.snapshot(now or self.clock())
        defrost = self.defrost(snapshot) if self.defrost is not None else None
        return snapshot_payload(snapshot, defrost)
