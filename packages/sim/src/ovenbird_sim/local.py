"""Install-specific settings kept next to the local captures, never committed.

The tracked tree only knows a generic example install: entity names such as
``sensor.living_room_temperature``, example comfort and pump values, placeholder
hosts. The real install's values live in ``$CAPTURES_DIR/local.env`` (default
``capture/captures/local.env``, git-ignored with the captures), so the checks on
recorded data run against the names and values the recording was made with.

The file holds ``NAME = value`` lines (``#`` starts a comment line). The Makefile
includes it, so a value there replaces the Makefile's default; the Python code reads
it through :func:`settings`. Entity names map with ``ENTITY.<generic id> = <real id>``.
Without the file every lookup returns the example value: the ``EXAMPLE_*``
constants here are the example install's comfort temperature, minimum water
setpoint and pump duties (the duties are the controller's own defaults).

Examples
--------
A minimal file::

    COMFORT_C = 21.0
    ENTITY.sensor.living_room_temperature = sensor.lounge_temperature
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

CAPTURES_ENV: Final = "CAPTURES_DIR"
CAPTURES: Final = Path("capture/captures")
SETTINGS_FILE: Final = "local.env"
ENTITY_PREFIX: Final = "ENTITY."
EXAMPLE_COMFORT_C: Final = 21.0
EXAMPLE_MIN_SETPOINT_C: Final = 24.0
EXAMPLE_PUMP_DUTY_HEAT: Final = 159
EXAMPLE_PUMP_DUTY_IDLE: Final = 102


def captures_dir() -> Path:
    """Return the local captures directory: ``$CAPTURES_DIR`` or ``capture/captures``."""
    configured = os.environ.get(CAPTURES_ENV)
    return Path(configured) if configured else CAPTURES


def settings_path() -> Path:
    """Return where the local settings file is looked for."""
    return captures_dir() / SETTINGS_FILE


def parse(text: str) -> dict[str, str]:
    """Return the ``NAME = value`` pairs of a settings file's text."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip().removesuffix("?").removesuffix(":").strip()] = value.strip()
    return values


def settings(path: Path | None = None) -> dict[str, str]:
    """Return the local settings, empty when the file does not exist."""
    chosen = path or settings_path()
    return parse(chosen.read_text(encoding="utf-8")) if chosen.is_file() else {}


def value(name: str, default: str) -> str:
    """Return the local value of ``name``, or ``default``."""
    return settings().get(name) or default


def number(name: str, default: float) -> float:
    """Return the local value of ``name`` as a number, or ``default``."""
    return float(value(name, str(default)))


def entity(generic: str) -> str:
    """Return this install's entity id for the generic ``generic``, or ``generic`` itself."""
    return value(ENTITY_PREFIX + generic, generic)
