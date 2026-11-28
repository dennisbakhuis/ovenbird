"""The sun day shift evaluation: weather, local time, pairing, the gate and its quick run."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from ovenbird_core.instant import Instant
from ovenbird_sim.evaluate import dayshift as ds
from ovenbird_sim.evaluate import dayshift_gate as gate
from ovenbird_sim.evaluate import dayshift_run as run
from ovenbird_sim.evaluate.dayshift import Arm, Replica
from ovenbird_sim.evaluate.plangate import Outcome

DEFAULT = Arm(ds.RULE, ds.DEFAULT_SETTING)


@pytest.fixture(scope="module")
def quick() -> run.Evaluation:
    """Return the quick evaluation (two scenarios, two short replicas)."""
    return run.evaluate(run.Options.quick(workers=None))


def _rows(n: int, **values: float) -> list[dict[str, float]]:
    """Return ``n`` identical KPI rows with some values set."""
    row = dict.fromkeys(ds.KPIS, 0.0)
    row.update(starts=10.0, elec_kwh=30.0, cop=5.0, below_occ_kh=2.0, night_run_h=40.0)
    row.update(values)
    return [dict(row) for _ in range(n)]


def _shifted(rows: list[dict[str, float]], **deltas: float) -> list[dict[str, float]]:
    """Return ``rows`` with constant deltas added."""
    return [{**r, **{k: r[k] + d for k, d in deltas.items()}} for r in rows]


def _verdict(arm: Arm, deltas: Mapping[str, Mapping[str, float]], n: int = 16) -> gate.Verdict:
    """Return the verdict of an arm whose differences per scenario are ``deltas``."""
    base = _rows(n)
    return gate.verdict(arm, {s: (base, _shifted(base, **deltas.get(s, {}))) for s in ds.SCENARIOS})


class TestWeather:
    """Weather generation of a replica."""

    def test_a_replica_is_seeded_and_shared_by_the_scenarios(self) -> None:
        """The same replica gives the same weather; scenarios share the sun's timing."""
        mild = ds.SCENARIOS["sunny_mild"]
        a = ds.build_case(mild, Replica(0, 3), 2)
        b = ds.build_case(mild, Replica(0, 3), 2)
        assert np.array_equal(a.weather.outside_c, b.weather.outside_c)
        assert np.array_equal(a.weather.ghi_w_m2, b.weather.ghi_w_m2)
        other = ds.build_case(mild, Replica(0, 4), 2)
        assert not np.array_equal(a.weather.outside_c, other.weather.outside_c)
        house = ds.build_case(ds.SCENARIOS["large_windows"], Replica(0, 3), 2)
        assert np.array_equal(a.weather.ghi_w_m2, house.weather.ghi_w_m2)

    def test_the_must_idle_scenarios_stay_below_their_limits(self) -> None:
        """Sunny cold never reaches 5 °C and cloudy days never get real sun."""
        for index in range(ds.DEFAULT_REPLICAS + 8):
            cold = ds.build_case(ds.SCENARIOS["sunny_cold"], Replica(0, index), ds.DAYS)
            assert cold.weather.outside_c.max() < 5.0
            cloudy = ds.build_case(ds.SCENARIOS["cloudy_mild"], Replica(0, index), ds.DAYS)
            assert cloudy.weather.ghi_w_m2.max() <= ds.OVERCAST_PEAK * ds.OVERCAST_RANGE[1]

    def test_a_wrong_forecast_differs_from_the_truth(self) -> None:
        """Sun forecast but not delivered: the stored rows announce more sun than arrives."""
        case = ds.build_case(ds.SCENARIOS["sun_missing"], Replica(0, 0), 2)
        now = ds.START.timestamp() + 8 * 3600.0
        rows = case.forecast.rows(Instant.from_unix(now))
        ahead = [r.ghi_w_m2 or 0.0 for r in rows if now + 3600.0 < r.target_ts <= now + 8 * 3600]
        assert np.mean(ahead) > 3.0 * case.weather.ghi_w_m2.max()

    def test_the_cold_snap_is_not_in_the_forecast(self) -> None:
        """The snap lowers the truth by its full size; the forecast keeps the mild night."""
        snap = ds.build_case(ds.SCENARIOS["cold_snap"], Replica(0, 0), 3)
        mild = ds.build_case(ds.SCENARIOS["sunny_mild"], Replica(0, 0), 3)
        drop = mild.weather.outside_c - snap.weather.outside_c
        assert drop.max() == pytest.approx(ds.SNAP_K)
        assert np.array_equal(snap.forecast.outside_c, mild.forecast.outside_c)


class TestLocalTime:
    """Local time handling of the run clock."""

    def test_local_hours_start_at_local_midnight(self) -> None:
        """The run starts at local midnight in the evaluation zone, not at UTC midnight."""
        hours = ds.local_hours(ds.T0, 1440, 60.0)
        assert hours[0] == 0.0
        assert hours[60] == 1.0
        assert ds.START.utcoffset() == timedelta(hours=1)

    def test_local_hours_follow_the_summer_time_change(self) -> None:
        """At the spring change the local clock jumps from 02:00 to 03:00."""
        zone = ZoneInfo(ds.ZONE)
        t0 = datetime(2026, 3, 29, tzinfo=zone).timestamp()
        hours = ds.local_hours(t0, 6 * 60, 60.0)
        assert hours[119] == pytest.approx(1.0 + 59 / 60)
        assert hours[120] == 3.0

    def test_the_rule_boosts_in_the_local_day_window(self, quick: run.Evaluation) -> None:
        """The applied offset is positive only from 09:00 (its ramp to 17:15) local time."""
        by_hour = quick.by_hour("sunny_mild", DEFAULT)
        assert all(by_hour[h] <= 0.0 for h in range(9))
        assert by_hour[9] > 0.0
        assert all(by_hour[h] <= 0.0 for h in range(18, 24))


class TestQuickRun:
    """A quick evaluation run through the gate."""

    def test_the_do_nothing_rule_changes_nothing(self, quick: run.Evaluation) -> None:
        """A provider that never plans leaves every run identical to its baseline."""
        none = quick.verdicts["none"]
        assert none.passed
        for cell in none.cells:
            assert all(iv.estimate == 0.0 for iv in cell.diffs.values() if iv.n)

    def test_a_constant_setback_fails_on_comfort(self, quick: run.Evaluation) -> None:
        """A -1 K offset day and night fails a comfort criterion in every scenario."""
        const = quick.verdicts["const_setback"]
        assert const.comfort_failed()
        assert all(cell.check("below_occupied").outcome is Outcome.FAILED for cell in const.cells)

    def test_the_rule_acts_on_sun_and_idles_on_clouds(self, quick: run.Evaluation) -> None:
        """The default rule boosts on sunny mild days and does nothing on cloudy ones."""
        sunny, cloudy = (quick.rows(s, DEFAULT)[1] for s in ("sunny_mild", "cloudy_mild"))
        assert all(r["boost_h"] > 0.0 for r in sunny)
        assert quick.verdicts[DEFAULT.label].cell("cloudy_mild").idle is True
        assert all(r["boost_h"] == r["setback_h"] == 0.0 for r in cloudy)

    def test_a_smoke_run_never_unlocks(self, quick: run.Evaluation, tmp_path: Path) -> None:
        """The quick run writes its outputs but can never unlock ``on``."""
        recommendation = run.recommend(quick)
        assert not recommendation.unlock
        assert any("smoke run" in line for line in recommendation.reasons)
        document, tables = run.write_outputs(tmp_path, quick, recommendation)
        assert document.exists()
        text = tables.read_text()
        assert "## Calibration" in text
        assert "sunny_mild" in text


class TestGate:
    """Gate decisions on constructed verdicts."""

    @pytest.mark.parametrize(
        ("kpi", "delta", "expected"),
        [
            ("below_occ_kh", 0.9, Outcome.PASSED),
            ("below_occ_kh", 1.1, Outcome.FAILED),
            ("below_morning_kh", 0.6, Outcome.FAILED),
            ("below_band_morning_kh", 0.3, Outcome.FAILED),
            ("above_kh", 1.2, Outcome.FAILED),
            ("starts", 3.0, Outcome.PASSED),
            ("starts", 4.0, Outcome.FAILED),
        ],
    )
    def test_margins_on_constant_differences(
        self, kpi: str, delta: float, expected: Outcome
    ) -> None:
        """A constant rise passes within its margin and fails beyond it."""
        verdict = _verdict(DEFAULT, {"sunny_mild": {kpi: delta}})
        criterion = next(c for c in gate.CRITERIA if c.kpi == kpi)
        assert verdict.cell("sunny_mild").check(criterion.name).outcome is expected

    def test_a_noisy_difference_near_the_margin_is_inconclusive(self) -> None:
        """An interval straddling the margin blocks without failing."""
        base = _rows(16)
        rng = np.random.default_rng(1)
        noisy = [{**r, "below_occ_kh": r["below_occ_kh"] + 1.0 + rng.normal(0, 1)} for r in base]
        cell = gate.judge("sunny_mild", DEFAULT, base, noisy)
        assert cell.check("below_occupied").outcome is Outcome.INCONCLUSIVE
        assert cell.outcome is Outcome.INCONCLUSIVE

    def test_activity_in_a_must_idle_scenario_fails(self) -> None:
        """Any offset applied on a cloudy day fails the rule, whatever the comfort says."""
        verdict = _verdict(DEFAULT, {"cloudy_mild": {"boost_h": 0.25}})
        cell = verdict.cell("cloudy_mild")
        assert cell.idle is False
        assert cell.outcome is Outcome.FAILED
        assert "idle" in cell.named(Outcome.FAILED)
        assert (
            _verdict(Arm(ds.CONST), {"cloudy_mild": {"boost_h": 1.0}}).cell("cloudy_mild").idle
            is None
        )

    def test_the_benefit_is_the_night_run_time(self) -> None:
        """Less night running shows as a negative interval and a positive shift."""
        verdict = _verdict(DEFAULT, {"sunny_mild": {"night_run_h": -2.0, "night_elec_kwh": -0.5}})
        found = gate.benefit(verdict.cell(gate.INTENDED))
        assert found.less_night_running
        assert found.shifted_kwh == pytest.approx(0.5)


def _evaluation(verdicts: list[gate.Verdict], sweep: tuple[ds.Params, ...]) -> run.Evaluation:
    """Return a full-looking evaluation made of given verdicts."""
    options = run.Options(sweep=sweep, replicas=16)
    return run.Evaluation(options, {}, {v.arm.label: v for v in verdicts}, 0.0)


def _calibration() -> list[gate.Verdict]:
    """Return calibration verdicts as a calibrated gate gives them."""
    return [
        _verdict(Arm(ds.NONE), {}),
        _verdict(Arm(ds.NOISE), {}),
        _verdict(Arm(ds.CONST), {s: {"below_occ_kh": 20.0} for s in ds.SCENARIOS}),
    ]


class TestRecommend:
    """The recommendation derived from gate verdicts."""

    def test_passing_defaults_are_kept_and_unlock(self) -> None:
        """Defaults that pass a calibrated, complete gate stay and unlock ``on``."""
        found = run.recommend(_evaluation([*_calibration(), _verdict(DEFAULT, {})], ds.SWEEP[:1]))
        assert found.unlock
        assert not found.changed

    def test_failing_defaults_give_way_to_a_passing_setting(self) -> None:
        """Another setting with both halves that passes everywhere becomes the default."""
        other = Arm(ds.RULE, ds.params_of({"boost_k": 1.0, "setback_k": 0.5, "recovery_h": 5.0}))
        bad = _verdict(DEFAULT, {"sunny_mild": {"below_morning_kh": 2.0}})
        good = _verdict(other, {"sunny_mild": {"night_run_h": -3.0}})
        found = run.recommend(
            _evaluation([*_calibration(), bad, good], (DEFAULT.params, other.params))
        )
        assert found.setting == other.params
        assert found.changed
        assert found.unlock

    def test_a_failing_setback_half_ships_at_zero(self) -> None:
        """Boost alone passes, set-back alone fails: the set-back defaults to 0."""
        boost = Arm(ds.RULE, ds.params_of({"boost_k": 0.5, "setback_k": 0.0, "recovery_h": 4.0}))
        back = Arm(ds.RULE, ds.params_of({"boost_k": 0.0, "setback_k": 0.5, "recovery_h": 4.0}))
        morning = {"sunny_mild": {"below_morning_kh": 2.0}}
        verdicts = [
            *_calibration(),
            _verdict(DEFAULT, morning),
            _verdict(boost, {}),
            _verdict(back, morning),
        ]
        found = run.recommend(_evaluation(verdicts, (DEFAULT.params, boost.params, back.params)))
        assert found.setting == boost.params
        assert found.unlock
        assert any("set-back at 0" in line for line in found.reasons)

    def test_nothing_unlocks_without_a_calibrated_gate(self) -> None:
        """A constant set-back that passes means the gate cannot see harm: no unlock."""
        verdicts = [_verdict(Arm(ds.NONE), {}), _verdict(Arm(ds.CONST), {}), _verdict(DEFAULT, {})]
        found = run.recommend(_evaluation(verdicts, ds.SWEEP[:1]))
        assert not found.unlock


@pytest.mark.slow
def test_the_full_gate_is_calibrated_and_keeps_the_defaults_locked() -> None:
    """At the gate's minimum size the calibration holds and the defaults do not pass.

    Every scenario, :data:`~ovenbird_sim.evaluate.dayshift_run.MIN_GATE_REPLICAS`
    replicas of the full length, the calibration arms and the default setting: the
    full sweep (``python -m ovenbird_sim.evaluate dayshift``) takes half an hour and is
    reported in ``docs/evaluation/dayshift.md``.
    """
    options = run.Options(sweep=(ds.DEFAULT_SETTING,), replicas=run.MIN_GATE_REPLICAS)
    assert options.complete
    evaluation = run.evaluate(options)
    assert gate.calibrated(evaluation.verdicts)
    assert not evaluation.verdicts[DEFAULT.label].passed
    assert not run.recommend(evaluation).unlock
