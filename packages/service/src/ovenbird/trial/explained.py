"""Divergence episodes marked as explained (``POST api/v1/shadow/episodes/explain``).

A mark covers the episode whose span contains its start; marks are audited
(``divergence_explain``) and kept in ``config.db`` (:mod:`ovenbird.system.facts`), at
most :data:`MAX_EXPLAINED` of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from ovenbird.clock import iso_from_unix, iso_z
from ovenbird.system.privacy import public_name
from ovenbird_core import Instant

if TYPE_CHECKING:
    from ovenbird.configstore import Actor, ConfigManager
    from ovenbird.system.facts import Facts

EXPLAINED_KEY: Final = "divergence_explained"
EXPLAIN_AUDIT: Final = "divergence_explain"
MAX_NOTE: Final = 500
MAX_EXPLAINED: Final = 500


def _unix(text: Any) -> float | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def explanation_for(episode: Mapping[str, Any], marks: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the explanation covering ``episode`` (its start lies within it), if any."""
    start = _unix(episode.get("start"))
    end = _unix(episode.get("end"))
    if start is None or end is None:
        return None
    for mark in marks.values():
        at = mark.get("start_ts") if isinstance(mark, dict) else None
        if isinstance(at, int | float) and start <= at <= end:
            return {
                "note": mark.get("note"),
                "by": public_name(mark.get("by")),
                "at": mark.get("at"),
                "start": mark.get("start"),
            }
    return None


def annotate(body: dict[str, Any], marks: Mapping[str, Any]) -> dict[str, Any]:
    """Add ``explained`` to every episode of a divergence payload (in place); returns it."""
    for episode in body.get("episodes", []):
        episode["explained"] = explanation_for(episode, marks)
    return body


def explanations(facts: Facts) -> dict[str, Any]:
    """Return the divergence episodes marked as explained, by their start."""
    stored = facts.get(EXPLAINED_KEY)
    return stored if isinstance(stored, dict) else {}


def explain(
    facts: Facts,
    config: ConfigManager | None,
    actor: Actor,
    start: datetime,
    note: str | None,
    moment: Instant,
) -> dict[str, Any]:
    """Mark the divergence episode starting at ``start`` as explained (``None`` unmarks).

    Parameters
    ----------
    facts
        Where the marks are kept.
    config
        The configuration manager that audits the mark, if any.
    actor
        Who judged it (audited, ``divergence_explain``).
    start
        The episode's start (any minute of it).
    note
        Why the divergence is explained; ``None`` removes the mark.
    moment
        Current instant.

    Returns
    -------
    dict
        The stored mark, or ``None`` after a removal, under ``explained``.
    """
    stamp = start.astimezone(UTC).timestamp()
    key = iso_from_unix(stamp)
    marks = dict(explanations(facts))
    mark: dict[str, Any] | None = None
    if note is None:
        marks.pop(key, None)
    else:
        mark = {"start": key, "start_ts": stamp, "note": note, "by": actor.name}
        mark["at"] = iso_z(moment.wall)
        marks[key] = mark
        if len(marks) > MAX_EXPLAINED:
            for old in sorted(marks)[: len(marks) - MAX_EXPLAINED]:
                del marks[old]
    facts.set(EXPLAINED_KEY, marks)
    if config is not None:
        config.audit(actor, EXPLAIN_AUDIT, {"start": key, "note": note})
    public = None if mark is None else {**mark, "by": public_name(mark["by"])}
    return {"explained": public}
