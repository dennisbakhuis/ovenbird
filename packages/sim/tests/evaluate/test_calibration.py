"""Proposals of ovenbird's target calibration."""

import pytest

from ovenbird_sim.evaluate.counterfactual import CHECK_FIRST_POINTS, ComfortMeasure, _proposals

ROWS = [
    (21.6, -0.4, -0.5, 1.0, 10.0),
    (21.9, -0.1, -0.1, 0.2, 4.0),
    (22.2, 0.2, 0.15, -0.05, 4.0),
]


def test_mean_and_tail_take_a_secant_step_on_their_measure() -> None:
    assert _proposals(ROWS, ComfortMeasure.MEAN, first=True) == [pytest.approx(22.0)]
    tail = _proposals(ROWS, ComfortMeasure.TAIL, first=True)[0]
    assert tail == pytest.approx(21.9 + 0.3 * 0.2 / 0.25)


def test_check_spans_the_mean_and_tail_targets_then_halves_around_the_best() -> None:
    first = _proposals(ROWS, ComfortMeasure.CHECK, first=True)
    assert len(first) == CHECK_FIRST_POINTS
    assert first[0] == pytest.approx(22.0)
    assert first[-1] == pytest.approx(22.14)
    later = _proposals(ROWS, ComfortMeasure.CHECK, first=False)
    assert later == [pytest.approx(21.75), pytest.approx(22.05)]
