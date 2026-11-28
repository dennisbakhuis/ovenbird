from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from ovenbird_harness.compare import compare
from ovenbird_harness.testing import REFERENCE_START
from ovenbird_harness.validate import mqtt_config

pytestmark = pytest.mark.slow

LONG_ENV = "OVENBIRD_HARNESS_LONG"


def check(tmp_path: Path, hours: float) -> dict[str, Any]:
    """Run the comparison over ``hours`` and assert that every KPI but coverage passes."""
    config = mqtt_config(REFERENCE_START, None, None, tmp_path)
    verdict = compare(config, hours, 600.0)
    failed = {
        name: item
        for name, item in verdict["kpis"].items()
        if not item["passed"] and name != "coverage"
    }
    assert not failed, failed
    assert verdict["b1"]["decisions"] == int(hours * 60)
    assert all(real["decisions"] > 0.9 * hours * 60 for real in verdict["real"])
    return verdict


def test_b1_kpis_match_the_real_service_over_six_hours(tmp_path: Path) -> None:
    """A six-hour window passes every KPI except coverage, so the overall verdict fails."""
    verdict = check(tmp_path, 6.0)
    assert not verdict["kpis"]["coverage"]["passed"]
    assert not verdict["passed"]


@pytest.mark.skipif(os.environ.get(LONG_ENV) != "1", reason=f"long variant: set {LONG_ENV}=1")
def test_b1_kpis_match_the_real_service_over_two_days(tmp_path: Path) -> None:
    """A 48-hour window (long variant) passes every KPI, coverage included."""
    assert check(tmp_path, 48.0)["passed"]
