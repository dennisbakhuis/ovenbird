"""Cross-field rules of the plain MQTT inputs: they never stand in for the pump's own data.

A plain input may not read a topic of the HeishaMon board itself (``<base>/main``,
``<base>/commands``, ``<base>/stats``, ``<base>/LWT``), may not produce a reserved signal
id (the HeishaMon catalogue, ``main/``, ``ha/``, ...; see
:func:`ovenbird_core.inputs.reserved_signal`) and lists each topic and each signal once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovenbird.config.values import Issue
from ovenbird_core import HeishaMonParser
from ovenbird_core.inputs import reserved_signal

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings

FIELD = "mqtt_inputs"


def input_issues(settings: Settings) -> list[Issue]:
    """Return the violated rules of the plain MQTT inputs, at most one per input.

    Parameters
    ----------
    settings
        Field-validated settings.

    Returns
    -------
    list of Issue
        ``input_topic_reserved``, ``input_topic_repeated``, ``input_signal_reserved`` or
        ``input_signal_repeated``, each with the input's ``path``.
    """
    board = HeishaMonParser(settings.heishamon_base)
    topics: set[str] = set()
    signals: set[str] = set()
    issues: list[Issue] = []
    for index, item in enumerate(settings.mqtt_inputs):
        issue = _input_issue(index, item.topic, item.signal_id, board, topics, signals)
        topics.add(item.topic)
        signals.add(item.signal_id)
        if issue is not None:
            issues.append(issue)
    return issues


def _input_issue(
    index: int,
    topic: str,
    signal: str,
    board: HeishaMonParser,
    topics: set[str],
    signals: set[str],
) -> Issue | None:
    if board.reserves(topic):
        return Issue(
            FIELD,
            "input_topic_reserved",
            f"topic {topic!r} belongs to the HeishaMon board itself (main, commands, stats, "
            "LWT below the HeishaMon base) and cannot be an extra sensor",
            {"path": f"{index}.topic", "topic": topic},
        )
    if topic in topics:
        return Issue(
            FIELD,
            "input_topic_repeated",
            f"topic {topic!r} is listed twice",
            {"path": f"{index}.topic", "topic": topic},
        )
    if reserved_signal(signal):
        return Issue(
            FIELD,
            "input_signal_reserved",
            f"signal {signal!r} is reserved for the heat pump, Home Assistant or the service "
            "(HeishaMon signals, stats, LWT, the board's command ids and the prefixes main/, "
            "ha/ and derived/)",
            {"path": f"{index}.signal", "signal": signal},
        )
    if signal in signals:
        return Issue(
            FIELD,
            "input_signal_repeated",
            f"signal {signal!r} is used by another MQTT input",
            {"path": f"{index}.signal", "signal": signal},
        )
    return None
