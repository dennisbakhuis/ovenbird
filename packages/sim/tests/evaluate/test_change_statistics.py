"""Event-aware statistics of the recorded room sensor states."""

import numpy as np
import pytest

from ovenbird_sim.data.series import Series
from ovenbird_sim.evaluate.sensors import changes_per_day, reversal_share

T0 = 1_793_232_000.0


def test_change_statistics_skip_excluded_periods() -> None:
    t = T0 + 3600.0 * np.arange(49, dtype=np.float64)
    v = np.where(np.arange(49) % 2 == 0, 21.5, 21.7).astype(np.float64)
    v[24:] = 21.5 + 0.2 * np.minimum(np.arange(25), 3)
    states = Series(t, v)
    whole = changes_per_day(states)
    first_day = changes_per_day(states, ((T0 + 86400.0, T0 + 2 * 86400.0 + 1.0),))
    assert whole == pytest.approx(26.5 / 2, abs=0.6)
    assert first_day == pytest.approx(23.0, abs=0.1)
    assert reversal_share(states, ((T0 + 86400.0, T0 + 2 * 86400.0 + 1.0),)) == 1.0
