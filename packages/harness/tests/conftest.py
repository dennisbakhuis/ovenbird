from __future__ import annotations

import pytest

from ovenbird_harness.testing import RecordedRun, recorded_run, reference_config


@pytest.fixture(scope="session")
def short_run(tmp_path_factory: pytest.TempPathFactory) -> RecordedRun:
    return recorded_run(reference_config(tmp_path_factory.mktemp("short"), 12.0))
