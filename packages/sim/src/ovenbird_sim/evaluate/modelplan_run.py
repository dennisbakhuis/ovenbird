"""``python -m ovenbird_sim.evaluate model-plan``: the replicated, paired evaluation of a planner.

The default run simulates every cell of the grid (:func:`ovenbird_sim.evaluate.
modelplan.cells`) on the same weather replicas as the baseline, applies the gate of
:mod:`ovenbird_sim.evaluate.plangate` (with the one extension of the starts criterion),
the pooled benefit and the combined verdict, and writes ``model_plan.json`` (every
replica's KPIs, every interval, the verdict) and ``model_plan_tables.md``.
``--sweep`` instead runs the planner's parameter sets (:data:`~ovenbird_sim.evaluate.
modelplan.SWEEPS`) over the same grid with fewer replicas and no extension; it only
ranks settings and never gives a verdict.
"""

from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

from ovenbird_sim.evaluate import meta, modelplan, plangate
from ovenbird_sim.evaluate.modelplan import (
    BASE_FORECASTS,
    DEFAULT_DAYS,
    DEFAULT_MODELS,
    DEFAULT_REPLICAS,
    DEFAULT_SEED,
    SCENARIOS,
    SHIFT_FORECASTS,
    SUNNY,
    CellId,
    Params,
    RunSpec,
)
from ovenbird_sim.evaluate.plangate import (
    CRITERIA,
    MAX_REPLICAS,
    CellVerdict,
    Interval,
    Outcome,
    Row,
    RunResult,
    Verdict,
)

QUICK_SCENARIOS: Final = ("sunny_cold", "false_sun_cold")
QUICK_MODELS: Final = ("correct", "aperture_x2")
QUICK_REPLICAS: Final = 4
QUICK_MAX_REPLICAS: Final = 6
QUICK_DAYS: Final = 3
SWEEP_REPLICAS: Final = 8
DEFAULT_PLANNER: Final = "v1"
JSON_VERSION: Final = 2

Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class EvalOptions:
    """Options of the evaluation.

    Parameters
    ----------
    planner
        Planner name (:data:`~ovenbird_sim.evaluate.modelplan.PLANNERS`).
    params
        Planner parameters.
    replicas
        Weather replicas per cell (the first look).
    max_replicas
        Replicas of a cell after the starts extension.
    days
        Simulated days per run (the first is dropped).
    seed
        Base seed of the replicas.
    workers
        Worker processes (``None``: the CPU count).
    scenarios, models, forecasts, shifts
        The grid (shifted forecasts meet only the correct model).
    sweep_replicas
        Replicas per cell of a sweep.
    """

    planner: str = DEFAULT_PLANNER
    params: Params = ()
    replicas: int = DEFAULT_REPLICAS
    max_replicas: int = MAX_REPLICAS
    days: int = DEFAULT_DAYS
    seed: int = DEFAULT_SEED
    workers: int | None = None
    scenarios: tuple[str, ...] = tuple(SCENARIOS)
    models: tuple[str, ...] = DEFAULT_MODELS
    forecasts: tuple[str, ...] = BASE_FORECASTS
    shifts: tuple[str, ...] = SHIFT_FORECASTS
    sweep_replicas: int = SWEEP_REPLICAS

    @classmethod
    def quick(cls, planner: str = DEFAULT_PLANNER) -> EvalOptions:
        """Return the small grid used by the tests (structure and determinism only)."""
        return cls(
            planner=planner,
            replicas=QUICK_REPLICAS,
            max_replicas=QUICK_MAX_REPLICAS,
            days=QUICK_DAYS,
            scenarios=QUICK_SCENARIOS,
            models=QUICK_MODELS,
            forecasts=("perfect",),
            shifts=(),
            sweep_replicas=2,
        )

    def cell_ids(self) -> list[CellId]:
        """Return the cells of the grid."""
        return modelplan.cells(self.scenarios, self.models, self.forecasts, self.shifts)


@dataclass(frozen=True, slots=True)
class CellResult:
    """Outcome of one cell.

    Parameters
    ----------
    cell
        The cell.
    verdict
        The gate's checks.
    without, with_plan
        Rows per replica (all replicas run for the cell, paired by position).
    diagnostics
        Split of the below-comfort difference by plan state and hour of day.
    """

    cell: CellId
    verdict: CellVerdict
    without: tuple[Row, ...]
    with_plan: tuple[Row, ...]
    diagnostics: Mapping[str, Any]

    @property
    def extended(self) -> bool:
        """Whether the cell got the starts extension."""
        return any(c.extended for c in self.verdict.checks)


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Result of an evaluation.

    Parameters
    ----------
    options
        What was run.
    cells
        Per cell the gate and the replicas.
    verdict
        The combined verdict.
    runtime_s
        Wall time.
    runs
        Number of simulations.
    """

    options: EvalOptions
    cells: tuple[CellResult, ...]
    verdict: Verdict
    runtime_s: float
    runs: int


@dataclass(frozen=True, slots=True)
class SweepLine:
    """Outcome of one parameter set of a sweep.

    Parameters
    ----------
    params
        The parameter set.
    counts
        Cells per role (``credible``, ``stress``) and outcome.
    benefit
        The pooled benefit interval.
    failing
        Labels of the failing cells.
    """

    params: Params
    counts: Mapping[str, Mapping[str, int]]
    benefit: Interval
    failing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Sweep:
    """Result of a sweep.

    Parameters
    ----------
    options
        What was run.
    lines
        One per parameter set.
    runtime_s
        Wall time.
    runs
        Number of simulations.
    """

    options: EvalOptions
    lines: tuple[SweepLine, ...]
    runtime_s: float
    runs: int


@dataclass(slots=True)
class _Runner:
    options: EvalOptions
    log: Log
    cache: dict[RunSpec, RunResult] = field(default_factory=dict)
    used: set[RunSpec] = field(default_factory=set)

    def run(self, specs: Sequence[RunSpec], label: str) -> None:
        self.used.update(specs)
        todo = [s for s in dict.fromkeys(specs) if s not in self.cache]

        def report(done: int, total: int) -> None:
            if done == total or done % 100 == 0:
                self.log(f"{label}: {done}/{total} runs")

        self.cache.update(modelplan.run_all(todo, self.options.workers, report))

    def pair(
        self, cell: CellId, replicas: range, params: Params
    ) -> tuple[list[RunResult], list[RunResult]]:
        o = self.options
        specs = modelplan.specs_for(cell, replicas, o.days, o.seed, o.planner, params)
        half = len(specs) // 2
        return [self.cache[s] for s in specs[:half]], [self.cache[s] for s in specs[half:]]


def _rows(results: Sequence[RunResult]) -> tuple[Row, ...]:
    return tuple(r.row for r in results)


def _judge(
    runner: _Runner, cell: CellId, n: int, params: Params, base_n: int
) -> tuple[CellVerdict, list[RunResult], list[RunResult]]:
    without, with_plan = runner.pair(cell, range(n), params)
    verdict = plangate.judge_cell(_rows(without), _rows(with_plan), cell.label, base_n)
    return verdict, without, with_plan


def _pooled_benefit(results: Sequence[tuple[CellId, Sequence[Row], Sequence[Row]]], n: int) -> Any:
    pooled = [(w, p) for c, w, p in results if c.credible and c.scenario in SUNNY]
    return plangate.benefit(pooled, n)


def _check_planner(options: EvalOptions) -> None:
    modelplan.build_arm(options.planner, modelplan.CORRECT, options.params)


def evaluate(
    options: EvalOptions,
    log: Log = lambda _message: None,
    cache: dict[RunSpec, RunResult] | None = None,
) -> Evaluation:
    """Run the grid, the starts extension, the gate, the benefit and the verdict.

    Parameters
    ----------
    options
        What to run.
    log
        Progress sink.
    cache
        Runs already simulated (shared between evaluations of several planners: the
        baselines are the same); new runs are added to it.

    Returns
    -------
    Evaluation
        Cells, verdict and runtime.
    """
    started = time.monotonic()
    _check_planner(options)
    runner = _Runner(options, log, cache if cache is not None else {})
    ids = options.cell_ids()
    first = range(options.replicas)
    runner.run(
        [
            s
            for c in ids
            for s in modelplan.specs_for(
                c, first, options.days, options.seed, options.planner, options.params
            )
        ],
        "grid",
    )
    verdicts = {
        c: _judge(runner, c, options.replicas, options.params, options.replicas)[0] for c in ids
    }
    extend = [
        c
        for c in ids
        if plangate.wants_extension(verdicts[c], options.replicas, options.max_replicas)
    ]
    if extend:
        log(f"starts extension: {len(extend)} cells to {options.max_replicas} replicas")
        more = range(options.replicas, options.max_replicas)
        runner.run(
            [
                s
                for c in extend
                for s in modelplan.specs_for(
                    c, more, options.days, options.seed, options.planner, options.params
                )
            ],
            "extension",
        )
    out: list[CellResult] = []
    for c in ids:
        n = options.max_replicas if c in extend else options.replicas
        verdict, without, with_plan = _judge(runner, c, n, options.params, options.replicas)
        diagnostics = plangate.plan_split(
            without[: options.replicas], with_plan[: options.replicas]
        )
        out.append(CellResult(c, verdict, _rows(without), _rows(with_plan), diagnostics))
    benefit = _pooled_benefit([(r.cell, r.without, r.with_plan) for r in out], options.replicas)
    credible = [(r.without, r.with_plan) for r in out if r.cell.credible]
    pooled = [plangate.pooled_check(k, credible, options.replicas) for k in CRITERIA]
    combined = plangate.combine(
        [(r.cell.label, r.cell.credible, r.verdict) for r in out], benefit, pooled
    )
    return Evaluation(options, tuple(out), combined, time.monotonic() - started, len(runner.used))


def sweep(options: EvalOptions, log: Log = lambda _message: None) -> Sweep:
    """Run every parameter set of the planner's sweep over the grid (no extension).

    Raises
    ------
    KeyError
        When the planner has no sweep.
    """
    started = time.monotonic()
    runner = _Runner(options, log)
    n = options.sweep_replicas
    ids = options.cell_ids()
    lines: list[SweepLine] = []
    for values in modelplan.SWEEPS[options.planner]:
        params = modelplan.params_of(values)
        _check_planner(replace(options, params=params))
        runner.run(
            [
                s
                for c in ids
                for s in modelplan.specs_for(
                    c, range(n), options.days, options.seed, options.planner, params
                )
            ],
            f"sweep {modelplan.params_label(params)}",
        )
        judged = [(c, *_judge(runner, c, n, params, n)) for c in ids]
        counts: dict[str, Counter[str]] = {"credible": Counter(), "stress": Counter()}
        for c, verdict, _, _ in judged:
            counts["credible" if c.credible else "stress"][verdict.outcome.value] += 1
        benefit = _pooled_benefit([(c, _rows(w), _rows(p)) for c, _, w, p in judged], n)
        failing = tuple(
            f"{c.label} [{', '.join(v.named(Outcome.FAILED))}]"
            for c, v, _, _ in judged
            if v.outcome is Outcome.FAILED
        )
        lines.append(SweepLine(params, {k: dict(v) for k, v in counts.items()}, benefit, failing))
        log(f"sweep {modelplan.params_label(params)}: {dict(counts['credible'])} credible")
    return Sweep(options, tuple(lines), time.monotonic() - started, len(runner.used))


def _fmt(x: float, digits: int = 2) -> str:
    return "nan" if not math.isfinite(x) else f"{x:+.{digits}f}"


def _check_text(check: plangate.Check) -> str:
    i = check.interval
    scale, digits = (100.0, 1) if plangate.CRITERION[check.criterion].relative else (1.0, 2)
    mark = "*" if check.extended else ""
    return (
        f"{_fmt(i.estimate * scale, digits)} [{_fmt(i.low * scale, digits)}, "
        f"{_fmt(i.high * scale, digits)}] {check.outcome.value[0]}{mark}"
    )


def counts(cells: Sequence[CellResult]) -> dict[str, dict[str, int]]:
    """Return the number of cells per role and outcome."""
    out: dict[str, dict[str, int]] = {}
    for role, credible in (("credible", True), ("stress", False)):
        found = Counter(c.verdict.outcome.value for c in cells if c.cell.credible is credible)
        out[role] = {o.value: found.get(o.value, 0) for o in Outcome}
    return out


def criterion_counts(cells: Sequence[CellResult]) -> dict[str, dict[str, dict[str, int]]]:
    """Return per role and criterion the number of checks per outcome."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for role, credible in (("credible", True), ("stress", False)):
        out[role] = {}
        for criterion in CRITERIA:
            found = Counter(
                c.verdict.check(criterion.name).outcome.value
                for c in cells
                if c.cell.credible is credible
            )
            out[role][criterion.name] = {o.value: found.get(o.value, 0) for o in Outcome}
    return out


def render_markdown(ev: Evaluation) -> str:
    """Return the evaluation as Markdown (verdict, counts, per-scenario tables, diagnostics)."""
    o = ev.options
    parts = [
        f"## Verdict: planner `{o.planner}` ({modelplan.params_label(o.params)})\n",
        "\n".join(f"- {line}" for line in ev.verdict.lines()) + "\n",
        _counts_table(ev),
        _pooled_table(ev),
    ]
    for scenario in o.scenarios:
        parts.append(
            _scenario_table(scenario, [c for c in ev.cells if c.cell.scenario == scenario])
        )
    parts.append(_diagnostics_table(ev.cells))
    v = ev.verdict
    if v.credible_fail or v.credible_inconclusive or v.credible_cost_inconclusive or v.stress_fail:
        listed = [
            ("Credible cells that fail", ev.verdict.credible_fail),
            ("Credible cells inconclusive on comfort (blocking)", ev.verdict.credible_inconclusive),
            (
                "Credible cells inconclusive on a cost criterion only (not blocking)",
                ev.verdict.credible_cost_inconclusive,
            ),
            ("Stress cells that fail", ev.verdict.stress_fail),
        ]
        for title, labels in listed:
            if labels:
                parts.append(f"{title}:\n\n" + "\n".join(f"- {x}" for x in labels) + "\n")
    return "\n".join(parts)


def _counts_table(ev: Evaluation) -> str:
    lines = [
        "### Cells per outcome\n",
        "| role | PASS | INCONCLUSIVE | FAIL |",
        "|---|---|---|---|",
    ]
    for role, found in counts(ev.cells).items():
        lines.append(f"| {role} | {found['PASS']} | {found['INCONCLUSIVE']} | {found['FAIL']} |")
    lines += [
        "",
        "| role | criterion | PASS | INCONCLUSIVE | FAIL |",
        "|---|---|---|---|---|",
    ]
    for role, per in criterion_counts(ev.cells).items():
        for name, found in per.items():
            lines.append(
                f"| {role} | {name} | {found['PASS']} | {found['INCONCLUSIVE']} | {found['FAIL']} |"
            )
    return "\n".join(lines) + "\n"


def _pooled_table(ev: Evaluation) -> str:
    lines = [
        "### Every criterion on the mean over the credible cells\n",
        "The cost criteria (starts, elec, writes) decide here; the comfort criteria per cell.\n",
        "| criterion | difference [95 % interval] | margin | outcome |",
        "|---|---|---|---|",
    ]
    for k in ev.verdict.pooled:
        relative = plangate.CRITERION[k.criterion].relative
        margin = f"{k.margin * 100:+.0f} %" if relative else f"{k.margin:+.2f}"
        lines.append(f"| {k.criterion} | {_check_text(k)[:-2]} | {margin} | {k.outcome.value} |")
    return "\n".join(lines) + "\n"


def _scenario_table(scenario: str, cells: Sequence[CellResult]) -> str:
    head = (
        f"### {scenario}\n\n"
        "Paired difference with minus without, mean over replicas per day, 95 % interval "
        "(starts: Pocock level) and outcome (P/I/F; * judged on the extended replicas). "
        "Electricity and writes in %.\n\n"
        "| model / forecast | role | n | below 20.5 °C (Kh/d) | below 21 °C (Kh/d) "
        "| starts/d | elec % | writes % | above 21.5 °C (Kh/d) | plan applied | cell |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    body = []
    for c in cells:
        v = c.verdict
        n = len(c.without)
        above = [w["above_kh"] - b["above_kh"] for b, w in zip(c.without, c.with_plan, strict=True)]
        share = sum(w["plan_share"] for w in c.with_plan) / n
        body.append(
            f"| {c.cell.model} / {c.cell.forecast} | {'credible' if c.cell.credible else 'stress'} "
            f"| {n} | "
            + " | ".join(_check_text(v.check(k.name)) for k in CRITERIA)
            + f" | {_fmt(sum(above) / n)} | {share * 100:.0f} % | {v.outcome.value} |"
        )
    return head + "\n".join(body) + "\n"


def _diagnostics_table(cells: Sequence[CellResult]) -> str:
    out = [
        "### Diagnostic: below-comfort difference by plan state and hour (Kh/day)\n",
        "Not part of the gate. Plan active / none: the paired difference attributed by the "
        "share of plan-applied ticks per quarter hour of the planned run. Worst hour: the "
        "hour of day (UTC) with the largest mean difference.\n",
        "| cell | plan active | plan none | worst hour |",
        "|---|---|---|---|",
    ]
    for c in cells:
        d = c.diagnostics
        hours = list(d["below_by_hour_kh"])
        worst = max(range(24), key=lambda h: hours[h])
        out.append(
            f"| {c.cell.label} | {_fmt(d['below_plan_active_kh'], 3)} "
            f"| {_fmt(d['below_plan_none_kh'], 3)} | {worst:02d}h {_fmt(hours[worst], 3)} |"
        )
    return "\n".join(out) + "\n"


def render_sweep(sw: Sweep) -> str:
    """Return a sweep as Markdown."""
    out = [
        f"## Sweep of planner `{sw.options.planner}` ({sw.options.sweep_replicas} replicas, "
        "no extension; ranks settings, gives no verdict)\n",
        "| parameters | credible P / I / F | stress P / I / F | benefit (Kh/day) |",
        "|---|---|---|---|",
    ]
    for line in sw.lines:
        cr = line.counts.get("credible", {})
        st = line.counts.get("stress", {})
        b = line.benefit
        out.append(
            f"| {modelplan.params_label(line.params)} "
            f"| {cr.get('PASS', 0)} / {cr.get('INCONCLUSIVE', 0)} / {cr.get('FAIL', 0)} "
            f"| {st.get('PASS', 0)} / {st.get('INCONCLUSIVE', 0)} / {st.get('FAIL', 0)} "
            f"| {_fmt(b.estimate, 3)} [{_fmt(b.low, 3)}, {_fmt(b.high, 3)}] |"
        )
    return "\n".join(out) + "\n"


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def _clean_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(k): _clean(v) for k, v in value.items()}


def _interval_json(i: Interval) -> dict[str, Any]:
    return {"estimate": i.estimate, "low": i.low, "high": i.high, "n": i.n, "alpha": i.alpha}


def _options_json(o: EvalOptions) -> dict[str, Any]:
    return {
        "planner": o.planner,
        "params": dict(o.params),
        "replicas": o.replicas,
        "max_replicas": o.max_replicas,
        "days": o.days,
        "seed": o.seed,
        "scenarios": list(o.scenarios),
        "models": list(o.models),
        "forecasts": list(o.forecasts),
        "shifts": list(o.shifts),
        "sweep_replicas": o.sweep_replicas,
    }


def rule_json() -> dict[str, Any]:
    """Return the gate rule as data (so a reader can re-apply it to the replica rows)."""
    return {
        "criteria": [
            {
                "name": c.name,
                "kpi": c.kpi,
                "margin": c.margin,
                "relative": c.relative,
                "floor": c.floor,
                "adaptive": c.adaptive,
                "cost": c.cost,
            }
            for c in CRITERIA
        ],
        "alpha": plangate.ALPHA,
        "adaptive_alpha": plangate.POCOCK_ALPHA,
        "interval": "expanded percentile bootstrap over replicas",
        "resamples": plangate.RESAMPLES,
        "benefit": "mean over credible sunny cells of delta above + 2 delta below, upper < 0",
        "verdict": (
            "no cell fails; every credible cell passes the comfort criteria; the cost "
            "criteria pass on the mean over the credible cells; the benefit holds"
        ),
        "benefit_scenarios": list(SUNNY),
    }


def _baseline_json(ev: Evaluation) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for c in ev.cells:
        known = out.get(c.cell.scenario, [])
        if len(c.without) > len(known):
            out[c.cell.scenario] = [dict(r) for r in c.without]
    return out


def to_json(ev: Evaluation) -> dict[str, Any]:
    """Return the evaluation as a JSON-ready dictionary (non-finite numbers as null)."""
    v = ev.verdict
    return _clean_dict(
        {
            "version": JSON_VERSION,
            "options": _options_json(ev.options),
            "git": meta.git_commit(),
            "runtime_s": ev.runtime_s,
            "runs": ev.runs,
            "workers": ev.options.workers or modelplan.available_workers(),
            "rule": rule_json(),
            "baseline": _baseline_json(ev),
            "cells": [
                {
                    "scenario": c.cell.scenario,
                    "model": c.cell.model,
                    "forecast": c.cell.forecast,
                    "credible": c.cell.credible,
                    "outcome": c.verdict.outcome.value,
                    "replicas": len(c.with_plan),
                    "extended": c.extended,
                    "checks": {
                        k.criterion: {
                            "outcome": k.outcome.value,
                            "margin": k.margin,
                            "extended": k.extended,
                            **_interval_json(k.interval),
                        }
                        for k in c.verdict.checks
                    },
                    "without_mean": plangate.mean_row(c.without),
                    "with_mean": plangate.mean_row(c.with_plan),
                    "with": [dict(r) for r in c.with_plan],
                    "diagnostics": dict(c.diagnostics),
                }
                for c in ev.cells
            ],
            "counts": counts(ev.cells),
            "criterion_counts": criterion_counts(ev.cells),
            "benefit": _interval_json(v.benefit),
            "pooled_credible": {
                k.criterion: {
                    "outcome": k.outcome.value,
                    "margin": k.margin,
                    **_interval_json(k.interval),
                }
                for k in v.pooled
            },
            "verdict": {
                "unlocked": v.unlocked,
                "benefit_holds": v.benefit_holds,
                "credible_fail": list(v.credible_fail),
                "credible_inconclusive": list(v.credible_inconclusive),
                "credible_cost_inconclusive": list(v.credible_cost_inconclusive),
                "stress_fail": list(v.stress_fail),
                "stress_inconclusive": list(v.stress_inconclusive),
                "lines": v.lines(),
            },
        }
    )


def sweep_json(sw: Sweep) -> dict[str, Any]:
    """Return a sweep as a JSON-ready dictionary."""
    return _clean_dict(
        {
            "version": JSON_VERSION,
            "options": _options_json(sw.options),
            "git": meta.git_commit(),
            "runtime_s": sw.runtime_s,
            "runs": sw.runs,
            "rule": rule_json(),
            "lines": [
                {
                    "params": dict(line.params),
                    "counts": line.counts,
                    "benefit": _interval_json(line.benefit),
                    "failing": list(line.failing),
                }
                for line in sw.lines
            ],
        }
    )


def write_outputs(ev: Evaluation, out: Path) -> None:
    """Write ``model_plan.json`` and ``model_plan_tables.md`` into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_plan.json").write_text(json.dumps(to_json(ev), indent=1, sort_keys=True) + "\n")
    (out / "model_plan_tables.md").write_text(render_markdown(ev))


def write_sweep(sw: Sweep, out: Path) -> None:
    """Write ``model_plan_sweep.json`` and ``model_plan_sweep.md`` into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_plan_sweep.json").write_text(
        json.dumps(sweep_json(sw), indent=1, sort_keys=True) + "\n"
    )
    (out / "model_plan_sweep.md").write_text(render_sweep(sw))


def parse_params(values: Sequence[str] | None) -> Params:
    """Return ``name=value`` arguments as planner parameters.

    Raises
    ------
    ValueError
        When an argument is not ``name=number``.
    """
    parsed: dict[str, float] = {}
    for item in values or ():
        name, sep, number = item.partition("=")
        if not sep or not name:
            raise ValueError(f"planner parameter {item!r} is not name=value")
        parsed[name.strip()] = float(number)
    return modelplan.params_of(parsed)


def options_from(args: Any) -> EvalOptions:
    """Return the options of the command line arguments."""
    base = EvalOptions.quick(args.planner) if args.quick else EvalOptions(planner=args.planner)
    options = replace(base, params=parse_params(args.param), workers=args.workers)
    if args.replicas is not None:
        options = replace(
            options, replicas=args.replicas, max_replicas=max(args.replicas, options.max_replicas)
        )
    if args.max_replicas is not None:
        options = replace(options, max_replicas=max(args.max_replicas, options.replicas))
    if args.days is not None:
        options = replace(options, days=args.days)
    if args.seed is not None:
        options = replace(options, seed=args.seed)
    if args.scenarios:
        options = replace(options, scenarios=tuple(args.scenarios))
    if args.models:
        options = replace(options, models=tuple(args.models))
    if args.sweep_replicas is not None:
        options = replace(options, sweep_replicas=args.sweep_replicas)
    return options


def run(args: Any) -> int:
    """Run the ``model-plan`` command: exit status 0 only when the planner is unlocked."""
    options = options_from(args)
    started = time.monotonic()

    def log(message: str) -> None:
        print(message, file=sys.stderr)

    if args.sweep:
        sw = sweep(options, log)
        write_sweep(sw, args.out)
        print(render_sweep(sw))
        print(
            f"total runtime {time.monotonic() - started:.0f} s ({sw.runs} runs); wrote {args.out}"
        )
        return 0
    ev = evaluate(options, log)
    write_outputs(ev, args.out)
    print(render_markdown(ev))
    print(f"total runtime {time.monotonic() - started:.0f} s ({ev.runs} runs); wrote {args.out}")
    return 0 if ev.verdict.unlocked else 1
