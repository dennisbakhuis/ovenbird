"""The go-live checklist: one item per condition, from live facts.

**Checklist** (``GET api/v1/trial/status``): one item per condition, each ``ok``,
``warn`` or ``fail`` with its evidence and a message that says what is missing, in two
groups. Before go-live (``phase: go_live``, all ``ok`` = ``ready``), all of them
possible in shadow:

- ``shadow_days``: time in shadow in the decision journal, gaps between
  ticks counted up to two intervals; ok from :data:`SHADOW_DAYS_REQUIRED` days;
- ``divergence``: the last 14 days of :mod:`ovenbird.trial.divergence`; fail
  without compared data, warn below 80 % coverage or with episodes of
  :data:`LONG_EPISODE_MIN` minutes or longer that nobody marked as explained
  (``POST api/v1/shadow/episodes/explain``, audited, kept in ``config.db``);
- ``envelope_rule``: declared installed;
- ``notifications``: the notifier's health (:meth:`ovenbird.notify.notifier.Notifier.health`,
  the same verdict as the status tile) and the dead-man ping alive;
- ``release_plan``: a dry rehearsal (or a real one) planned every setting against a
  complete snapshot without a refusal;
- ``alarms``: no active critical alarm (warnings warn);
- ``room``: the room value is fresh and trusted (cross-check, cooling authority);
- ``pump_snapshot``: an armed, complete snapshot that is not stale (captured by
  hand in shadow, or the go-live one).

In the first trial (``phase: trial``; everything ``ok`` = ``ready_for_cutover``):

- ``envelope_proof``: the envelope rule seen correcting the pump while ovenbird is
  the only controller (the stop-the-service test);
- ``rollback_rehearsal``: a rehearsed release that restored everything within 5 min.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from ovenbird.clock import iso_from_unix, iso_z
from ovenbird.control.alarms import Severity
from ovenbird.history.schema import connect
from ovenbird.trial.release import REHEARSAL_LIMIT_S
from ovenbird_core import Instant

if TYPE_CHECKING:
    from ovenbird.config import Settings
    from ovenbird.control.loop import ControlLoop
    from ovenbird.notify.notifier import Notifier

DAY_S: Final = 86_400.0
SHADOW_DAYS_REQUIRED: Final = 14.0
DIVERGENCE_DAYS: Final = 14
LONG_EPISODE_MIN: Final = 120
MIN_COVERAGE: Final = 0.8
CHECK_IDS: Final = (
    "shadow_days",
    "divergence",
    "envelope_rule",
    "notifications",
    "release_plan",
    "alarms",
    "room",
    "pump_snapshot",
    "envelope_proof",
    "rollback_rehearsal",
)
GO_LIVE: Final = "go_live"
TRIAL: Final = "trial"
PHASES: Final = (GO_LIVE, TRIAL)
PHASE_OF: Final = {
    **dict.fromkeys(CHECK_IDS, GO_LIVE),
    "envelope_proof": TRIAL,
    "rollback_rehearsal": TRIAL,
}
CHECK_STATUSES: Final = ("ok", "warn", "fail")
OK: Final = "ok"
WARN: Final = "warn"
FAIL: Final = "fail"


def item(id_: str, status: str, message: str, **evidence: Any) -> dict[str, Any]:
    """Return one checklist item.

    Parameters
    ----------
    id_
        Checklist item id.
    status
        Result of the check: pass, warn or fail.
    message
        Explanation for the operator.
    **evidence
        Facts the check was based on, stored with the item.
    """
    return {
        "id": id_,
        "phase": PHASE_OF[id_],
        "status": status,
        "message": message,
        "evidence": evidence,
    }


def shadow_seconds(path: Path, interval_s: float) -> tuple[float, float | None, float | None]:
    """Return the seconds in shadow in the decision journal, and its first and last tick.

    Each shadow tick counts the time since the tick before, at most two intervals,
    so gaps (the service stopped) are not counted.
    """
    if not path.exists():
        return 0.0, None, None
    conn = connect(path, read_only=True)
    try:
        if (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'decision'"
            ).fetchone()
            is None
        ):
            return 0.0, None, None
        row = conn.execute(
            "SELECT COALESCE(SUM(MIN(ts - prev, ?)), 0), MIN(ts), MAX(ts) FROM ("
            "SELECT ts, mode, LAG(ts) OVER (ORDER BY ts, id) AS prev FROM decision) "
            "WHERE mode = 'shadow' AND prev IS NOT NULL",
            (2.0 * interval_s,),
        ).fetchone()
    except sqlite3.Error:
        return 0.0, None, None
    finally:
        conn.close()
    total, first, last = row
    return float(total or 0.0), first, last


def shadow_days_item(
    settings: Settings, shadow: tuple[float, float | None, float | None]
) -> dict[str, Any]:
    """Return the ``shadow_days`` item from the time in shadow (:func:`shadow_seconds`)."""
    seconds, first, last = shadow
    days = round(seconds / DAY_S, 2)
    evidence = {
        "days": days,
        "required_days": SHADOW_DAYS_REQUIRED,
        "first": None if first is None else iso_from_unix(float(first)),
        "last": None if last is None else iso_from_unix(float(last)),
        "journal_days": settings.history_decision_days,
    }
    if days >= SHADOW_DAYS_REQUIRED:
        return item("shadow_days", OK, f"{days:.1f} days in shadow", **evidence)
    if days > 0:
        return item(
            "shadow_days",
            WARN,
            f"{days:.1f} of {SHADOW_DAYS_REQUIRED:.0f} days in shadow",
            **evidence,
        )
    return item("shadow_days", FAIL, "no shadow time recorded yet", **evidence)


def divergence_item(body: dict[str, Any]) -> dict[str, Any]:
    """Return the ``divergence`` item from an annotated divergence payload."""
    summary = body["summary"]
    long_all = [ep for ep in body["episodes"] if ep["minutes"] >= LONG_EPISODE_MIN]
    long_ = [ep for ep in long_all if not ep.get("explained")]
    evidence = {
        "days": DIVERGENCE_DAYS,
        "coverage": summary["coverage"],
        "mean_abs_k": summary["mean_abs_k"],
        "max_abs_k": summary["max_abs_k"],
        "hours_over": summary["hours_over"],
        "episodes": summary["episodes"],
        "long_episodes": len(long_),
        "explained_episodes": len(long_all) - len(long_),
        "long_episode_min": LONG_EPISODE_MIN,
        "longest": max(long_, key=lambda ep: ep["minutes"]) if long_ else None,
    }
    if not summary["compared_minutes"]:
        return item("divergence", FAIL, "no comparison data yet", **evidence)
    if summary["coverage"] < MIN_COVERAGE:
        return item(
            "divergence",
            WARN,
            f"the comparison covers {summary['coverage']:.0%} of the last {DIVERGENCE_DAYS} days",
            **evidence,
        )
    if long_:
        return item(
            "divergence",
            WARN,
            f"{len(long_)} episodes of {LONG_EPISODE_MIN} min or longer to review; mark "
            "each as explained in Compare once you know why",
            **evidence,
        )
    if long_all:
        return item(
            "divergence",
            OK,
            f"{len(long_all)} long episodes, all marked as explained",
            **evidence,
        )
    return item("divergence", OK, "no long divergence", **evidence)


def envelope_item(loop: ControlLoop | None, now: Instant) -> dict[str, Any]:
    """Return the ``envelope_rule`` item from the envelope watch."""
    watch = loop.envelope if loop is not None else None
    if watch is None:
        return item("envelope_rule", FAIL, "no control loop")
    status = watch.status(now)["envelope_rule"]
    evidence = {
        "installed": status["installed"],
        "count": status["count"],
        "last": status["last"],
    }
    match status["state"]:
        case "proven":
            return item("envelope_rule", OK, "installed and seen acting", **evidence)
        case "declared":
            return item(
                "envelope_rule",
                OK,
                "declared installed; prove it in the first trial by stopping the service",
                **evidence,
            )
        case _:
            return item(
                "envelope_rule",
                FAIL,
                "not declared installed (OVENBIRD_ENVELOPE_RULE_INSTALLED)",
                **evidence,
            )


def envelope_proof_item(loop: ControlLoop | None, now: Instant) -> dict[str, Any]:
    """Return the ``envelope_proof`` item: the envelope rule seen correcting the pump."""
    watch = loop.envelope if loop is not None else None
    if watch is None:
        return item("envelope_proof", FAIL, "no control loop")
    status = watch.status(now)["envelope_rule"]
    evidence = {"count": status["count"], "last": status["last"]}
    if status["state"] == "proven":
        return item("envelope_proof", OK, "seen correcting the pump", **evidence)
    return item(
        "envelope_proof",
        WARN,
        "not seen acting yet: while ovenbird controls, stop the service at night-time load "
        "and let the rule correct the setpoint",
        **evidence,
    )


def notifications_item(notifier: Notifier | None) -> dict[str, Any]:
    """Return the ``notifications`` item from the notifier's health and dead-man ping."""
    if notifier is None or not notifier.configured:
        return item(
            "notifications",
            FAIL,
            "ntfy is not configured (OVENBIRD_NOTIFY_NTFY_URL and _TOPIC)",
            health=None if notifier is None else notifier.health(),
        )
    status = notifier.status()
    health = status["health"]
    deadman = status["deadman"]
    evidence = {
        "health": health,
        "last_test": status["ntfy"]["last_test"],
        "last_sent": status["ntfy"]["last_sent"],
        "last_error": status["ntfy"]["last_error"],
        "deadman_configured": deadman["configured"],
        "deadman_last_ok": deadman["last_ok"],
    }
    match health["state"]:
        case "failing":
            return item(
                "notifications", FAIL, f"alerts do not arrive: {health['reason']}", **evidence
            )
        case "untested":
            return item(
                "notifications", WARN, "no test notification sent yet; send one", **evidence
            )
    match health["deadman_state"]:
        case "not_configured":
            return item(
                "notifications",
                WARN,
                "no dead-man ping configured (OVENBIRD_NOTIFY_DEADMAN_URL)",
                **evidence,
            )
        case "waiting":
            return item(
                "notifications", WARN, "the dead-man ping has not succeeded yet", **evidence
            )
        case "failing":
            return item("notifications", WARN, "the last dead-man ping failed", **evidence)
        case "skipped":
            return item(
                "notifications",
                WARN,
                f"the dead-man ping is held back: {deadman['last_skip']}",
                **evidence,
            )
    return item("notifications", OK, "alerts arrive; dead-man ping alive", **evidence)


def release_plan_item(loop: ControlLoop | None) -> dict[str, Any]:
    """Return the ``release_plan`` item: a rehearsal planned every setting."""
    release = loop.release if loop is not None else None
    if release is None:
        return item("release_plan", FAIL, "no control loop")
    candidates = [
        run
        for run in (release.last_rehearsal(), release.last_dry_rehearsal())
        if isinstance(run, dict) and run.get("outcome") == "ok"
    ]
    latest = release.last_dry_rehearsal() or release.last_rehearsal()
    evidence = {"last": latest}
    if candidates:
        best = max(candidates, key=lambda run: str(run.get("started_at")))
        kind = "dry rehearsal" if best.get("dry") else "rehearsal"
        return item("release_plan", OK, f"a {kind} planned every setting", last=best)
    if latest is not None:
        failed = [
            entry["kind"]
            for entry in latest.get("items", [])
            if isinstance(entry, dict) and not entry.get("ok")
        ]
        return item(
            "release_plan",
            WARN,
            f"the last rehearsal could not plan: {', '.join(failed) or 'unknown'}",
            **evidence,
        )
    return item(
        "release_plan",
        FAIL,
        "no rehearsal yet: capture a snapshot, then run a dry rehearsal",
        **evidence,
    )


def rehearsal_item(loop: ControlLoop | None) -> dict[str, Any]:
    """Return the ``rollback_rehearsal`` item: a release that restored everything in time."""
    release = loop.release if loop is not None else None
    last = release.last_rehearsal() if release is not None else None
    if last is None:
        return item(
            "rollback_rehearsal",
            FAIL,
            "no rehearsal yet: possible once ovenbird controls (release, then resume)",
            last=None,
        )
    duration = last.get("duration_s")
    evidence = {"last": last, "limit_s": REHEARSAL_LIMIT_S}
    if last.get("outcome") != "ok":
        return item(
            "rollback_rehearsal",
            WARN,
            f"the last rehearsal ended {last.get('outcome')}: not everything was restored",
            **evidence,
        )
    if duration is None or duration > REHEARSAL_LIMIT_S:
        return item("rollback_rehearsal", WARN, "the last rehearsal took too long", **evidence)
    return item("rollback_rehearsal", OK, f"rehearsed in {duration:.0f} s", **evidence)


def alarms_item(loop: ControlLoop | None) -> dict[str, Any]:
    """Return the ``alarms`` item: no active critical alarm."""
    active = loop.alarms.active() if loop is not None else ()
    critical = [a.code.value for a in active if a.severity is Severity.CRITICAL]
    warning = [a.code.value for a in active if a.severity is Severity.WARNING]
    evidence = {"critical": critical, "warning": warning}
    if critical:
        return item("alarms", FAIL, "critical alarms are active", **evidence)
    if warning:
        return item("alarms", WARN, "warnings are active", **evidence)
    return item("alarms", OK, "no open alarms", **evidence)


def room_item(loop: ControlLoop | None, now: Instant) -> dict[str, Any]:
    """Return the ``room`` item: the room value is fresh and trusted."""
    room = loop.room_status(now) if loop is not None else None
    if room is None:
        return item("room", FAIL, "no room signal configured")
    evidence = {
        key: room.get(key)
        for key in ("signal", "value", "fresh", "plausible", "authority", "held_s", "alive_s")
    }
    if not room["fresh"]:
        return item("room", FAIL, "the room value is not fresh", **evidence)
    if room.get("plausible") is False:
        return item("room", WARN, "the cross-check does not trust the room value", **evidence)
    authority = room.get("authority")
    if authority is not None and authority < 1.0:
        return item("room", WARN, "the room value is held long; reduced authority", **evidence)
    return item("room", OK, "the room value is fresh and trusted", **evidence)


def snapshot_item(loop: ControlLoop | None, now: Instant) -> dict[str, Any]:
    """Return the ``pump_snapshot`` item: an armed, complete and recent snapshot.

    Parameters
    ----------
    loop
        Control loop holding the pump snapshot; ``None`` without one.
    now
        Time of the check.
    """
    release = loop.release if loop is not None else None
    if release is None:
        return item("pump_snapshot", WARN, "no control loop")
    snapshot = release.snapshot
    if snapshot is None:
        return item(
            "pump_snapshot",
            WARN,
            "no snapshot yet: capture one in shadow; the go-live records its own",
            snapshot=None,
        )
    body = snapshot.to_json(now.wall)
    if not snapshot.armed:
        return item(
            "pump_snapshot",
            WARN,
            "used by a release; capture a new one, or the next go-live records it",
            snapshot=body,
        )
    if not snapshot.complete:
        return item(
            "pump_snapshot", WARN, "some values were not known when it was taken", snapshot=body
        )
    days = snapshot.age_s(now.wall) / DAY_S
    if snapshot.stale(now.wall):
        return item(
            "pump_snapshot",
            WARN,
            f"taken {days:.0f} days ago; capture a new one",
            snapshot=body,
        )
    if snapshot.origin == "manual":
        return item(
            "pump_snapshot",
            OK,
            "captured in shadow; the go-live records the values of that moment",
            snapshot=body,
        )
    return item("pump_snapshot", OK, "recorded at go-live", snapshot=body)


def build_checklist(
    settings: Settings,
    loop: ControlLoop | None,
    notifier: Notifier | None,
    now: Instant,
    facts: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the go-live checklist, in its fixed order.

    Parameters
    ----------
    settings
        The effective settings.
    loop
        The control loop (with ``release`` and ``envelope``), if any.
    notifier
        The notifier, if any.
    now
        Current instant.
    facts
        The facts read from ``history.db`` (``shadow`` and ``divergence``).

    Returns
    -------
    list of dict
        One item per entry of :data:`CHECK_IDS`.
    """
    return [
        shadow_days_item(settings, facts["shadow"]),
        divergence_item(facts["divergence"]),
        envelope_item(loop, now),
        notifications_item(notifier),
        release_plan_item(loop),
        alarms_item(loop),
        room_item(loop, now),
        snapshot_item(loop, now),
        envelope_proof_item(loop, now),
        rehearsal_item(loop),
    ]


def counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Return how many items are ``ok``, ``warn`` and ``fail``."""
    return {status: sum(1 for e in entries if e["status"] == status) for status in (OK, WARN, FAIL)}


def group(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return one phase's readiness, counts and item ids."""
    return {
        "ready": all(entry["status"] == OK for entry in entries),
        "counts": counts(entries),
        "ids": [entry["id"] for entry in entries],
    }


def status_body(
    now: Instant,
    loop: ControlLoop | None,
    items: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Return the body of ``GET api/v1/trial/status`` from the checklist and summary.

    Parameters
    ----------
    now
        Time of the status.
    loop
        Control loop, ``None`` without one.
    items
        Checklist items.
    summary
        Trial summary.
    """
    groups = {
        phase: group([entry for entry in items if entry["phase"] == phase]) for phase in PHASES
    }
    return {
        "at": iso_z(now.wall),
        "mode": None if loop is None else loop.effective_mode.value,
        "configured_mode": None if loop is None else loop.mode.value,
        "ready": groups[GO_LIVE]["ready"],
        "ready_for_cutover": all(entry["status"] == OK for entry in items),
        "not_ready": [
            {"id": entry["id"], "message": entry["message"]}
            for entry in items
            if entry["phase"] == GO_LIVE and entry["status"] != OK
        ],
        "counts": counts(items),
        "groups": groups,
        "checklist": items,
        "summary": summary,
    }
