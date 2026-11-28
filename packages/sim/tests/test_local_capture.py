import os
from pathlib import Path

import numpy as np
import pytest

from ovenbird_sim.data.capture import load_capture
from ovenbird_sim.data.dataset import assemble, load_datalake
from ovenbird_sim.data.weather import load_weather

CAPTURES = Path(
    os.environ.get("CAPTURES_DIR") or Path(__file__).resolve().parents[3] / "capture" / "captures"
)
LIVE = CAPTURES / "live"

pytestmark = pytest.mark.skipif(
    not any(LIVE.glob("*.jsonl*")), reason="local capture not present (data is never committed)"
)


def test_local_capture_aligns_and_has_sane_physics() -> None:
    """The local capture aligns with the datalake and weather and has plausible physics."""
    capture = load_capture(LIVE)
    start = float(capture["liveness"].t[-1]) - 3 * 86400.0
    ds = assemble(
        capture,
        datalake=load_datalake(CAPTURES / "datalake"),
        weather=load_weather(CAPTURES / "weather"),
        step=60.0,
        start=start,
        end=start + 2 * 86400.0,
    )
    c = ds.columns
    assert ds.grid.n == 2 * 1440 + 1 or ds.grid.n == 2 * 1440
    assert np.isfinite(c["outlet"]).mean() > 0.95
    assert 0.0 <= ds.calibration.offset_k <= 0.75
    running = ds.flags["compressor_on"]
    assert np.nanmean(c["heat_w"][running]) > 1000.0
    assert np.all(np.nan_to_num(c["heat_w"][c["compressor_frac"] == 0.0]) == 0.0)
    assert ds.flags["gap"].mean() < 0.05
