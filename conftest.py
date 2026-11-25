"""Shared test fixture: the two-hour capture slices the replay tests run on.

``synthetic`` is committed (``packages/core/tests/fixtures/synthetic``, written by
``python -m ovenbird_sim.heishamon.fixture``). ``recorded`` is a slice of the live
recording kept with the local captures (``$CAPTURES_DIR``, default
``capture/captures``, under ``fixtures/live``); recorded data is never committed, so
its variants are skipped where the captures are absent, as in CI.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parent
SYNTHETIC: Final = ROOT / "packages/core/tests/fixtures/synthetic/2026-01-06.jsonl.gz"
RECORDED: Final = Path("fixtures") / "live"


def captures_dir() -> Path:
    """Return the local captures directory (``$CAPTURES_DIR`` or ``capture/captures``)."""
    configured = os.environ.get("CAPTURES_DIR")
    return Path(configured) if configured else ROOT / "capture" / "captures"


def recorded_slice() -> Path:
    """Return the recorded slice: the one day file under ``fixtures/live`` of the captures."""
    folder = captures_dir() / RECORDED
    files = sorted(folder.glob("*.jsonl.gz")) if folder.is_dir() else []
    return files[0] if files else folder / "absent.jsonl.gz"


@pytest.fixture(scope="session", params=("synthetic", "recorded"))
def capture_slice(request: pytest.FixtureRequest) -> Path:
    """Each capture slice in turn; the recorded one is skipped when not present locally."""
    path = SYNTHETIC if request.param == "synthetic" else recorded_slice()
    if not path.is_file():
        pytest.skip(f"recorded slice not present at {path} (local data, never committed)")
    return path
