"""The learner's checks: excitation, skill, credibility, parameters at a limit, promotion."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import numpy as np
import pytest

from ovenbird_sim.data import events as ev
from ovenbird_sim.data.dataset import FLAGS, Dataset, OffsetCalibration
from ovenbird_sim.data.grid import TimeGrid
from ovenbird_sim.identify import io
from ovenbird_sim.identify.building import BOUNDS, DEFAULT_PRIORS
from ovenbird_sim.identify.validate import HorizonErrors
from ovenbird_sim.insight.signature import Signature
from ovenbird_sim.learn import checks, run
from ovenbird_sim.learn.priors import build_priors, house_settings, unconstrained
from ovenbird_sim.learn.sun import SunCheck
from ovenbird_sim.model.building import BuildingParams
from ovenbird_sim.model.heatpump import HeatPumpParams
from ovenbird_sim.model.plant import PlantParams

START = 1_789_948_800.0
STEP = 600.0
PER_DAY = round(86400.0 / STEP)


def days_dataset(
    outside: Sequence[float],
    share: Sequence[float],
    *,
    room: float = 21.0,
    events: tuple[ev.Event, ...] = (),
    room_wave_k: float = 0.0,
) -> Dataset:
    """A dataset of whole UTC days with a constant outside temperature and run share per day."""
    n = len(outside) * PER_DAY
    grid = TimeGrid(START, STEP, n)
    t = grid.edges
    day = np.repeat(np.arange(len(outside)), PER_DAY)
    hour = (t % 86400.0) / 3600.0
    running = np.repeat(np.asarray(share, dtype=np.float64), PER_DAY)
    indoor = room + room_wave_k * np.sin(2.0 * np.pi * hour / 24.0)
    columns = {
        "room": indoor,
        "outside": np.asarray(outside, dtype=np.float64)[day],
        "heat_w": 4000.0 * running,
        "compressor_frac": running,
        "local_hour": hour,
        "inlet": np.full(n, 28.0),
        "outlet": np.full(n, 32.0),
    }
    flags = {name: np.zeros(n, dtype=np.bool_) for name in FLAGS}
    flags["event"] = ev.mask(grid.mids, events)
    calibration = OffsetCalibration(0.0, 0.0, 0.0, 0, 0.0)
    return Dataset(grid, columns, flags, calibration, {}, events)


def spread(days: int, low: float, high: float) -> list[float]:
    return list(np.linspace(low, high, days))


def test_a_cold_varied_window_with_a_running_pump_is_excited() -> None:
    ds = days_dataset(spread(30, 0.0, 14.0), [0.5] * 30)
    out = checks.excitation(ds, 300.0, (280.0, 320.0))
    assert out["excited"] is True
    assert out["heating_days"] >= 25
    assert out["outside_range_k"] >= 10.0
    assert out["ua_relative_width"] == pytest.approx(40.0 / 300.0, abs=1e-3)
    assert out["needed"] == {"heating_days": 0, "outside_range_k": 0.0}
    assert out["reasons"] == []
    assert out["heat_kwh_per_day"] == pytest.approx(48.0, rel=0.05)
    assert out["rules"]["heating_days"] == checks.EXCITED_DAYS


def test_mild_weather_is_not_excited() -> None:
    ds = days_dataset([18.0] * 30, [0.5] * 30)
    out = checks.excitation(ds, 300.0, (280.0, 320.0))
    assert out["excited"] is False
    assert out["heating_days"] == 0
    assert out["needed"]["heating_days"] == checks.EXCITED_DAYS
    assert out["needed"]["outside_range_k"] == checks.EXCITED_RANGE_K
    assert any("heating days" in reason for reason in out["reasons"])


def test_an_idle_heat_pump_is_not_excited() -> None:
    ds = days_dataset(spread(30, 0.0, 14.0), [0.1] * 30)
    out = checks.excitation(ds, 300.0, (280.0, 320.0))
    assert out["excited"] is False
    assert out["delta_t_days"] >= 25
    assert out["run_share_days"] == 0
    assert out["heating_days"] == 0


def test_a_narrow_outside_range_is_not_excited() -> None:
    ds = days_dataset(spread(30, 2.0, 8.0), [0.5] * 30)
    out = checks.excitation(ds, 300.0, (280.0, 320.0))
    assert out["excited"] is False
    assert out["needed"]["heating_days"] == 0
    assert 3.5 < out["needed"]["outside_range_k"] < 5.0


def test_a_wide_ua_interval_is_not_excited() -> None:
    ds = days_dataset(spread(30, 0.0, 14.0), [0.5] * 30)
    wide = checks.excitation(ds, 300.0, (200.0, 400.0))
    assert wide["excited"] is False
    assert wide["ua_tight"] is False
    assert any("interval" in reason for reason in wide["reasons"])
    none = checks.excitation(ds, 300.0, None)
    assert none["excited"] is False
    assert none["ua_relative_width"] is None


def test_event_days_do_not_count() -> None:
    fire = ev.Event(ev.STOVE_MODE, START + 86400.0, START + 2 * 86400.0, START + 3 * 86400.0, 0, 0)
    plain = checks.excitation(days_dataset([0.0] * 10, [0.5] * 10), 300.0, (290.0, 310.0))
    masked = checks.excitation(
        days_dataset([0.0] * 10, [0.5] * 10, events=(fire,)), 300.0, (290.0, 310.0)
    )
    assert masked["days"] == plain["days"] - 2


def horizon(room: Sequence[float], persistence: Sequence[float]) -> HorizonErrors:
    hours = checks.SKILL_HORIZONS_H
    return HorizonErrors(hours, tuple(room), tuple(room), tuple(persistence), 40)


def test_skill_is_against_persistence_on_the_same_origins() -> None:
    errors = horizon([0.1, 0.12, 0.15, 0.2, 0.3], [0.1, 0.15, 0.2, 0.2, 0.25])
    assert checks.skill_at(errors, 6.0) == pytest.approx(0.25)
    assert checks.skill_at(errors, 12.0) == pytest.approx(0.0)
    assert checks.skill_at(errors, 24.0) == pytest.approx(-0.2)
    assert math.isnan(checks.skill_at(errors, 2.0))
    flat = horizon([0.1] * 5, [0.0] * 5)
    assert math.isnan(checks.skill_at(flat, 6.0))
    body = checks.skill_json(errors, (0.3, 0.3, 0.3, 0.3, 0.3))
    assert body["horizons_h"] == list(checks.SKILL_HORIZONS_H)
    assert body["skill"][2] == 0.25
    assert body["skill_diurnal"][4] == 0.0


def test_diurnal_persistence_repeats_yesterday() -> None:
    ds = days_dataset([5.0] * 6, [0.5] * 6, room_wave_k=1.0)
    start, end = START + 2 * 86400.0, START + 5 * 86400.0
    diurnal = checks.diurnal_persistence(ds, start, end)
    assert all(value < 1e-9 for value in diurnal)
    assert len(diurnal) == len(checks.SKILL_HORIZONS_H)
    early = checks.diurnal_persistence(ds, START, START + 2 * 86400.0)
    assert math.isnan(early[0])
    assert early[-1] < 1e-9


def signature(*, heating: int = 40, span: float = 14.0, h: float = 300.0) -> Signature:
    reasons = []
    if heating < 30:
        reasons.append(f"{heating} heating days < 30")
    return Signature(
        indoor="house_mean",
        days=heating + 5,
        heating_days=heating,
        cold_days=4,
        outside_span_k=span,
        h_w_per_k=h,
        h_interval=(h - 20.0, h + 20.0),
        solar_m2=5.0,
        solar_interval=(4.0, 6.0),
        gains_w=100.0,
        storage_j_per_k=0.0,
        balance_c=17.0,
        balance_interval=(16.0, 18.0),
        time_constant_h=math.nan,
        rmse_w=100.0,
        credible=not reasons,
        reasons=tuple(reasons),
    )


EXCITED = {
    "excited": True,
    "needed": {"heating_days": 0, "outside_range_k": 0.0},
    "reasons": [],
}


SUNNY = SunCheck(
    days=14, sunny_days=8, ablation_skill=0.3, beta=1.1, beta_interval=(0.9, 1.3), origins=14
)
STABLE = (300.0, 320.0)


def credibility(**changes: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "sig": signature(),
        "sig_days": 45,
        "excited": EXCITED,
        "ua_w_per_k": 310.0,
        "skill": 0.12,
        "skill_24h": -0.2,
        "reported_ua": (290.0, 330.0),
        "fold_uas": STABLE,
        "sun": SUNNY,
    }
    args |= changes
    return checks.model_credibility(
        args.pop("sig"),
        args.pop("sig_days"),
        args.pop("excited"),
        args.pop("ua_w_per_k"),
        args.pop("skill"),
        **args,
    )


def test_every_gate_passes_and_credible_is_the_heat_loss_gate() -> None:
    good = credibility()
    gates = good["gates"]
    assert [gates[g]["ok"] for g in checks.GATES] == [True, True, True]
    assert good["credible"] is True
    assert all(good["checks"].values())
    assert good["message"] is None
    assert good["cold_days"] == 4
    assert "cold_days" not in good["rules"]
    assert gates["heat_loss"]["uses"] == list(checks.HEAT_LOSS_USES)
    assert gates["dynamics"]["uses"] == ["whatif_cool_down", "room_target_planner"]
    assert gates["sun"]["uses"] == ["water_planner"]
    assert gates["heat_loss"]["checks"]["ua_stability"]["value"] == pytest.approx(0.032, abs=1e-3)
    assert gates["heat_loss"]["checks"]["ua_stability"]["folds"] == 2
    assert gates["sun"]["checks"]["sun_response"]["interval"] == [0.9, 1.3]
    assert gates["sun"]["checks"]["sun_response"]["limit"] == [0.67, 1.5]
    for gate in gates.values():
        assert gate["needed"] == []
        assert gate["message"] is None
        assert set(gate["needed"]) <= checks.NEEDS


def test_the_heat_loss_gate_has_no_room_skill_term() -> None:
    blind = credibility(skill=-0.05)
    assert blind["credible"] is True
    assert blind["checks"]["predictive"] is False
    assert blind["gates"]["dynamics"]["ok"] is False
    assert blind["gates"]["dynamics"]["needed"] == ["no_dynamics_skill"]
    assert "no change" in blind["gates"]["dynamics"]["message"]
    unscored = credibility(skill=math.nan)
    assert any("no scored origins" in r for r in unscored["gates"]["dynamics"]["reasons"])


def test_a_signature_that_disagrees_fails_the_heat_loss_gate() -> None:
    apart = credibility(sig=signature(h=400.0), ua_w_per_k=300.0, fold_uas=(300.0,))
    assert apart["checks"]["ua_consistent"] is False
    assert apart["credible"] is False
    assert "ua_disagrees" in apart["gates"]["heat_loss"]["needed"]
    assert "disagree" in apart["message"]


def test_a_ua_that_drifts_across_the_folds_fails_the_heat_loss_gate() -> None:
    drifting = credibility(
        fold_uas=(250.0, 320.0), reported_ua=checks.ua_range(310.0, (300.0, 320.0), (250.0, 320.0))
    )
    gate = drifting["gates"]["heat_loss"]
    assert gate["ok"] is False
    assert gate["checks"]["ua_stability"]["value"] == pytest.approx(60.0 / 310.0, abs=1e-3)
    assert gate["needed"] == ["ua_unstable"]
    assert "fewer weeks" in gate["message"]
    assert drifting["checks"]["ua_stable"] is False
    assert drifting["gates"]["dynamics"]["ok"] is True
    assert drifting["gates"]["sun"]["ok"] is True
    none = credibility(fold_uas=())
    assert none["gates"]["heat_loss"]["needed"] == ["ua_unstable"]


def test_the_reported_ua_range_is_the_envelope_of_bootstrap_and_folds() -> None:
    assert checks.ua_range(310.0, (300.0, 320.0), (280.0, 315.0)) == (280.0, 320.0)
    assert checks.ua_range(310.0, (300.0, 320.0), ()) == (300.0, 320.0)
    assert checks.ua_range(310.0, None, (280.0,)) is None
    wide = credibility(reported_ua=(250.0, 360.0))
    assert wide["gates"]["heat_loss"]["checks"]["ua_interval"]["ok"] is False
    assert "ua_interval_wide" in wide["gates"]["heat_loss"]["needed"]


def test_a_flat_held_room_is_judged_at_6_h_and_its_24_h_skill_only_reported() -> None:
    flat = credibility(skill=0.04, skill_24h=-0.5)
    dynamics = flat["gates"]["dynamics"]
    assert dynamics["ok"] is True
    assert dynamics["diagnostics"]["skill_24h"] == -0.5
    assert "not gated" in dynamics["diagnostics"]["note"]
    assert list(dynamics["checks"]) == ["skill_6h"]


@pytest.mark.parametrize(
    ("sun", "needed"),
    [
        (replace(SUNNY, sunny_days=3), ["more_sunny_days"]),
        (replace(SUNNY, ablation_skill=-0.1), ["no_sun_skill"]),
        (replace(SUNNY, beta=0.45, beta_interval=(0.23, 0.67)), ["sun_response_off"]),
        (replace(SUNNY, beta=1.9, beta_interval=(1.5, 2.3)), ["sun_response_off"]),
        (replace(SUNNY, beta=math.nan, beta_interval=None), ["sun_response_off"]),
        (None, ["more_sunny_days", "no_sun_skill", "sun_response_off"]),
    ],
)
def test_each_sun_check_fails_the_sun_gate(sun: SunCheck | None, needed: list[str]) -> None:
    out = credibility(sun=sun)
    gate = out["gates"]["sun"]
    assert gate["ok"] is False
    assert gate["needed"] == needed
    assert out["credible"] is True
    assert out["checks"]["sun"] is False


def test_too_few_sunny_days_ask_for_more() -> None:
    gate = credibility(sun=replace(SUNNY, sunny_days=2))["gates"]["sun"]
    assert gate["message"].startswith("3 more sunny days")
    assert gate["checks"]["sunny_days"] == {"ok": False, "value": 2, "limit": 5, "days": 14}


def test_needed_takes_the_larger_shortfall() -> None:
    thin = {
        "excited": False,
        "needed": {"heating_days": 12, "outside_range_k": 3.5},
        "reasons": ["8 heating days in the fit window < 20"],
    }
    out = checks.model_credibility(signature(heating=25, span=12.0), 30, thin, 300.0, 0.1)
    assert out["needed"] == {"heating_days": 12, "outside_span_k": 3.5}
    assert out["message"].startswith("insufficient data: 12 more heating days")
    none = checks.model_credibility(None, 3, EXCITED, 300.0, 0.1)
    assert none["checks"]["signature"] is False
    assert none["needed"]["heating_days"] == 30
    assert any("for a signature" in reason for reason in none["reasons"])


def test_parameters_at_a_limit_are_listed_by_kind() -> None:
    p = BuildingParams(
        h_water_air=5.001,
        solar_mass_fraction=0.0,
        q_int_modulation=1.0,
        h_air_out=398.0,
        q_int_w=300.0,
    )
    settings = house_settings({"house_ua_max_w_per_k": 400.0, "house_internal_gain_min_w": 300.0})
    held = {row["parameter"] for row in checks.at_bound(p, settings.priors)}
    assert held == {"h_air_out", "q_int_w"}
    rows = checks.at_bound(p, settings.priors.with_free())
    found = {row["parameter"]: row for row in rows}
    assert found["h_water_air"]["kind"] == "structural"
    assert found["h_water_air"]["side"] == "lower"
    assert found["solar_mass_fraction"]["kind"] == "structural"
    assert found["q_int_modulation"]["side"] == "upper"
    assert found["h_air_out"] == {
        "parameter": "h_air_out",
        "value": 398.0,
        "side": "upper",
        "limit": 400.0,
        "kind": "owner",
    }
    assert found["q_int_w"]["kind"] == "owner"
    assert "q_int_peak_hour" not in found
    assert "c_mass" not in found
    away = checks.at_bound(BuildingParams(h_air_out=380.0), settings.priors)
    assert "h_air_out" not in {row["parameter"] for row in away}


def test_pins_and_the_time_constant_range_are_owner_limits() -> None:
    settings = house_settings(
        {
            "house_solar_aperture_min_m2": 4.0,
            "house_solar_aperture_max_m2": 4.0,
            "house_time_constant_max_h": 40.0,
        }
    )
    p = BuildingParams(solar_aperture_m2=4.0)
    rows = {row["parameter"]: row for row in checks.at_bound(p, settings.priors)}
    assert rows["solar_aperture_m2"]["side"] == "pinned"
    assert rows["time_constant_h"]["kind"] == "owner"
    assert rows["time_constant_h"]["side"] == "upper"
    assert checks.at_bound(BuildingParams(q_int_modulation=0.3), DEFAULT_PRIORS) == []


def test_held_parameters_and_gains_at_zero_are_not_bound_problems() -> None:
    p = BuildingParams(h_water_air=5.0, solar_mass_fraction=0.0, q_int_modulation=0.0, q_int_w=0.0)
    assert checks.at_bound(p, DEFAULT_PRIORS) == []
    pinned = house_settings({"house_internal_gain_min_w": 0.0, "house_internal_gain_max_w": 0.0})
    rows = checks.at_bound(p, pinned.priors)
    assert [(r["parameter"], r["kind"]) for r in rows] == [("q_int_w", "owner")]
    high = checks.at_bound(BuildingParams(q_int_w=1990.0), DEFAULT_PRIORS)
    assert [(r["parameter"], r["side"], r["kind"]) for r in high] == [
        ("q_int_w", "upper", "structural")
    ]


def test_constraint_cost_flags_a_clearly_worse_constrained_fit() -> None:
    assert checks.constraint_cost(0.30, 0.28) == {"excess_k": 0.02, "limit_k": 0.05, "worse": False}
    assert checks.constraint_cost(0.40, 0.30)["worse"] is True
    assert checks.constraint_cost(1.10, 0.90)["worse"] is True
    assert checks.constraint_cost(1.02, 0.90)["worse"] is False
    assert checks.constraint_cost(math.nan, 0.3)["worse"] is False


def test_unconstrained_priors_release_bounds_pins_and_time_constant_but_keep_facts() -> None:
    config = {
        "house_build_period": "1975_1991",
        "house_floor_area_m2": 120.0,
        "house_volume_m3": 300.0,
        "house_ua_min_w_per_k": 250.0,
        "house_ua_max_w_per_k": 250.0,
        "house_solar_aperture_max_m2": 6.0,
        "house_time_constant_min_h": 30.0,
    }
    settings = house_settings(config)
    assert "h_air_out" in settings.priors.pinned
    free = unconstrained(settings.priors)
    assert free.pinned == {}
    assert free.time_constant_h is None
    assert (free.params["h_air_out"].lower, free.params["h_air_out"].upper) == BOUNDS["h_air_out"]
    assert free.params["solar_aperture_m2"].upper == BOUNDS["solar_aperture_m2"][1]
    assert free.params["h_air_out"].mean == settings.priors.params["h_air_out"].mean
    assert free.params["c_air"].lower == settings.priors.params["c_air"].lower
    assert free.params["c_air"].lower > BOUNDS["c_air"][0]
    plain, _ = build_priors(settings.facts, settings.bounds.__class__())
    assert unconstrained(plain) == plain


@pytest.mark.parametrize(
    ("args", "kwargs", "promoted", "says"),
    [
        ((math.nan, 0.3), {}, False, "no held-out error"),
        ((0.9, None), {"challenger_credible": False}, True, "no champion"),
        ((0.9, math.nan), {}, True, "no champion"),
        (
            (0.9, 0.3),
            {"challenger_credible": True, "champion_credible": False},
            True,
            "credible model replaces",
        ),
        (
            (0.2, 0.3),
            {"challenger_credible": False, "champion_credible": True},
            False,
            "not credible",
        ),
        (
            (0.2, 0.3),
            {"challenger_credible": False, "champion_credible": True, "settings_changed": True},
            False,
            "although the house settings changed",
        ),
        ((0.9, 0.3), {"settings_changed": True}, True, run.SETTINGS_CHANGED),
        (
            (0.9, 0.3),
            {"challenger_credible": True, "champion_credible": True, "settings_changed": True},
            True,
            run.SETTINGS_CHANGED,
        ),
        ((0.9, 0.3), {"same_house": "h_air_out 300 in [280, 320]"}, True, "same house"),
        ((0.31, 0.3), {}, False, "> champion"),
        ((0.31, 0.3), {"tolerance_k": 0.02}, True, "<= champion"),
        ((0.25, 0.3), {"tolerance_k": -0.1}, False, "> champion"),
        ((0.3, 0.3), {"challenger_credible": True, "champion_credible": True}, True, "<="),
        ((0.3, 0.3), {"challenger_credible": False, "champion_credible": False}, True, "<="),
        (
            (0.2, 0.3),
            {
                "challenger_credible": True,
                "champion_credible": True,
                "challenger_gates": {"dynamics": True, "sun": False},
                "champion_gates": {"dynamics": True, "sun": True},
            },
            False,
            "does not pass the sun gate",
        ),
        (
            (0.2, 0.3),
            {
                "settings_changed": True,
                "challenger_gates": {"dynamics": False, "sun": False},
                "champion_gates": {"dynamics": True, "sun": True},
            },
            False,
            "dynamics and sun gate the champion passes on the same days although",
        ),
        (
            (0.2, 0.3),
            {
                "challenger_gates": {"dynamics": False, "sun": False},
                "champion_gates": {"dynamics": False, "sun": False},
            },
            True,
            "<=",
        ),
        (
            (0.9, 0.3),
            {
                "challenger_credible": True,
                "champion_credible": False,
                "challenger_gates": {"dynamics": False, "sun": False},
                "champion_gates": {"dynamics": True, "sun": True},
            },
            True,
            "credible model replaces",
        ),
    ],
)
def test_every_promotion_branch(
    args: tuple[float, float | None], kwargs: dict[str, Any], promoted: bool, says: str
) -> None:
    decision, rule = run.decide_promotion(*args, **kwargs)
    assert decision is promoted
    assert says in rule


def champion(**changes: Any) -> run._Champion:
    base = run._Champion(
        name="house-20261111",
        building=BuildingParams(),
        data_to=START,
        credible=True,
        intervals={"h_air_out": (180.0, 220.0), "time_constant_h": (10.0, 100.0)},
    )
    return replace(base, **changes)


def test_the_same_house_needs_newer_data_and_both_values_inside_the_intervals() -> None:
    p = BuildingParams(h_air_out=200.0)
    tau = p.time_constant_h
    assert 10.0 < tau < 100.0
    later = START + 7 * 86400.0
    why = run.same_house(champion(), p, later)
    assert why is not None
    assert "h_air_out 200" in why
    assert run.same_house(champion(), p, START + 3600.0) is None
    assert run.same_house(champion(), BuildingParams(h_air_out=230.0), later) is None
    assert run.same_house(champion(intervals={}), p, later) is None
    assert run.same_house(champion(data_to=None), p, later) is None
    assert run.same_house(None, p, later) is None
    narrow = champion(intervals={"h_air_out": (180.0, 220.0), "time_constant_h": (1.0, 2.0)})
    assert run.same_house(narrow, p, later) is None


def test_the_champion_is_read_back_with_its_data_end_credibility_and_intervals() -> None:
    payload = {
        "params": io.params_to_dict(PlantParams(HeatPumpParams(), BuildingParams())),
        "provenance": {"data_to": "2026-11-11T16:32:00+00:00"},
        "credibility": {"credible": True},
        "intervals_90": {
            "building": {"h_air_out": [180.0, 220.0], "time_constant_h": [10, 100], "x": "y"}
        },
    }
    read = run.read_champion({"model": "house-20261111", "house_payload": payload})
    assert read is not None
    assert read.credible is True
    assert read.data_to == pytest.approx(1794414720.0)
    assert read.intervals == {"h_air_out": (180.0, 220.0), "time_constant_h": (10.0, 100.0)}
    assert run.read_champion({"model": "x", "house_payload": {"params": {}}}) is None
    assert run.read_champion(None) is None
    bare = run.read_champion({"model": "x", "house_payload": {"params": payload["params"]}})
    assert bare is not None
    assert (bare.credible, bare.data_to, bare.intervals) == (False, None, {})


def test_the_champions_frozen_heat_loss_gate_is_rechecked_against_todays_signature() -> None:
    frozen = credibility()["gates"]["heat_loss"]
    kept = champion(building=BuildingParams(h_air_out=310.0), heat_loss=frozen)
    gate = run.champion_heat_loss(kept, signature(h=320.0))
    assert gate["ok"] is True
    assert gate["checks"]["ua_agreement"]["signature"] == "this run"
    moved = run.champion_heat_loss(kept, signature(h=420.0))
    assert moved["ok"] is False
    assert moved["needed"] == ["ua_disagrees"]
    assert run.champion_heat_loss(kept, None)["ok"] is True
    unstable = credibility(fold_uas=(250.0, 320.0))["gates"]["heat_loss"]
    shaky = run.champion_heat_loss(replace(kept, heat_loss=unstable), signature(h=320.0))
    assert shaky["ok"] is False
    assert shaky["needed"] == ["ua_unstable"]


def test_a_champion_from_before_the_gates_keeps_its_old_credibility_as_heat_loss() -> None:
    old = champion(building=BuildingParams(h_air_out=310.0), credible=True)
    assert old.heat_loss is None
    assert run.champion_heat_loss(old, signature(h=320.0))["ok"] is True
    thin = replace(old, credible=False, needed={"heating_days": 4, "outside_span_k": 0.0})
    gate = run.champion_heat_loss(thin, signature(h=320.0))
    assert gate["ok"] is False
    assert gate["needed"] == ["more_heating_days"]
    assert run.champion_heat_loss(replace(old, credible=False), None)["needed"] == ["legacy_model"]


def test_the_champion_gates_are_read_back_from_its_house_file() -> None:
    frozen = credibility()
    payload = {
        "params": io.params_to_dict(PlantParams(HeatPumpParams(), BuildingParams())),
        "credibility": frozen,
    }
    read = run.read_champion({"model": "m", "house_payload": payload})
    assert read is not None
    assert read.heat_loss == frozen["gates"]["heat_loss"]
    broken = payload | {"credibility": frozen | {"gates": {"heat_loss": {"ok": True}}}}
    legacy = run.read_champion({"model": "m", "house_payload": broken})
    assert legacy is not None
    assert legacy.heat_loss is None
