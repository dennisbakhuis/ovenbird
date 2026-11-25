"""The preview's identity check on a simulated run: replaying 24 h with the active config.

The run includes an operator configuration apply (and its revert) and a service
restart, so the replay must re-seed at the version changes and follow the restart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ovenbird.config import Settings
from ovenbird.configstore import ConfigManager
from ovenbird.configstore.preview import run_open_loop
from ovenbird_harness.testing import recorded_run, reference_config

pytestmark = pytest.mark.slow

HOURS = 26.0


def test_replaying_a_simulated_day_reproduces_every_setpoint(tmp_path: Path) -> None:
    config = reference_config(tmp_path, HOURS, faults=("config_apply", "ovenbird_restart"))
    recorded = recorded_run(config)
    assert recorded.result.passed, recorded.result.summary["faults"]
    run = recorded.run
    manager = ConfigManager.open(run.settings, run.clock, locked={})
    try:
        settings: Settings = manager.settings
        end = run.end_ts
        start = end - 24 * 3600.0
        result = run_open_loop(
            settings.history_path,
            settings,
            manager.version,
            settings,
            manager.config_of,
            (start, end),
        )
        versions = {row.config_version for row in recorded.decisions if row.ts >= start}
        assert len(versions) >= 2
        assert result["ticks"] >= 24 * 60 - 10
        assert result["skipped"] == 0
        assert result["identity_ticks"] > 600
        assert result["identity_ok"] is True, result["identity_first_mismatch"]
    finally:
        manager.close()
