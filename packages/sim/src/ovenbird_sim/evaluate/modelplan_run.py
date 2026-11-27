"""``python -m ovenbird_sim.evaluate model-plan``: the offline evaluation of the model plan.

Runs the paired grid (scenario x model variant x forecast variant, see
:mod:`ovenbird_sim.evaluate.modelplan`), applies the gate, optionally sweeps planner
settings, and writes ``model_plan.json`` and ``model_plan_tables.md`` to the output
directory.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from ovenbird_sim.evaluate import meta, modelplan
from ovenbird_sim.evaluate.modelplan import (
    CORRECT,
    DEFAULT_DAYS,
    DEFAULT_SEEDS,
    NOISY,
    PERFECT,
    SCENARIOS,
    Cell,
    PlanSettings,
    SweepLine,
)
from ovenbird_sim.evaluate.plangate import RunKpis, format_row_table

QUICK_SCENARIOS: Final = ("sunny_cold", "missing_sun")
QUICK_MODELS: Final = (CORRECT, "aperture_x2")
QUICK_DAYS: Final = 3
SWEEP_SEEDS: Final = 1
JITTERS_K: Final = (-0.1, -0.05, 0.05, 0.1)
FLOOR_KPIS: Final = ("below_kh", "below_band_kh", "above_kh", "starts_per_day")

Log = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class EvalOptions:
    """Options of the evaluation.

    Parameters
    ----------
    days
        Simulated days per run (the first is dropped from the KPIs).
    seeds
        Seeds of the noisy forecast variant (the perfect forecast uses one).
    workers
        Worker processes (``None``: the CPU count).
    scenarios, models, forecasts
        The grid.
    sweep
        Also run the planner-setting sweep.
    sweep_seeds
        Seeds of the noisy forecast in the sweep.
    """

    days: int = DEFAULT_DAYS
    seeds: int = DEFAULT_SEEDS
    workers: int | None = None
    scenarios: tuple[str, ...] = tuple(SCENARIOS)
    models: tuple[str, ...] = tuple(modelplan.MODEL_VARIANTS)
    forecasts: tuple[str, ...] = (PERFECT, NOISY)
    sweep: bool = True
    sweep_seeds: int = SWEEP_SEEDS

    @classmethod
    def quick(cls) -> EvalOptions:
        """Return the small subset used by the tests."""
        return cls(
            days=QUICK_DAYS,
            seeds=1,
            scenarios=QUICK_SCENARIOS,
            models=QUICK_MODELS,
            forecasts=(PERFECT,),
            sweep=False,
        )


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Result of an evaluation.

    Parameters
    ----------
    options
        What was run.
    cells
        Gate cells of the default settings.
    sweep
        Sweep lines (empty without a sweep).
    verified
        Sweep lines of the passing settings re-run with the full seed count.
    runtime_s
        Wall time.
    runs
        Number of simulations.
    sensitivity_floor
        Per scenario and KPI the (minimum, maximum) of the runs without the planner when
        the true outside temperature is shifted by up to 0.1 K: how far two runs differ
        when the weather is the same for every practical purpose.
    """

    options: EvalOptions
    cells: tuple[Cell, ...]
    sweep: tuple[SweepLine, ...]
    verified: tuple[SweepLine, ...]
    runtime_s: float
    runs: int
    sensitivity_floor: Mapping[str, Mapping[str, tuple[float, float]]]


def _progress(log: Log, label: str) -> Callable[[int, int], None]:
    def report(done: int, total: int) -> None:
        if done == total or done % 25 == 0:
            log(f"{label}: {done}/{total} runs")

    return report


def evaluate(options: EvalOptions, log: Log = lambda _message: None) -> Evaluation:
    """Run the grid, the gate and the sweep.

    Parameters
    ----------
    options
        What to run.
    log
        Progress sink.

    Returns
    -------
    Evaluation
        Cells, sweep lines and the runtime.
    """
    started = time.monotonic()
    cache: dict[tuple[Any, ...], RunKpis] = {}
    specs = modelplan.grid(
        options.scenarios, options.models, options.forecasts, options.seeds, options.days
    )
    results = modelplan.run_all(specs, options.workers, _progress(log, "grid"), cache)
    cache.update(results)
    cells = modelplan.collect(
        results, options.scenarios, options.models, options.forecasts, options.seeds, options.days
    )
    lines: list[SweepLine] = []
    verified: list[SweepLine] = []
    if options.sweep:
        for settings in modelplan.sweep_settings():
            lines.append(_sweep_one(options, settings, options.sweep_seeds, log, cache))
        for line in lines:
            if not line.failing and line.above_gain_kh > 0.0:
                verified.append(_sweep_one(options, line.settings, options.seeds, log, cache))
    return Evaluation(
        options,
        tuple(cells),
        tuple(lines),
        tuple(verified),
        time.monotonic() - started,
        len(cache),
        _sensitivity_floor(options, cache),
    )


def _sensitivity_floor(
    options: EvalOptions, cache: dict[tuple[Any, ...], RunKpis]
) -> dict[str, dict[str, tuple[float, float]]]:
    specs = [
        modelplan.RunSpec(scenario, 0, options.days, jitter_k=jitter)
        for scenario in options.scenarios
        for jitter in (0.0, *JITTERS_K)
    ]
    results = modelplan.run_all(specs, options.workers, None, cache)
    cache.update(results)
    floor: dict[str, dict[str, tuple[float, float]]] = {}
    for scenario in options.scenarios:
        rows = [results[s.key].row for s in specs if s.scenario == scenario]
        floor[scenario] = {
            name: (min(r[name] for r in rows), max(r[name] for r in rows)) for name in FLOOR_KPIS
        }
    return floor


def _sweep_one(
    options: EvalOptions,
    settings: PlanSettings,
    seeds: int,
    log: Log,
    cache: dict[tuple[Any, ...], RunKpis],
) -> SweepLine:
    specs = modelplan.grid(
        options.scenarios, options.models, options.forecasts, seeds, options.days, settings
    )
    results = modelplan.run_all(specs, options.workers, None, cache)
    cache.update(results)
    cells = modelplan.collect(
        results, options.scenarios, options.models, options.forecasts, seeds, options.days, settings
    )
    line = modelplan.sweep_line(settings, cells)
    log(f"sweep {settings.label}: {len(line.failing)} failing of {line.cells}")
    return line


def failing_cells(cells: Sequence[Cell]) -> list[Cell]:
    """Return the cells that fail the gate."""
    return [c for c in cells if not c.verdict.passed]


def _cell_text(cell: Cell) -> str:
    failed = [f"{c.name} {c.detail}" for c in cell.verdict.checks if not c.passed]
    return f"{cell.scenario} / {cell.model} / {cell.forecast}: " + "; ".join(failed)


def render_markdown(ev: Evaluation) -> str:
    """Return the evaluation as Markdown tables (gate summary, scenarios, sweep)."""
    failing = failing_cells(ev.cells)
    parts = [
        f"## Gate verdict\n\n{len(ev.cells) - len(failing)} of {len(ev.cells)} cells pass, "
        f"{len(failing)} fail.\n"
    ]
    if failing:
        parts.append("Failing cells:\n\n" + "\n".join(f"- {_cell_text(c)}" for c in failing) + "\n")
    for scenario in ev.options.scenarios:
        lines = [
            (
                f"{c.model}, {c.forecast}"
                + (f" ({c.seeds_failing}/{c.seeds} seeds fail)" if c.seeds_failing else ""),
                c.without,
                c.with_plan,
                c.verdict,
            )
            for c in ev.cells
            if c.scenario == scenario
        ]
        parts.append(format_row_table(scenario, lines))
    parts.append(_headline_table(ev.cells))
    parts.append(_floor_table(ev))
    if ev.sweep:
        parts.append(_sweep_table(ev))
    return "\n".join(parts)


def _headline_table(cells: Sequence[Cell]) -> str:
    rows = [c for c in cells if modelplan.benefit_required(c.scenario, c.model)]
    if not rows:
        return ""
    out = [
        "### Benefit with the correct model (95 % day-block bootstrap of the change, Kh)\n",
        "| scenario | forecast | above 21.5 °C | below 21 °C | below 20.5 °C |",
        "|---|---|---|---|---|",
    ]
    for c in rows:
        cols = []
        for name, key in (
            ("above_kh", "above_kh"),
            ("below_kh", "below_kh"),
            ("below_band_kh", "below_band_kh"),
        ):
            low, high = c.intervals[key]
            change = c.with_plan[name] - c.without[name]
            cols.append(f"{change:+.2f} [{low:+.2f}, {high:+.2f}]")
        out.append(f"| {c.scenario} | {c.forecast} | " + " | ".join(cols) + " |")
    return "\n".join(out) + "\n"


def _floor_table(ev: Evaluation) -> str:
    out = [
        "### Sensitivity floor: runs without the planner, outside temperature shifted by "
        f"{', '.join(f'{j:+g}' for j in JITTERS_K)} K\n",
        "Range (minimum to maximum) of the baseline KPIs over those runs and the unshifted "
        "run. The loop rounds its setpoint to whole kelvin, so a change of the same size with "
        "the planner is not distinguishable from this.\n",
        "| scenario | below 21 °C (Kh) | below 20.5 °C (Kh) | above 21.5 °C (Kh) | starts/day |",
        "|---|---|---|---|---|",
    ]
    for scenario, kpis in ev.sensitivity_floor.items():
        cols = [f"{kpis[n][0]:.2f} to {kpis[n][1]:.2f}" for n in FLOOR_KPIS]
        out.append(f"| {scenario} | " + " | ".join(cols) + " |")
    return "\n".join(out) + "\n"


def _sweep_table(ev: Evaluation) -> str:
    out = [
        "### Planner setting sweep\n",
        f"Every setting over the same grid ({len(ev.options.scenarios)} scenarios x "
        f"{len(ev.options.models)} models, perfect and {ev.options.sweep_seeds} noisy seed). "
        "Benefit: reduction of Kh above the band, sunny scenarios, correct model, perfect "
        "forecast. Below: change of Kh below comfort over the same cells.\n",
        "| setting | failing cells | above reduced (Kh) | below change (Kh) |",
        "|---|---|---|---|",
    ]
    for line in ev.sweep:
        out.append(
            f"| {line.settings.label} | {len(line.failing)} of {line.cells} "
            f"| {line.above_gain_kh:+.2f} | {line.below_change_kh:+.2f} |"
        )
    if ev.verified:
        out.append("\nSettings that pass every cell, re-run with the full seed count:\n")
        for line in ev.verified:
            status = "pass" if not line.failing else f"FAIL ({len(line.failing)} cells)"
            out.append(
                f"- {line.settings.label}: {status}; above reduced {line.above_gain_kh:+.2f} Kh, "
                f"below change {line.below_change_kh:+.2f} Kh"
            )
    else:
        out.append("\nNo tested setting passes every cell with a benefit left.")
    out.append("\nFailing cells per sweep setting:\n")
    for line in ev.sweep:
        if line.failing:
            out.append(f"- {line.settings.label}: " + "; ".join(line.failing))
    return "\n".join(out) + "\n"


def to_json(ev: Evaluation) -> dict[str, Any]:
    """Return the evaluation as a JSON-ready dictionary."""
    return {
        "options": {
            "days": ev.options.days,
            "seeds": ev.options.seeds,
            "scenarios": list(ev.options.scenarios),
            "models": list(ev.options.models),
            "forecasts": list(ev.options.forecasts),
            "sweep_seeds": ev.options.sweep_seeds,
        },
        "git": meta.git_commit(),
        "runtime_s": ev.runtime_s,
        "runs": ev.runs,
        "sensitivity_floor": {
            k: {n: list(v) for n, v in d.items()} for k, d in ev.sensitivity_floor.items()
        },
        "passed": all(c.verdict.passed for c in ev.cells),
        "cells": modelplan.cells_to_json(ev.cells),
        "sweep": [_line_json(line) for line in ev.sweep],
        "verified": [_line_json(line) for line in ev.verified],
    }


def _line_json(line: SweepLine) -> dict[str, Any]:
    return {
        "settings": {
            "gain": line.settings.gain,
            "max_setback_k": line.settings.max_setback_k,
            "max_preheat_k": line.settings.max_preheat_k,
            "dead_zone_k": line.settings.dead_zone_k,
        },
        "cells": line.cells,
        "failing": list(line.failing),
        "above_gain_kh": line.above_gain_kh,
        "below_change_kh": line.below_change_kh,
    }


def write_outputs(ev: Evaluation, out: Path) -> None:
    """Write ``model_plan.json`` and ``model_plan_tables.md`` into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_plan.json").write_text(json.dumps(to_json(ev), indent=2, sort_keys=True) + "\n")
    (out / "model_plan_tables.md").write_text(render_markdown(ev))


def run(args: Any) -> int:
    """Run the ``model-plan`` command: exit status 1 when a gate cell fails."""
    options = EvalOptions.quick() if args.quick else EvalOptions()
    options = replace(
        options,
        days=args.days if args.days is not None else options.days,
        seeds=args.seeds if args.seeds is not None else options.seeds,
        workers=args.workers,
        sweep=options.sweep and not args.no_sweep,
    )
    ev = evaluate(options, lambda message: print(message, file=sys.stderr))
    write_outputs(ev, args.out)
    print(render_markdown(ev))
    print(f"runtime {ev.runtime_s:.0f} s ({ev.runs} runs); wrote {args.out}")
    return 0 if all(c.verdict.passed for c in ev.cells) else 1
