"""Test helpers: short runs on the built-in example house and the synthetic cold week."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from ovenbird.history.journal import CommandRow, DecisionRow
from ovenbird_harness.fullrun import FullRun, RunConfig, RunResult
from ovenbird_harness.settings import Profile

REFERENCE_START: Final = datetime(2025, 11, 10, 6, tzinfo=UTC)


def reference_config(out: Path, hours: float, **overrides: Any) -> RunConfig:
    """Return a run on the example house and the cold week, without local data.

    Parameters
    ----------
    out
        Output directory.
    hours
        Simulated hours from :data:`REFERENCE_START`.
    **overrides
        Further :class:`~ovenbird_harness.fullrun.RunConfig` fields.
    """
    values: dict[str, Any] = {
        "start": REFERENCE_START,
        "end": REFERENCE_START + timedelta(hours=hours),
        "out": out,
        "params": None,
        "weather_dir": None,
        "datalake": None,
        "profile": Profile(),
    }
    values.update(overrides)
    return RunConfig(**values)


@dataclass
class RecordedRun:
    """A finished run with every decision and command event it journalled.

    Parameters
    ----------
    run
        The run.
    result
        Its result.
    decisions, commands
        Journal rows in order.
    """

    run: FullRun
    result: RunResult
    decisions: list[DecisionRow] = field(default_factory=list)
    commands: list[CommandRow] = field(default_factory=list)


def recorded_run(config: RunConfig) -> RecordedRun:
    """Run ``config`` and keep its journal rows."""
    run = FullRun(config)
    decisions: list[DecisionRow] = []
    commands: list[CommandRow] = []
    run.on_decision.append(decisions.append)
    run.on_command.append(commands.append)
    result = run.run()
    return RecordedRun(run, result, decisions, commands)
