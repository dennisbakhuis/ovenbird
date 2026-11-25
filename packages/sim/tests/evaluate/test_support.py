"""Joint support of the COP map."""

import numpy as np
import pytest

from ovenbird_sim.evaluate.support import MIN_MINUTES, CopSupport


def test_unsupported_share_weights_heat_in_thin_cells() -> None:
    minutes = np.zeros((2, 2, 2))
    minutes[0, 0, 0] = MIN_MINUTES
    minutes[1, 1, 1] = MIN_MINUTES - 1.0
    support = CopSupport((0.0, 30.0, 20.0), (2.0, 2.0, 5.0), minutes)
    outside = np.array([1.0, 3.0, 9.0, 1.0])
    outlet = np.array([31.0, 33.0, 31.0, 31.0])
    hz = np.array([22.0, 27.0, 22.0, 0.0])
    heat = np.array([3000.0, 1000.0, 1000.0, 5000.0])
    expected = [MIN_MINUTES, MIN_MINUTES - 1.0, 0.0, 0.0]
    assert support.cell_minutes(outside, outlet, hz).tolist() == expected
    assert support.unsupported_share(outside, outlet, hz, heat) == pytest.approx(0.4)


def test_no_heating_means_nothing_unsupported() -> None:
    support = CopSupport((0.0, 30.0, 20.0), (2.0, 2.0, 5.0), np.zeros((1, 1, 1)))
    zeros = np.zeros(3)
    assert support.unsupported_share(zeros, zeros + 30.0, zeros, zeros) == 0.0
