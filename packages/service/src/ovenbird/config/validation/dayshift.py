"""Rules of the sun day shift settings, and the acknowledgement ``on`` needs.

``control_dayshift_use`` accepts ``off``, ``shadow`` and ``on``. The day shift is
experimental (its simulator evaluation did not pass: ``docs/evaluation/dayshift.md``), so
``on`` is valid only together with ``control_dayshift_experimental_ok``; ``on`` without
it is refused (``dayshift_on_needs_ack``), whether ``on`` is the change or the
acknowledgement is being taken back. A stored or deployed configuration can therefore
never be ``on`` without it.
The windows must follow each other through the day (``dayshift_windows``): the day
window does not wrap midnight and, going forward from its end, the night starts, ends
and the comfort time comes before the next day window starts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from ovenbird.config.values import Issue
from ovenbird.control.dayshift import params_from_settings, window_problem

if TYPE_CHECKING:
    from ovenbird.config.settings import Settings

WINDOW_FIELDS: Final = {
    "day": "control_dayshift_day_end",
    "night": "control_dayshift_night_start",
    "comfort": "control_dayshift_comfort_at",
}

NEEDS_ACK_MESSAGE: Final = (
    "the sun day shift is experimental: switching it on needs "
    "control_dayshift_experimental_ok; use shadow otherwise"
)


def dayshift_issues(settings: Settings) -> list[Issue]:
    """Return the refusal of ``on`` without the acknowledgement and window problems."""
    issues: list[Issue] = []
    if settings.control_dayshift_use == "on" and not settings.control_dayshift_experimental_ok:
        issues.append(Issue("control_dayshift_use", "dayshift_on_needs_ack", NEEDS_ACK_MESSAGE))
    problem = window_problem(params_from_settings(settings))
    if problem is not None:
        part, message = problem
        issues.append(Issue(WINDOW_FIELDS[part], "dayshift_windows", message))
    return issues
