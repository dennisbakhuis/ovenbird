import math

import pytest

from ovenbird_core.control.forecast import HISTORY_S, HOUR_S, ForecastHour

DAY0 = 1_767_225_600.0


def test_forecast_hour_accepts_whole_hours_and_missing_values() -> None:
    """A forecast hour on a whole hour may lack outside and irradiance values."""
    row = ForecastHour(DAY0 + HOUR_S, None, None)
    assert row.outside_c is None
    assert row.ghi_w_m2 is None
    assert HISTORY_S == 24 * HOUR_S


def test_forecast_hour_rejects_bad_values() -> None:
    """Off-hour timestamps, negative irradiance and non-finite values raise ValueError."""
    with pytest.raises(ValueError, match="whole hours"):
        ForecastHour(DAY0 + 60.0, 3.0, 0.0)
    with pytest.raises(ValueError, match="non-negative"):
        ForecastHour(DAY0, 3.0, -1.0)
    with pytest.raises(ValueError, match="finite"):
        ForecastHour(DAY0, math.nan, 0.0)
    with pytest.raises(ValueError, match="finite"):
        ForecastHour(math.inf, 3.0, 0.0)
