"""Run the sun day shift evaluation, choose the defaults it supports and write its outputs.

:func:`evaluate` simulates every arm in every scenario on the same replicas as their
baselines and judges them (:mod:`~ovenbird_sim.evaluate.dayshift_gate`).
:func:`recommend` applies the owner's rule for the defaults: keep them when they pass;
otherwise take a swept setting with both halves that passes everywhere (the one that
cuts the night run time most in the intended scenario); otherwise, when one half
passes alone and the other does not, ship with the failing half at 0. ``on`` may be
unlocked only when the gate is calibrated and the final setting passes.
:func:`write_outputs` writes ``dayshift.json`` (every KPI per run, every interval and
verdict) and ``dayshift_tables.md`` (the tables for the report).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ovenbird_sim.evaluate import dayshift as ds
from ovenbird_sim.evaluate import dayshift_gate as gate
from ovenbird_sim.evaluate.dayshift import Arm, Params, Row, RunResult, RunSpec
from ovenbird_sim.evaluate.plangate import Interval, Outcome

QUICK_REPLICAS: Final = 2
QUICK_DAYS: Final = 2
FULL_REPLICAS: Final = 32
MIN_GATE_REPLICAS: Final = 16


@dataclass(frozen=True, slots=True)
class Options:
    """What to evaluate.

    Parameters
    ----------
    scenarios
        Scenario names.
    sweep
        Rule settings.
    replicas
        Replicas per scenario.
    days
        Simulated days per run (the first is warm-up).
    seed
        Base seed.
    workers
        Worker processes (``None``: all cores but one).
    calibration
        Run the calibration arms.
    """

    scenarios: tuple[str, ...] = tuple(ds.SCENARIOS)
    sweep: tuple[Params, ...] = ds.SWEEP
    replicas: int = FULL_REPLICAS
    days: int = ds.DAYS
    seed: int = ds.DEFAULT_SEED
    workers: int | None = None
    calibration: bool = True

    @property
    def complete(self) -> bool:
        """Whether this is a full evaluation (every scenario, enough replicas, full runs)."""
        return (
            set(self.scenarios) == set(ds.SCENARIOS)
            and self.replicas >= MIN_GATE_REPLICAS
            and self.days >= ds.DAYS
            and self.calibration
        )

    @classmethod
    def quick(cls, workers: int | None = 1) -> Options:
        """Return the quick options: two scenarios, the default setting, two short replicas."""
        return cls(
            scenarios=ds.QUICK_SCENARIOS,
            sweep=(ds.DEFAULT_SETTING,),
            replicas=QUICK_REPLICAS,
            days=QUICK_DAYS,
            workers=workers,
        )


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Everything an evaluation produced.

    Parameters
    ----------
    options
        What was evaluated.
    results
        KPIs per run.
    verdicts
        Verdict per arm label.
    runtime_s
        Wall time of the simulations.
    """

    options: Options
    results: Mapping[RunSpec, RunResult]
    verdicts: Mapping[str, gate.Verdict]
    runtime_s: float

    def rows(self, scenario: str, arm: Arm) -> tuple[list[Row], list[Row]]:
        """Return the baseline and arm rows of a scenario, paired by replica."""
        specs = ds.specs_for(
            scenario, arm, self.options.replicas, self.options.days, self.options.seed
        )
        half = len(specs) // 2
        return (
            [self.results[s].row for s in specs[:half]],
            [self.results[s].row for s in specs[half:]],
        )

    def by_hour(self, scenario: str, arm: Arm) -> list[float]:
        """Return the mean applied offset per local hour of an arm in a scenario."""
        specs = ds.specs_for(
            scenario, arm, self.options.replicas, self.options.days, self.options.seed
        )
        planned = [self.results[s].by_hour for s in specs[len(specs) // 2 :]]
        return [sum(values) / len(values) for values in zip(*planned, strict=True)]


def evaluate(options: Options, progress: Callable[[int, int], None] | None = None) -> Evaluation:
    """Simulate and judge every arm of ``options`` in every scenario.

    Parameters
    ----------
    options
        What to evaluate.
    progress
        Called with ``(done, total)`` runs.

    Returns
    -------
    Evaluation
        The KPIs of every run and the verdict of every arm.
    """
    chosen = ds.arms(options.sweep, options.calibration)
    specs = [
        spec
        for arm in chosen
        for scenario in options.scenarios
        for spec in ds.specs_for(scenario, arm, options.replicas, options.days, options.seed)
    ]
    started = time.perf_counter()
    results = ds.run_all(specs, options.workers, progress)
    runtime = time.perf_counter() - started
    partial = Evaluation(options, results, {}, runtime)
    verdicts = {
        arm.label: gate.verdict(
            arm, {scenario: partial.rows(scenario, arm) for scenario in options.scenarios}
        )
        for arm in chosen
    }
    return Evaluation(options, results, verdicts, runtime)


@dataclass(frozen=True, slots=True)
class Recommendation:
    """The defaults the evaluation supports and whether ``on`` may be unlocked.

    Parameters
    ----------
    setting
        The final default setting.
    changed
        Whether it differs from :data:`~ovenbird_sim.evaluate.dayshift.DEFAULT_SETTING`.
    unlock
        Whether ``on`` may be unlocked.
    reasons
        Plain sentences: how the setting was chosen and why ``on`` is (not) unlocked.
    """

    setting: Params
    changed: bool
    unlock: bool
    reasons: tuple[str, ...]


def _night_cut(evaluation: Evaluation, arm: Arm) -> float:
    """Return the change of the night run time in the intended scenario (``inf`` if absent)."""
    verdict = evaluation.verdicts.get(arm.label)
    if verdict is None or gate.INTENDED not in evaluation.options.scenarios:
        return math.inf
    return verdict.cell(gate.INTENDED).diffs["night_run_h"].estimate


def recommend(evaluation: Evaluation) -> Recommendation:
    """Return the defaults the evaluation supports (see the module docstring).

    Parameters
    ----------
    evaluation
        Finished evaluation with the verdicts of every arm.
    """
    verdicts = evaluation.verdicts
    reasons: list[str] = []
    calibrated = gate.calibrated(verdicts)
    if not calibrated:
        reasons.append("The gate is not calibrated in this run; nothing may be unlocked.")
    complete = evaluation.options.complete
    if not complete:
        reasons.append(
            "This is not a full evaluation (scenarios, replicas or days missing): a smoke "
            "run, not a gate result; nothing may be unlocked from it."
        )
    default = Arm(ds.RULE, ds.DEFAULT_SETTING)
    rules = [Arm(ds.RULE, p) for p in evaluation.options.sweep if ds.is_candidate(p)]
    passing = [a for a in rules if verdicts[a.label].passed]
    setting = ds.DEFAULT_SETTING
    found = verdicts.get(default.label)
    if found is not None and found.passed:
        reasons.append(f"The defaults ({ds.setting_label(setting)}) pass the gate.")
    else:
        state = "are not evaluated" if found is None else f"are {found.outcome.value}"
        reasons.append(f"The defaults ({ds.setting_label(setting)}) {state}.")
        both = [a for a in passing if ds.setting_kind(a.params) == "both"]
        boost = [a for a in rules if ds.setting_kind(a.params) == "boost only"]
        back = [a for a in rules if ds.setting_kind(a.params) == "set-back only"]
        if both:
            best = min(both, key=lambda a: _night_cut(evaluation, a))
            setting = best.params
            reasons.append(
                f"{len(both)} setting(s) with both halves pass everywhere; the one that cuts "
                f"the night run time most becomes the default: {ds.setting_label(setting)}."
            )
        elif any(a in passing for a in boost) and not any(a in passing for a in back) and back:
            best = min((a for a in boost if a in passing), key=lambda a: _night_cut(evaluation, a))
            setting = best.params
            reasons.append(
                "The boost half passes alone and the set-back half does not: ship with the "
                f"set-back at 0 ({ds.setting_label(setting)})."
            )
        elif any(a in passing for a in back) and not any(a in passing for a in boost) and boost:
            best = min((a for a in back if a in passing), key=lambda a: _night_cut(evaluation, a))
            setting = best.params
            reasons.append(
                "The set-back half passes alone and the boost half does not: ship with the "
                f"boost at 0 ({ds.setting_label(setting)})."
            )
        else:
            reasons.append("No swept setting passes everywhere; the defaults stay.")
    final = verdicts.get(Arm(ds.RULE, setting).label)
    unlock = complete and calibrated and final is not None and final.passed
    if unlock:
        reasons.append("The final setting passes a calibrated gate: on may be unlocked.")
    else:
        reasons.append("The final setting does not pass a calibrated gate: on stays locked.")
    return Recommendation(setting, setting != ds.DEFAULT_SETTING, unlock, tuple(reasons))


def _interval(iv: Interval, digits: int = 2) -> str:
    """Return ``+0.12 [-0.03, +0.27]``."""
    if math.isnan(iv.estimate):
        return "n/a"
    return f"{iv.estimate:+.{digits}f} [{iv.low:+.{digits}f}, {iv.high:+.{digits}f}]"


def _share(iv: Interval) -> str:
    """Return a relative interval in percent."""
    if math.isnan(iv.estimate):
        return "n/a"
    return f"{100 * iv.estimate:+.1f} % [{100 * iv.low:+.1f}, {100 * iv.high:+.1f}]"


def _short(outcome: Outcome) -> str:
    """Return ``P``, ``F`` or ``I``."""
    return {Outcome.PASSED: "P", Outcome.FAILED: "F", Outcome.INCONCLUSIVE: "I"}[outcome]


def _cell_outcomes(cell: gate.Cell) -> str:
    """Return the outcome of a cell with its failing and inconclusive criteria."""
    text = cell.outcome.value
    bad = cell.named(Outcome.FAILED) + cell.named(Outcome.INCONCLUSIVE)
    if cell.idle is not None:
        text += " (idle)" if cell.idle else ""
    return f"{text} ({', '.join(bad)})" if bad else text


def scenario_table(evaluation: Evaluation, arm: Arm) -> list[str]:
    """Return the per-scenario table of an arm (paired differences per 7 days, 95 %)."""
    verdict = evaluation.verdicts[arm.label]
    head = (
        "| scenario | Δ below, 07-23 (Kh) | Δ below, 07-09 (Kh) | Δ below -0.5 K, 07-23 / 07-09 "
        "(Kh) | Δ above +1.5 K (Kh) | Δ starts | Δ run 23-07 (h) | Δ electricity | "
        "night → day (kWh) | Δ COP | Δ writes | gate |"
    )
    lines = [head, "|" + " --- |" * 12]
    for cell in verdict.cells:
        d = cell.diffs
        band = (
            f"{d['below_band_occ_kh'].estimate:+.2f} / {d['below_band_morning_kh'].estimate:+.2f}"
        )
        shifted = -d["night_elec_kwh"].estimate
        lines.append(
            f"| {cell.scenario} | {_interval(d['below_occ_kh'])} | "
            f"{_interval(d['below_morning_kh'])} | {band} | {_interval(d['above_kh'])} | "
            f"{_interval(d['starts'], 1)} | {_interval(d['night_run_h'], 1)} | "
            f"{_share(d['elec_share'])} | {shifted:+.2f} | {d['cop'].estimate:+.3f} | "
            f"{d['writes'].estimate:+.1f} | {_cell_outcomes(cell)} |"
        )
    return lines


def sweep_table(evaluation: Evaluation) -> list[str]:
    """Return one line per arm: verdict, failing and inconclusive cells, intended benefit."""
    lines = [
        "| arm | kind | gate | FAIL | INCONCLUSIVE | sunny_mild: Δ run 23-07 (h) | "
        "sunny_mild: Δ below 07-23 (Kh) | sunny_mild: night → day (kWh) |",
        "|" + " --- |" * 8,
    ]
    for label, verdict in evaluation.verdicts.items():
        arm = verdict.arm
        kind = "calibration" if arm.calibration else ds.setting_kind(arm.params)
        intended = (
            verdict.cell(gate.INTENDED) if gate.INTENDED in evaluation.options.scenarios else None
        )
        if intended is not None:
            b = gate.benefit(intended)
            run, below, shifted = (
                _interval(b.night_run_h, 1),
                _interval(b.below_occ_kh),
                f"{b.shifted_kwh:+.2f}",
            )
        else:
            run = below = shifted = "n/a"
        fail = "; ".join(verdict.listed(Outcome.FAILED)) or "-"
        inc = "; ".join(verdict.listed(Outcome.INCONCLUSIVE)) or "-"
        lines.append(
            f"| {label} | {kind} | {verdict.outcome.value} | {fail} | {inc} | {run} | "
            f"{below} | {shifted} |"
        )
    return lines


def outcome_grid(evaluation: Evaluation) -> list[str]:
    """Return the outcome of every criterion per arm and scenario (P, F, I)."""
    names = [c.name for c in gate.CRITERIA]
    lines = [
        "Criteria in order: " + ", ".join(names) + "; then the idle check where it applies.",
        "",
        "| arm | " + " | ".join(evaluation.options.scenarios) + " |",
        "|" + " --- |" * (len(evaluation.options.scenarios) + 1),
    ]
    for label, verdict in evaluation.verdicts.items():
        cells = []
        for cell in verdict.cells:
            text = "".join(_short(c.outcome) for c in cell.checks)
            if cell.idle is not None:
                text += " idle" if cell.idle else " ACTIVE"
            cells.append(text)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return lines


def baseline_table(evaluation: Evaluation) -> list[str]:
    """Return the baseline's mean KPIs per scenario (per 7 days)."""
    arm = Arm(ds.RULE, evaluation.options.sweep[0])
    lines = [
        "| scenario | below 07-23 (Kh) | below 07-09 (Kh) | above +1.5 K (Kh) | starts | "
        "run 23-07 (h) | electricity (kWh) | COP | room mean (°C) |",
        "|" + " --- |" * 9,
    ]
    for scenario in evaluation.options.scenarios:
        m = gate.mean_rows(evaluation.rows(scenario, arm)[0])
        lines.append(
            f"| {scenario} | {m['below_occ_kh']:.2f} | {m['below_morning_kh']:.2f} | "
            f"{m['above_kh']:.2f} | {m['starts']:.1f} | {m['night_run_h']:.1f} | "
            f"{m['elec_kwh']:.1f} | {m['cop']:.2f} | {m['room_mean_c']:.2f} |"
        )
    return lines


def render(evaluation: Evaluation, recommendation: Recommendation) -> str:
    """Return the Markdown tables of an evaluation.

    Parameters
    ----------
    evaluation
        Finished evaluation.
    recommendation
        Recommendation derived from it, shown in the tables.
    """
    o = evaluation.options
    final = Arm(ds.RULE, recommendation.setting)
    lines = [
        "# Sun day shift: evaluation tables",
        "",
        f"Replicas {o.replicas}, {o.days} simulated days (the first is warm-up), seed {o.seed}, "
        f"zone {ds.ZONE}, {len(evaluation.results)} runs in {evaluation.runtime_s:.0f} s.",
        "Differences are arm minus baseline, per 7 days, mean over replicas with a 95 % "
        "bootstrap interval.",
        "",
        "## Margins",
        "",
        "| criterion | largest acceptable rise per 7 days |",
        "| --- | --- |",
    ]
    lines += [f"| {gate.MARGIN_TEXT[c.name]} | {c.margin:g} |" for c in gate.CRITERIA]
    lines += ["", "## Calibration", ""]
    lines += [f"- {line}" for line in gate.calibration_lines(evaluation.verdicts)]
    lines += ["", "## Recommendation", ""]
    lines += [f"- {line}" for line in recommendation.reasons]
    lines += ["", "## Every arm", "", *sweep_table(evaluation)]
    lines += ["", "## Outcome per criterion", "", *outcome_grid(evaluation)]
    if final.label in evaluation.verdicts:
        lines += ["", f"## Final setting per scenario: {final.label}", ""]
        lines += scenario_table(evaluation, final)
    default = Arm(ds.RULE, ds.DEFAULT_SETTING)
    if default != final and default.label in evaluation.verdicts:
        lines += ["", f"## Defaults per scenario: {default.label}", ""]
        lines += scenario_table(evaluation, default)
    for params in o.sweep:
        arm = Arm(ds.RULE, params)
        if arm in (final, default):
            continue
        lines += ["", f"## {arm.label}", "", *scenario_table(evaluation, arm)]
    lines += ["", "## Baseline per scenario (means per 7 days)", "", *baseline_table(evaluation)]
    if gate.INTENDED in o.scenarios and final.label in evaluation.verdicts:
        hours = evaluation.by_hour(gate.INTENDED, final)
        lines += [
            "",
            f"## Mean applied offset by local hour, {gate.INTENDED}, final setting",
            "",
            "| hour | " + " | ".join(f"{h:02d}" for h in range(24)) + " |",
            "|" + " --- |" * 25,
            "| K | " + " | ".join(f"{v:+.2f}" for v in hours) + " |",
        ]
    return "\n".join(lines) + "\n"


def _iv(iv: Interval) -> dict[str, float]:
    """Return an interval as JSON."""
    return {"estimate": iv.estimate, "low": iv.low, "high": iv.high, "n": iv.n}


def as_json(evaluation: Evaluation, recommendation: Recommendation) -> dict[str, Any]:
    """Return the evaluation as a JSON document."""
    o = evaluation.options
    return {
        "options": {
            "scenarios": list(o.scenarios),
            "sweep": [dict(p) for p in o.sweep],
            "replicas": o.replicas,
            "days": o.days,
            "seed": o.seed,
            "zone": ds.ZONE,
            "start": ds.START.isoformat(),
        },
        "runtime_s": evaluation.runtime_s,
        "margins": {c.name: c.margin for c in gate.CRITERIA},
        "calibration": gate.calibration_lines(evaluation.verdicts),
        "calibrated": gate.calibrated(evaluation.verdicts),
        "recommendation": {
            "setting": dict(recommendation.setting),
            "changed": recommendation.changed,
            "unlock": recommendation.unlock,
            "reasons": list(recommendation.reasons),
        },
        "verdicts": {
            label: {
                "outcome": v.outcome.value,
                "cells": {
                    cell.scenario: {
                        "outcome": cell.outcome.value,
                        "idle": cell.idle,
                        "checks": {
                            c.criterion: {"outcome": c.outcome.value, **_iv(c.interval)}
                            for c in cell.checks
                        },
                        "diffs": {name: _iv(iv) for name, iv in cell.diffs.items()},
                    }
                    for cell in v.cells
                },
            }
            for label, v in evaluation.verdicts.items()
        },
        "runs": [
            {
                "scenario": spec.scenario,
                "replica": spec.replica,
                "arm": spec.arm or "baseline",
                "params": dict(spec.params),
                "kpis": dict(result.row),
            }
            for spec, result in evaluation.results.items()
        ],
    }


def write_outputs(
    out: Path, evaluation: Evaluation, recommendation: Recommendation
) -> tuple[Path, Path]:
    """Write ``dayshift.json`` and ``dayshift_tables.md`` to ``out`` and return their paths."""
    out.mkdir(parents=True, exist_ok=True)
    document = out / "dayshift.json"
    tables = out / "dayshift_tables.md"
    document.write_text(json.dumps(as_json(evaluation, recommendation), indent=1, default=str))
    tables.write_text(render(evaluation, recommendation))
    return document, tables


def summary(evaluation: Evaluation, recommendation: Recommendation) -> list[str]:
    """Return the console summary."""
    lines = gate.calibration_lines(evaluation.verdicts)
    lines += [f"{label}: {v.outcome.value}" for label, v in evaluation.verdicts.items()]
    lines += list(recommendation.reasons)
    return lines


def parse_setting(values: Sequence[str]) -> Params:
    """Return a setting from ``name=value`` texts on top of the defaults."""
    current = dict(ds.DEFAULT_SETTING)
    for text in values:
        name, _, value = text.partition("=")
        if name not in current:
            raise ValueError(f"unknown setting {name!r}; known: {', '.join(current)}")
        current[name] = float(value)
    return ds.params_of(current)
