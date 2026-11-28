"""Latest value per signal with ages, freshness and HeishaMon liveness.

The store is the ingestion buffer between the async shell and the pure controller:
the shell applies every parse result as it arrives (a few per second live,
millions in a replay) and the controller reads an immutable :class:`Snapshot`
once per tick. Mutation is explicit and confined to :meth:`StateStore.apply`;
everything read from the store is immutable.

**Freshness rules**
* Ages are measured on the monotonic axis from the last *confirmation* of a value.
* A live delivery confirms its value. For sources that report their own timestamp
  (Home Assistant ``last_reported``) the confirmation is moved back by the lag the
  source reports, so a state replayed on reconnect keeps its real age.
* A retained delivery never confirms anything: with an unchanged value the
  previous confirmation stays, with a different value the age becomes unknown.
* A live delivery that cannot be used (Home Assistant ``unavailable``/``unknown``,
  a HeishaMon ``-1`` enum, an out-of-range or malformed payload) invalidates the
  stored value at once: the value is kept for display, but it is never fresh and
  its view carries the reason until the next live reading. Retained errors are
  replays and invalidate nothing.
* A signal can be confirmed by a group (:attr:`StalenessPolicy.confirmed_by`): its
  age is the newest valid confirmation of itself or of any of its liveness signals
  (sibling signals of the same device, e.g. a sensor's humidity next to its
  temperature). An invalidated liveness signal confirms nothing. This is also how a
  value seeded by a retained delivery becomes alive: by a live delivery of the
  value or of a liveness signal.
* Each entry also keeps when its value last *changed* (seeded from the source's own
  change time, HA ``last_changed``, after a restart); the view reports it as the
  ``held`` age.
* A signal can be *held* (:attr:`StalenessPolicy.held`): its per-signal maximum
  age (the silence limit of a sensor that reports only on change) applies only while
  the link to its source is up (:meth:`StateStore.set_link`); otherwise the source
  default applies. A Home Assistant link is up while connected and a ``get_states``
  re-read succeeded within :attr:`StalenessPolicy.ha_link_window_s`; an MQTT link
  while the broker is connected.
* HeishaMon is alive while a live ``stats`` message arrived within the liveness
  window. The window follows the observed ``stats`` cadence (a multiple of the
  median interval, clamped to a floor and a ceiling); until a few intervals are
  known it is the policy's default. ``LWT`` is recorded for display only.
"""

from __future__ import annotations

import statistics
from collections import Counter, deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from typing import Final

from ovenbird_core.heishamon import Heartbeat, LwtNotice, ParseResult
from ovenbird_core.instant import Instant
from ovenbird_core.readings import Ignored, ParseError, Reading, SignalId, SourceKind, Value

HEISHAMON_MAX_AGE_S: Final = 330.0
HEISHAMON_LIVENESS_S: Final = 15.0
LIVENESS_FLOOR_S: Final = 15.0
LIVENESS_CEILING_S: Final = 120.0
LIVENESS_CADENCE_FACTOR: Final = 3.0
LIVENESS_MIN_INTERVALS: Final = 3
LIVENESS_HISTORY: Final = 12
HA_MAX_AGE_S: Final = 1800.0
MQTT_MAX_AGE_S: Final = 1800.0
PROVIDER_MAX_AGE_S: Final = 7200.0
HA_LINK_WINDOW_S: Final = 900.0


@dataclass(frozen=True, slots=True)
class StalenessPolicy:
    """Maximum ages per source kind, per-signal overrides and the liveness window.

    Parameters
    ----------
    heishamon_max_age_s
        HeishaMon re-publishes every topic in a full dump every 300 s, so a value
        without any update for longer than this is stale.
    ha_max_age_s
        Default for Home Assistant entities (room temperature: 30 min).
    mqtt_max_age_s
        Default for plain MQTT topics.
    provider_max_age_s
        Default for provider data (forecasts, prices).
    liveness_window_s
        Liveness window used until the ``stats`` cadence is known.
    liveness_floor_s, liveness_ceiling_s
        Bounds of the cadence-derived liveness window; intervals longer than the
        ceiling are outages and are not learned as cadence.
    liveness_cadence_factor
        The window is this many median ``stats`` intervals.
    overrides
        Maximum age per signal id, taking precedence over the source default.
    confirmed_by
        Liveness signals per signal id: a valid confirmation of any of them also
        confirms the signal.
    held
        Signals whose override applies only while their source link is up (held
        values of sensors that report only on change).
    ha_link_window_s
        A Home Assistant link counts as up only when a ``get_states`` re-read
        succeeded within this window.
    """

    heishamon_max_age_s: float = HEISHAMON_MAX_AGE_S
    ha_max_age_s: float = HA_MAX_AGE_S
    mqtt_max_age_s: float = MQTT_MAX_AGE_S
    provider_max_age_s: float = PROVIDER_MAX_AGE_S
    liveness_window_s: float = HEISHAMON_LIVENESS_S
    liveness_floor_s: float = LIVENESS_FLOOR_S
    liveness_ceiling_s: float = LIVENESS_CEILING_S
    liveness_cadence_factor: float = LIVENESS_CADENCE_FACTOR
    overrides: Mapping[SignalId, float] = field(default_factory=dict)
    confirmed_by: Mapping[SignalId, tuple[SignalId, ...]] = field(default_factory=dict)
    held: frozenset[SignalId] = frozenset()
    ha_link_window_s: float = HA_LINK_WINDOW_S

    def max_age(self, signal: SignalId, source: SourceKind, link_up: bool = True) -> float:
        """Return the maximum age in seconds for ``signal`` delivered by ``source``.

        Parameters
        ----------
        signal
            Signal id.
        source
            Source kind of its latest reading.
        link_up
            Whether the link to the source is up; a held signal's override applies
            only then.

        Returns
        -------
        float
            The per-signal override, otherwise the source default.
        """
        override = self.overrides.get(signal)
        if override is not None and (link_up or signal not in self.held):
            return override
        match source:
            case SourceKind.HEISHAMON:
                return self.heishamon_max_age_s
            case SourceKind.HA:
                return self.ha_max_age_s
            case SourceKind.MQTT:
                return self.mqtt_max_age_s
            case SourceKind.PROVIDER:
                return self.provider_max_age_s

    def with_override(self, signal: SignalId, max_age_s: float) -> StalenessPolicy:
        """Return a copy with a per-signal maximum age."""
        return replace(self, overrides={**self.overrides, signal: max_age_s})

    def with_liveness(self, signal: SignalId, liveness: Iterable[SignalId]) -> StalenessPolicy:
        """Return a copy in which ``liveness`` signals also confirm ``signal``."""
        group = tuple(dict.fromkeys(s for s in liveness if s != signal))
        return replace(self, confirmed_by={**self.confirmed_by, signal: group})

    def with_held(self, signal: SignalId, silence_limit_s: float) -> StalenessPolicy:
        """Return a copy holding ``signal`` up to ``silence_limit_s`` while its link is up."""
        return replace(
            self,
            overrides={**self.overrides, signal: silence_limit_s},
            held=self.held | {signal},
        )

    def link_window(self, source: SourceKind) -> float | None:
        """Window in which a link must have been confirmed (``None``: connected suffices)."""
        return self.ha_link_window_s if source is SourceKind.HA else None

    def liveness_window(self, intervals: Iterable[float]) -> float:
        """Return the liveness window for the observed ``stats`` intervals.

        Parameters
        ----------
        intervals
            Recent intervals between live ``stats`` messages in seconds.

        Returns
        -------
        float
            ``liveness_window_s`` with fewer than three intervals, otherwise the
            cadence factor times their median, clamped to the floor and ceiling.
        """
        known = list(intervals)
        if len(known) < LIVENESS_MIN_INTERVALS:
            return self.liveness_window_s
        window = self.liveness_cadence_factor * statistics.median(known)
        return min(self.liveness_ceiling_s, max(self.liveness_floor_s, window))


@dataclass(frozen=True, slots=True)
class SignalView:
    """What a consumer sees of one signal at one instant.

    Parameters
    ----------
    signal
        Signal id.
    value
        Latest known value.
    unit
        Unit of the value.
    source
        Source kind of the latest reading.
    observed
        When the latest reading arrived.
    age
        Seconds since the value was last confirmed; ``None`` when it never was
        (only seen in a retained delivery).
    max_age
        Maximum age under the staleness policy.
    fresh
        The value is usable: ``age`` is known and at most ``max_age`` and no live
        delivery invalidated it since.
    retained
        The latest reading came from a retained delivery.
    source_timestamp
        Source-reported timestamp of the latest reading, if any.
    reason
        Why the value is not usable when a later live delivery invalidated it
        (``"unavailable: entity has no state"``); ``None`` otherwise.
    held
        Seconds since the value last changed; ``None`` when unknown (only seen
        in a retained delivery).
    alive_by
        The liveness signal whose confirmation set ``age`` when it is newer than
        the signal's own; ``None`` when the signal confirmed itself.
    source_unit
        The unit the source reported when the value was converted at ingest;
        ``None`` when ``unit`` is the source's own.
    """

    signal: SignalId
    value: Value
    unit: str | None
    source: SourceKind
    observed: Instant
    age: float | None
    max_age: float
    fresh: bool
    retained: bool
    source_timestamp: datetime | None
    reason: str | None = None
    held: float | None = None
    alive_by: SignalId | None = None
    source_unit: str | None = None


@dataclass(frozen=True, slots=True)
class HeishaMonStatus:
    """HeishaMon board status derived from ``stats`` and ``LWT``.

    Parameters
    ----------
    alive
        A live ``stats`` arrived within the liveness window.
    heartbeat_age
        Seconds since the last live ``stats``; ``None`` before the first one.
    lwt_online
        Last ``LWT`` seen (informational); ``None`` before the first one.
    version
        Firmware version from the last live ``stats``.
    uptime_s
        Board uptime from the last live ``stats``.
    window_s
        Liveness window in effect.
    """

    alive: bool
    heartbeat_age: float | None
    lwt_online: bool | None
    version: str | None
    uptime_s: float | None
    window_s: float = HEISHAMON_LIVENESS_S


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Immutable view of every signal at one instant.

    Parameters
    ----------
    now
        The instant the view was taken.
    signals
        View per signal id.
    heishamon
        HeishaMon liveness and board status.
    errors
        Last parse error per signal id.
    error_counts
        Number of parse errors per signal id since the store was created.
    links
        Whether the link to each source kind is up (only sources whose link state
        the shell reports).
    """

    now: Instant
    signals: Mapping[SignalId, SignalView]
    heishamon: HeishaMonStatus
    errors: Mapping[SignalId, ParseError]
    error_counts: Mapping[SignalId, int]
    links: Mapping[SourceKind, bool] = field(default_factory=lambda: MappingProxyType({}))

    def get(self, signal: SignalId) -> SignalView | None:
        """Return the view of ``signal``, or ``None`` when it was never seen."""
        return self.signals.get(signal)

    def value(self, signal: SignalId) -> Value | None:
        """Return the latest value of ``signal`` regardless of freshness."""
        view = self.signals.get(signal)
        return view.value if view is not None else None

    def fresh_value(self, signal: SignalId) -> Value | None:
        """Return the value of ``signal`` only when it is fresh."""
        view = self.signals.get(signal)
        return view.value if view is not None and view.fresh else None

    def __contains__(self, signal: object) -> bool:
        """Whether ``signal`` was ever seen."""
        return signal in self.signals

    def __iter__(self) -> Iterator[SignalView]:
        """Iterate over the signal views."""
        return iter(self.signals.values())


@dataclass(frozen=True, slots=True)
class LinkStatus:
    """Connection state of one source link.

    Parameters
    ----------
    up
        The link is connected.
    confirmed
        Monotonic time the link last proved to work (a successful re-read).
    """

    up: bool
    confirmed: float | None = None


@dataclass(frozen=True, slots=True)
class _Entry:
    """Latest reading of a signal with its confirmation, last invalid payload and change time."""

    reading: Reading
    confirmed: float | None
    invalid: ParseError | None = None
    changed: float | None = None

    @property
    def last_observed(self) -> Instant:
        """Return the receipt time of the newest payload, valid or not."""
        if self.invalid is not None and self.reading.observed < self.invalid.observed:
            return self.invalid.observed
        return self.reading.observed

    @property
    def usable_confirmation(self) -> float | None:
        """Return the confirmation time, ``None`` while the latest payload was invalid."""
        return None if self.invalid is not None else self.confirmed


def confirmation_time(reading: Reading) -> float:
    """Monotonic time at which the source last confirmed a live reading's value.

    The receipt time, moved back by the lag the source reports through its own
    timestamp (never forward: a source clock ahead of ours counts as no lag).
    """
    if reading.source_timestamp is None:
        return reading.observed.monotonic
    lag = (reading.observed.wall - reading.source_timestamp).total_seconds()
    return reading.observed.monotonic - max(0.0, lag)


def _source_time(reading: Reading, stamp: datetime) -> float:
    """Return the monotonic time of the source's own ``stamp``, never later than the receipt.

    Parameters
    ----------
    reading
        Reading whose receipt time anchors the conversion.
    stamp
        Timestamp reported by the source.
    """
    lag = (reading.observed.wall - stamp).total_seconds()
    return reading.observed.monotonic - max(0.0, lag)


class StateStore:
    """Latest reading per signal, HeishaMon heartbeats and parse diagnostics.

    Parameters
    ----------
    policy
        Staleness rules.
    """

    def __init__(self, policy: StalenessPolicy | None = None) -> None:
        self.policy = policy or StalenessPolicy()
        self._entries: dict[SignalId, _Entry] = {}
        self._heartbeat: Heartbeat | None = None
        self._intervals: deque[float] = deque(maxlen=LIVENESS_HISTORY)
        self._lwt: LwtNotice | None = None
        self._errors: dict[SignalId, ParseError] = {}
        self._error_counts: Counter[SignalId] = Counter()
        self._links: dict[SourceKind, LinkStatus] = {}
        self.ignored = 0

    def copy(self) -> StateStore:
        """Return an independent copy (for forking a replay)."""
        clone = StateStore(self.policy)
        clone._entries = dict(self._entries)
        clone._heartbeat = self._heartbeat
        clone._intervals = deque(self._intervals, maxlen=LIVENESS_HISTORY)
        clone._lwt = self._lwt
        clone._errors = dict(self._errors)
        clone._error_counts = Counter(self._error_counts)
        clone._links = dict(self._links)
        clone.ignored = self.ignored
        return clone

    def set_link(self, source: SourceKind, up: bool, now: Instant | None = None) -> None:
        """Record the state of the link to ``source``.

        Parameters
        ----------
        source
            Source kind.
        up
            Whether the link is connected.
        now
            When the link proved to work (a successful re-read); omitted keeps the
            previous proof while connected.
        """
        previous = self._links.get(source)
        if not up:
            self._links[source] = LinkStatus(False)
        elif now is not None:
            self._links[source] = LinkStatus(True, now.monotonic)
        else:
            kept = previous.confirmed if previous is not None and previous.up else None
            self._links[source] = LinkStatus(True, kept)

    def link_up(self, source: SourceKind, now: Instant) -> bool:
        """Whether the link to ``source`` is up at ``now`` (see the module docstring)."""
        status = self._links.get(source)
        if status is None or not status.up:
            return False
        window = self.policy.link_window(source)
        if window is None:
            return True
        return status.confirmed is not None and now.monotonic - status.confirmed <= window

    def apply(self, item: ParseResult) -> bool:
        """Apply one parse result.

        Parameters
        ----------
        item
            A reading, heartbeat, LWT notice, parse error or ignored input.

        Returns
        -------
        bool
            Whether the store's signal state or liveness changed.
        """
        match item:
            case Reading():
                return self._apply_reading(item)
            case Heartbeat():
                return self._apply_heartbeat(item)
            case LwtNotice():
                self._lwt = item
                return False
            case ParseError():
                self._errors[item.signal] = item
                self._error_counts[item.signal] += 1
                return self._invalidate(item)
            case Ignored():
                self.ignored += 1
                return False

    def _apply_heartbeat(self, heartbeat: Heartbeat) -> bool:
        """Record a live heartbeat and its interval, returning whether it was taken."""
        if heartbeat.retained:
            return False
        previous = self._heartbeat
        if previous is not None and heartbeat.observed < previous.observed:
            return False
        if previous is not None:
            interval = heartbeat.observed.since(previous.observed)
            if 0.0 < interval <= self.policy.liveness_ceiling_s:
                self._intervals.append(interval)
        self._heartbeat = heartbeat
        return True

    def _invalidate(self, error: ParseError) -> bool:
        """Mark the signal's reading invalid, returning whether it was usable before."""
        existing = self._entries.get(error.signal)
        if error.retained or existing is None or error.observed < existing.last_observed:
            return False
        was_usable = existing.invalid is None
        self._entries[error.signal] = replace(existing, invalid=error)
        return was_usable

    def _apply_reading(self, reading: Reading) -> bool:
        """Store a reading with its confirmation and change times; return whether it was taken.

        Parameters
        ----------
        reading
            The new reading; one observed before the stored one is discarded.

        Returns
        -------
        bool
            Whether the reading was stored.
        """
        existing = self._entries.get(reading.signal)
        if existing is not None and reading.observed < existing.last_observed:
            return False
        same_value = existing is not None and existing.reading.value == reading.value
        if reading.retained:
            if existing is not None and same_value:
                return False
            self._entries[reading.signal] = _Entry(reading, None)
            return True
        confirmed = confirmation_time(reading)
        if existing is not None and same_value and existing.usable_confirmation is not None:
            confirmed = max(confirmed, existing.usable_confirmation)
        if reading.source_changed is not None:
            changed = min(_source_time(reading, reading.source_changed), confirmed)
        elif existing is not None and same_value and existing.changed is not None:
            changed = existing.changed
        else:
            changed = confirmed
        self._entries[reading.signal] = _Entry(reading, confirmed, changed=changed)
        return True

    def latest(self, signal: SignalId) -> Reading | None:
        """Return the latest reading of ``signal``."""
        entry = self._entries.get(signal)
        return entry.reading if entry is not None else None

    def signals(self) -> frozenset[SignalId]:
        """Return the ids of all signals seen so far."""
        return frozenset(self._entries)

    def age(self, signal: SignalId, now: Instant) -> float | None:
        """Seconds since ``signal`` (or one of its liveness signals) last confirmed it.

        ``None`` when it never was. Never negative: an observation stamped after
        ``now`` has age 0.
        """
        entry = self._entries.get(signal)
        if entry is None:
            return None
        confirmed, _ = self._alive(signal, entry)
        return None if confirmed is None else max(0.0, now.monotonic - confirmed)

    def max_age(self, signal: SignalId, now: Instant | None = None) -> float | None:
        """Maximum age of ``signal`` under the policy, ``None`` for unseen signals.

        With ``now`` a held signal's limit follows its link state at that instant;
        without, the limit of an up link.
        """
        entry = self._entries.get(signal)
        if entry is None:
            return None
        source = entry.reading.source
        link = True if now is None else self.link_up(source, now)
        return self.policy.max_age(signal, source, link)

    def is_fresh(self, signal: SignalId, now: Instant) -> bool:
        """Whether ``signal`` has a valid, confirmed value no older than its maximum age."""
        view = self.view(signal, now)
        return view is not None and view.fresh

    def heartbeat_age(self, now: Instant) -> float | None:
        """Seconds since the last live HeishaMon ``stats``."""
        if self._heartbeat is None:
            return None
        return max(0.0, now.since(self._heartbeat.observed))

    def liveness_window(self) -> float:
        """Return the liveness window derived from the observed ``stats`` cadence."""
        return self.policy.liveness_window(self._intervals)

    def heishamon_alive(self, now: Instant) -> bool:
        """Whether a live ``stats`` arrived within the liveness window."""
        age = self.heartbeat_age(now)
        return age is not None and age <= self.liveness_window()

    def heishamon_status(self, now: Instant) -> HeishaMonStatus:
        """Return liveness and board status at ``now``."""
        heartbeat = self._heartbeat
        return HeishaMonStatus(
            alive=self.heishamon_alive(now),
            heartbeat_age=self.heartbeat_age(now),
            lwt_online=self._lwt.online if self._lwt is not None else None,
            version=heartbeat.version if heartbeat is not None else None,
            uptime_s=heartbeat.uptime_s if heartbeat is not None else None,
            window_s=self.liveness_window(),
        )

    def view(self, signal: SignalId, now: Instant) -> SignalView | None:
        """Return the view of one signal at ``now``."""
        entry = self._entries.get(signal)
        if entry is None:
            return None
        reading = entry.reading
        confirmed, alive_by = self._alive(signal, entry)
        age = None if confirmed is None else max(0.0, now.monotonic - confirmed)
        held = None if entry.changed is None else max(0.0, now.monotonic - entry.changed)
        limit = self.policy.max_age(signal, reading.source, self.link_up(reading.source, now))
        invalid = entry.invalid
        return SignalView(
            signal=signal,
            value=reading.value,
            unit=reading.unit,
            source=reading.source,
            observed=reading.observed,
            age=age,
            max_age=limit,
            fresh=invalid is None and age is not None and age <= limit,
            retained=reading.retained,
            source_timestamp=reading.source_timestamp,
            reason=None if invalid is None else f"{invalid.kind.value}: {invalid.detail}",
            held=held,
            alive_by=alive_by,
            source_unit=reading.source_unit,
        )

    def _alive(self, signal: SignalId, entry: _Entry) -> tuple[float | None, SignalId | None]:
        """Return the newest confirmation of ``signal`` and the sibling that supplied it, if any."""
        newest, by = entry.confirmed, None
        for sibling in self.policy.confirmed_by.get(signal, ()):
            other = self._entries.get(sibling)
            when = None if other is None else other.usable_confirmation
            if when is not None and (newest is None or when > newest):
                newest, by = when, sibling
        return newest, by

    def snapshot(self, now: Instant) -> Snapshot:
        """Return an immutable view of every signal at ``now``."""
        views: dict[SignalId, SignalView] = {}
        for signal in self._entries:
            view = self.view(signal, now)
            if view is not None:
                views[signal] = view
        return Snapshot(
            now=now,
            signals=MappingProxyType(views),
            heishamon=self.heishamon_status(now),
            errors=MappingProxyType(dict(self._errors)),
            error_counts=MappingProxyType(dict(self._error_counts)),
            links=MappingProxyType({source: self.link_up(source, now) for source in self._links}),
        )
