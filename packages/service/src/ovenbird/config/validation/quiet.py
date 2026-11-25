"""Field rules of the quiet-mode windows: clock times and non-empty windows."""

from __future__ import annotations

import re
from typing import Final

from pydantic_core import PydanticCustomError

CLOCK_TIME_RE: Final = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


def check_clock_time(value: str) -> str:
    """Return ``value`` when it is a local time ``HH:MM``.

    Raises
    ------
    PydanticCustomError
        ``clock_time`` otherwise.
    """
    if CLOCK_TIME_RE.fullmatch(value) is None:
        raise PydanticCustomError("clock_time", "times must be written HH:MM")
    return value


def check_window(start: str, end: str) -> None:
    """Refuse a quiet window that starts where it ends.

    Raises
    ------
    PydanticCustomError
        ``window_empty`` when ``start == end``.
    """
    if start == end:
        raise PydanticCustomError("window_empty", "a quiet window needs start != end")
