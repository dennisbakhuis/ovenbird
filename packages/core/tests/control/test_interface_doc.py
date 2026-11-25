"""``docs/control-interface.md`` against the code: dataclass fields and enum values."""

from __future__ import annotations

import re
from dataclasses import fields
from enum import StrEnum
from pathlib import Path

import pytest

from ovenbird_core.control import (
    CommandIntent,
    ControlInputs,
    IntentKind,
    LadderLevel,
    ReasonCode,
    RoomInput,
    RoomProfile,
    StepResult,
)
from ovenbird_core.control.record import DecisionRecord

DOC = Path(__file__).resolve().parents[4] / "docs" / "control-interface.md"
FIELD = re.compile(r"^    (\w+): ")


def documented_fields(name: str) -> list[str]:
    """Return the field names of ``class <name>`` in the doc's code blocks."""
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(rf"class {name}\b", line))
    found: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith(" ") or line.startswith("```"):
            break
        match = FIELD.match(line)
        if match:
            found.append(match.group(1))
    return found


def documented_values(name: str) -> list[str]:
    """Return the values listed in the ``text`` block after the backticked ``name``."""
    text = DOC.read_text(encoding="utf-8")
    section = text.split(f"`{name}`", 1)[1]
    block = section.split("```text", 1)[1].split("```", 1)[0]
    return [item.strip() for item in block.replace("\n", " ").split(",") if item.strip()]


@pytest.mark.parametrize(
    "cls", [ControlInputs, RoomInput, StepResult, CommandIntent, DecisionRecord]
)
def test_dataclass_fields_match_the_doc(cls: type) -> None:
    assert documented_fields(cls.__name__) == [item.name for item in fields(cls)]


@pytest.mark.parametrize("enum", [IntentKind, LadderLevel, ReasonCode, RoomProfile])
def test_enum_values_match_the_doc(enum: type[StrEnum]) -> None:
    assert documented_values(enum.__name__) == [item.value for item in enum]
