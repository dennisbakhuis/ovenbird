from __future__ import annotations

from pathlib import Path

import pytest

from climate_manager_capture.capture import CaptureReader, Record
from climate_manager_capture.synthetic import build_records, write_capture
from climate_manager_capture.testing import FakeClock


@pytest.fixture(scope="session")
def synthetic_records() -> list[Record]:
    return build_records()


@pytest.fixture(scope="session")
def synthetic_capture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_capture(tmp_path_factory.mktemp("captures"), "synthetic")


@pytest.fixture
def synthetic_reader(synthetic_capture: Path) -> CaptureReader:
    return CaptureReader(synthetic_capture)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()
