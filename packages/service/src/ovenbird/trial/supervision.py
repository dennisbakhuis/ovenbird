"""Shadow and trial facts: what the shadow, trial and system endpoints read.

:class:`Supervision` bundles the runtime, the control loop (with its release manager
and envelope watch), the configuration manager, the notifier and the persistent
facts. The go-live checklist is built in :mod:`ovenbird.trial.checklist`, the trial
summary in :mod:`ovenbird.trial.summary`, the explained divergence episodes in
:mod:`ovenbird.trial.explained` and the "about" page in :mod:`ovenbird.system.about`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ovenbird.system.about import about_body
from ovenbird.trial import checklist as checks
from ovenbird.trial import explained
from ovenbird.trial import summary as summaries
from ovenbird.trial.checklist import DAY_S, DIVERGENCE_DAYS, shadow_seconds
from ovenbird.trial.divergence import divergence_payload
from ovenbird.trial.explained import annotate
from ovenbird_core import Instant

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.configstore import Actor, ConfigManager
    from ovenbird.control.loop import ControlLoop
    from ovenbird.notify.notifier import Notifier
    from ovenbird.runtime import Runtime
    from ovenbird.system.facts import Facts


@dataclass
class Supervision:
    """What the shadow, trial and system endpoints read.

    Parameters
    ----------
    runtime
        Clock, state store and component health.
    current
        Returns the effective settings.
    control
        The control loop (with ``release`` and ``envelope``), if any.
    config
        The configuration manager, if any.
    notifier
        The notifier, if any.
    facts
        Persistent facts.
    started
        When this service instance started.
    starts
        The service start count (see :func:`ovenbird.system.about.record_start`).
    """

    runtime: Runtime
    current: Callable[[], Settings]
    control: ControlLoop | None
    config: ConfigManager | None
    notifier: Notifier | None
    facts: Facts
    started: Instant
    starts: dict[str, Any] | None = None

    def now(self) -> Instant:
        """Return the service clock's now."""
        return self.runtime.clock()

    def healthy_reason(self) -> str | None:
        """Return why the control loop is not healthy, ``None`` when it is (dead-man)."""
        now = self.now()
        runtime = self.runtime
        if not runtime.live:
            return "a component keeps crashing"
        if not runtime.mqtt_connected:
            return "MQTT is disconnected"
        if not runtime.store.heishamon_alive(now):
            return "HeishaMon is not alive"
        history = runtime.history
        if history is not None and not (history.healthy() or history.starting()):
            return "history is not being written"
        loop = self.control
        if loop is None:
            return "no control loop"
        last = loop.last_tick
        if last is None or now.since(last) > 3.0 * loop.interval_s:
            return "the control loop has not ticked recently"
        return None

    def history_facts(
        self,
        now: Instant,
        trial: tuple[float, float] | None = None,
        baseline: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """Return the facts read from ``history.db`` (safe to run in a worker thread).

        Returns
        -------
        dict
            ``shadow`` (seconds, first and last tick), ``divergence`` (the last 14
            days) and ``summary`` (the trial summary).
        """
        settings = self.current()
        end = now.wall.timestamp()
        divergence = divergence_payload(
            settings.history_path,
            start=end - DIVERGENCE_DAYS * DAY_S,
            end=end,
            step=3600,
            timezone=settings.control_timezone,
            interval_s=settings.control_interval_s,
        )
        return {
            "shadow": shadow_seconds(settings.history_path, settings.control_interval_s),
            "divergence": annotate(divergence, self.explanations()),
            "summary": self.summary(now, trial, baseline),
        }

    def explanations(self) -> dict[str, Any]:
        """Return the divergence episodes marked as explained, by their start."""
        return explained.explanations(self.facts)

    def explain(
        self, actor: Actor, start: datetime, note: str | None, now: Instant | None = None
    ) -> dict[str, Any]:
        """Mark the divergence episode starting at ``start`` as explained (``None`` unmarks).

        See :func:`ovenbird.trial.explained.explain`.

        Parameters
        ----------
        actor
            Who marks the episode, for the audit trail.
        start
            Start of the divergence episode.
        note
            Explanation; ``None`` removes the mark.
        now
            Time of the request; the service clock when omitted.
        """
        moment = now or self.now()
        return explained.explain(self.facts, self.config, actor, start, note, moment)

    def checklist(
        self, now: Instant | None = None, history: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Return the go-live checklist from live facts (``history`` from :meth:`history_facts`)."""
        moment = now or self.now()
        settings = self.current()
        facts = history if history is not None else self.history_facts(moment)
        return checks.build_checklist(settings, self.control, self.notifier, moment, facts)

    def _divergence(self, body: dict[str, Any]) -> dict[str, Any]:
        """Return the divergence checklist item for a divergence body."""
        return checks.divergence_item(body)

    def _notifications(self) -> dict[str, Any]:
        """Return the notifications checklist item."""
        return checks.notifications_item(self.notifier)

    def windows(
        self,
        now: Instant,
        trial: tuple[float, float] | None,
        baseline: tuple[float, float] | None,
    ) -> tuple[tuple[float, float], tuple[float, float], str]:
        """Resolve the trial and baseline periods (unix seconds) and where they came from."""
        return summaries.windows(self.control, now, trial, baseline)

    def _period(self, settings: Settings, span: tuple[float, float]) -> dict[str, Any]:
        """Return the summary of a period."""
        return summaries.period(settings, span)

    def summary(
        self,
        now: Instant | None = None,
        trial: tuple[float, float] | None = None,
        baseline: tuple[float, float] | None = None,
    ) -> dict[str, Any]:
        """Return the trial against the baseline on the cut-over criteria."""
        moment = now or self.now()
        settings = self.current()
        trial_span, baseline_span, source = self.windows(moment, trial, baseline)
        ours = self._period(settings, trial_span)
        theirs = self._period(settings, baseline_span)
        state, days = summaries.trial_state(
            self.control, source, trial_span, moment.wall.timestamp()
        )
        return summaries.summary_body(
            source, state, days, ours, theirs, settings.command_daily_budget
        )

    def status(
        self,
        now: Instant | None = None,
        trial: tuple[float, float] | None = None,
        baseline: tuple[float, float] | None = None,
        history: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the body of ``GET api/v1/trial/status``.

        ``history`` is :meth:`history_facts` (computed when omitted).

        Parameters
        ----------
        now
            Time of the status; the service clock when omitted.
        trial
            Trial window as Unix times.
        baseline
            Baseline window as Unix times.
        history
            History facts; computed when omitted.
        """
        moment = now or self.now()
        facts = history if history is not None else self.history_facts(moment, trial, baseline)
        items = self.checklist(moment, facts)
        return checks.status_body(moment, self.control, items, facts["summary"])

    def about(self, now: Instant | None = None) -> dict[str, Any]:
        """Return the body of ``GET api/v1/system/about``."""
        moment = now or self.now()
        settings = self.current()
        return about_body(settings, self.runtime, self.control, self.started, self.starts, moment)
