"""Golden decision log: the deterministic simulations' decision streams, for byte comparison.

A refactor that must not change behaviour regenerates these streams and diffs them
against the committed ones. A stream holds, in the order the service produced them:

- every decision: the whole :class:`~ovenbird_core.control.DecisionRecord` (instant,
  mode, ladder, reason, terms with units and notes, ``pre_round``, setpoint, binding,
  flip distance and input, the inputs used, the complete controller state after the
  tick (integrator, ``frozen_by``, held integrator, wood-stove carry, cross-check,
  dwell and ramp state, ...), intents, actor) plus the arbiter's decisions, the
  tick's command events and the configuration version;
- every command event, alarm transition (raised, cleared, hold started, expired,
  released, journal events) and persisted state row (the controller state and the
  manual request as the state sink saves them).

Nothing that varies between runs is kept (no wall-clock time of the machine, ids or
durations); floats are rounded to six decimals. Every stream is gzipped (without a
timestamp) to keep the directory small:

``fullrun.jsonl.gz``
    The harness full-run on the example house and the synthetic cold week.
``sweep/<scenario>.jsonl.gz``
    Each fault scenario alone.
``drills/<drill>.jsonl.gz``
    Each golden drill alone (:mod:`ovenbird_harness.drills`: a defrost and a DHW run
    holding the setpoint, a manual setpoint and a boost, a latched hold across a
    restart and its release, a go-live restore).
These streams are synthetic (the example house, the synthetic cold week and the
modelled room sensor) and committed under ``packages/harness/tests/golden``.

Streams on recorded data are never committed. They live next to the local captures
(``$CAPTURES_DIR``, default ``capture/captures``, git-ignored) under ``golden-real``:

``golden-real/openloop.jsonl.gz``
    The open-loop run over one recorded day (``OPENLOOP_DAY`` of the local settings,
    :mod:`ovenbird_sim.local`, else the first full day) with the install profile of the
    local settings.

They are written and checked only when the recorded capture is present; without it
(CI, a fresh clone) they are skipped and the run says so. With the capture present a
open-loop run without decisions, or a missing ``golden-real`` stream on ``check``, is an
error.

Examples
--------
Regenerate the streams, or check that nothing changed::

    uv run python -m ovenbird_harness.golden write
    uv run python -m ovenbird_harness.golden check
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import logging
import multiprocessing
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

from ovenbird.history.journal import AlarmRow, CommandRow, DecisionRow, StateRow
from ovenbird_harness.drills import DRILLS, Drill
from ovenbird_harness.faults import SCENARIOS, TAIL_S
from ovenbird_harness.fullrun import FullRun, RunConfig
from ovenbird_harness.sweep import default_jobs, plan
from ovenbird_harness.testing import REFERENCE_START, reference_config
from ovenbird_sim import local

GOLDEN_DIR: Final = Path("packages/harness/tests/golden")
CAPTURES_ENV: Final = "CAPTURES_DIR"
CAPTURES: Final = Path("capture/captures")
REAL_DIR: Final = "golden-real"
FULLRUN_FILE: Final = "fullrun.jsonl.gz"
OPENLOOP_FILE: Final = "openloop.jsonl.gz"
SWEEP_DIR: Final = "sweep"
DRILL_DIR: Final = "drills"
FULLRUN_HOURS: Final = 24.0
SWEEP_AT: Final = REFERENCE_START + timedelta(hours=30)
SWEEP_WARMUP_S: Final = 2 * 3600.0
OPENLOOP_ARGUMENTS: Final = (
    "--room auto --room-max-age 1800 --comfort {comfort} "
    "--min-setpoint {min_setpoint} --pump-duty --pump-duty-heat {heat} --pump-duty-idle {idle} "
    "--emitter mixed --no-inputs"
)
SHOWN_DIFFERENCES: Final = 5
DIGITS: Final = 6
CONTEXT: Final = 80


def stable(value: Any) -> Any:
    """Return ``value`` with floats rounded and negative zero removed, recursively."""
    if isinstance(value, float):
        return round(value, DIGITS) + 0.0
    if isinstance(value, dict):
        return {key: stable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [stable(item) for item in value]
    return value


def dump(value: Any) -> str:
    """Return one canonical JSON line."""
    return json.dumps(
        stable(value), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


class GoldenError(RuntimeError):
    """A stream that should have been produced is missing or empty."""


def decision_line(record: dict[str, Any], **extra: Any) -> str:
    """Return the golden line of one decision record (``DecisionRecord.to_json_dict`` form)."""
    return dump({"kind": "decision", **record, **extra})


def journal_decision(row: DecisionRow) -> str:
    """Return the golden line of a journalled decision."""
    return decision_line(
        json.loads(row.record),
        ts=row.ts,
        arbiter=json.loads(row.arbiter),
        commands=json.loads(row.commands),
        config_version=row.config_version,
    )


def journal_command(row: CommandRow) -> str:
    """Return the golden line of a journalled command event."""
    return dump(
        {
            "kind": "command",
            "ts": row.ts,
            "command": row.kind,
            "value": row.value,
            "status": row.status,
            "attempt": row.attempt,
            "topic": row.topic,
            "payload": row.payload,
            "detail": row.detail,
        }
    )


def journal_alarm(row: AlarmRow) -> str:
    """Return the golden line of a journalled alarm transition or event."""
    return dump(
        {
            "kind": "alarm",
            "ts": row.ts,
            "code": row.code,
            "severity": row.severity,
            "event": row.event,
            "message": row.message,
            "detail": json.loads(row.detail) if row.detail else None,
        }
    )


def persisted_state(row: StateRow) -> str:
    """Return the golden line of a row the state sink saved."""
    return dump({"kind": "state", "key": row.key, "ts": row.ts, "value": json.loads(row.value)})


def stream_of(config: RunConfig, drill: str | None = None) -> list[str]:
    """Run ``config`` (with the golden drill ``drill``) and return its golden lines.

    A header, then every decision, command event, alarm transition and persisted
    state row in the order the service produced them.
    """
    run = FullRun(config)
    lines: list[str] = []
    run.on_decision.append(lambda row: lines.append(journal_decision(row)))
    run.on_command.append(lambda row: lines.append(journal_command(row)))
    run.on_alarm.append(lambda row: lines.append(journal_alarm(row)))
    run.on_state.append(lambda row: lines.append(persisted_state(row)))
    scenario = None if drill is None else attach_drill(run, drill)
    result = run.run()
    summary = result.summary
    outcomes = summary["faults"] if scenario is None else [scenario.outcome(run)]
    header = dump(
        {
            "kind": "run",
            "from": config.start.isoformat(),
            "to": config.end.isoformat(),
            "faults": [list(pair) for pair in config.faults],
            "drill": drill,
            "passed": result.passed,
            "outcomes": outcomes,
            "violations": summary["invariants"]["by_rule"],
            "decisions": summary["kpis"]["decisions"],
        }
    )
    return [header, *lines]


def attach_drill(run: FullRun, name: str) -> Drill:
    """Start the drill ``name`` at :data:`SWEEP_AT` in ``run``; its actions run every cycle."""
    scenario = DRILLS[name]()
    scenario.start = SWEEP_AT.timestamp()
    scenario.attach(run)
    run.on_cycle.append(lambda t: scenario.before(run, t))
    return scenario


def drill_config(work: Path, name: str) -> RunConfig:
    """Return the run of drill ``name`` alone: the sweep's warm-up, its window and a tail."""
    window = DRILLS[name]().window_s
    start = SWEEP_AT - timedelta(seconds=SWEEP_WARMUP_S)
    end = SWEEP_AT + timedelta(seconds=window + TAIL_S)
    return reference_config(work / DRILL_DIR / name, 0.0, start=start, end=end)


def _drill_stream(name: str, work: Path) -> list[str]:
    """Return the stream of the single-drill run ``name``."""
    return stream_of(drill_config(work, name), name)


def _quiet() -> None:
    """Silence logging below critical level (worker process initialiser)."""
    logging.basicConfig(level="CRITICAL")


def fullrun_lines(work: Path) -> list[str]:
    """Return the full-run stream."""
    return stream_of(reference_config(work / "fullrun", FULLRUN_HOURS))


def sweep_streams(work: Path, jobs: int) -> dict[str, list[str]]:
    """Return the stream of every fault scenario and every drill alone, by file name."""
    base = reference_config(work / "sweep", 48.0)
    runs = plan(
        base, tuple(SCENARIOS), 0, work / "sweep", dates=[SWEEP_AT], warmup_s=SWEEP_WARMUP_S
    )
    configs = [replace(config, progress=False) for _, _, config in runs]
    names = [f"{SWEEP_DIR}/{name}.jsonl.gz" for name, _, _ in runs]
    drills = list(DRILLS)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=jobs, mp_context=context, initializer=_quiet) as pool:
        drilled = pool.map(_drill_stream, drills, [work] * len(drills))
        streams = list(pool.map(stream_of, configs))
        streams += list(drilled)
    names += [f"{DRILL_DIR}/{name}.jsonl.gz" for name in drills]
    return dict(zip(names, streams, strict=True))


def openloop_day(captures: Path) -> str:
    """Return the open-loop day: the local ``OPENLOOP_DAY``, else the first full recorded day."""
    configured = local.value("OPENLOOP_DAY", "")
    if configured:
        return configured
    days = sorted(p.name.split(".", 1)[0] for p in (captures / "live").glob("*.jsonl*"))
    if len(days) < 2:
        raise GoldenError(f"no full recorded day in {captures / 'live'}; set OPENLOOP_DAY locally")
    return days[1]


def openloop_arguments() -> list[str]:
    """Return the open-loop run's profile arguments: the local install profile, else the example."""
    text = OPENLOOP_ARGUMENTS.format(
        comfort=local.value("COMFORT_C", str(local.EXAMPLE_COMFORT_C)),
        min_setpoint=local.value("MIN_SETPOINT_C", str(local.EXAMPLE_MIN_SETPOINT_C)),
        heat=local.value("PUMP_DUTY_HEAT", str(local.EXAMPLE_PUMP_DUTY_HEAT)),
        idle=local.value("PUMP_DUTY_IDLE", str(local.EXAMPLE_PUMP_DUTY_IDLE)),
    )
    return text.split()


def openloop_lines(captures: Path, work: Path) -> list[str]:
    """Return the open-loop run stream over one recorded day.

    Raises
    ------
    GoldenError
        When the open-loop run fails or produces no decisions.
    """
    from ovenbird_sim.evaluate.__main__ import main as evaluate

    out = work / "openloop"
    day = openloop_day(captures)
    argv = [
        "open-loop",
        "--capture",
        str(captures / "live"),
        "--datalake",
        str(captures / "datalake"),
        "--from",
        day,
        "--to",
        day,
        "--out",
        str(out),
        *openloop_arguments(),
    ]
    with contextlib.redirect_stdout(io.StringIO()):
        code = evaluate(argv)
    result = out / "openloop.sqlite"
    if code != 0 or not result.is_file():
        raise GoldenError(f"the open-loop run exited with {code} and wrote no {result.name}")
    with sqlite3.connect(result) as db:
        rows = db.execute("SELECT record FROM decisions ORDER BY tick").fetchall()
    if not rows:
        raise GoldenError(
            f"the open-loop run over {day} produced no decisions although the recorded "
            f"capture is present at {captures / 'live'}"
        )
    return [
        dump({"kind": "run", "day": day, "decisions": len(rows)}),
        *(decision_line(json.loads(text)) for (text,) in rows),
    ]


def write_lines(path: Path, lines: Sequence[str]) -> None:
    """Write ``lines`` to ``path``, gzipped (without a timestamp) when it ends in ``.gz``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ("\n".join(lines) + "\n").encode()
    if path.suffix == ".gz":
        with path.open("wb") as raw, gzip.GzipFile("", "wb", 9, raw, mtime=0) as packed:
            packed.write(data)
    else:
        path.write_bytes(data)


def read_lines(path: Path) -> list[str]:
    """Read the lines of a golden file (gzipped when it ends in ``.gz``)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return handle.read().splitlines()


def default_captures() -> Path:
    """Return the local captures directory: ``$CAPTURES_DIR`` or ``capture/captures``."""
    configured = os.environ.get(CAPTURES_ENV)
    return Path(configured) if configured else CAPTURES


def has_recorded(captures: Path) -> bool:
    """Whether the recorded capture the real-data streams need is present."""
    return (captures / "live").is_dir()


def openloop_skipped(captures: Path) -> str:
    """Return the line printed when the real-data streams are skipped for lack of a capture."""
    return (
        f"golden: real-data streams SKIPPED (open-loop run), no recorded capture at "
        f"{captures / 'live'} (expected in CI and in a fresh clone); "
        "the synthetic full-run, fault sweep and drill streams are checked"
    )


def real_checked(captures: Path) -> str:
    """Return the line printed when the real-data streams were produced locally."""
    return (
        f"golden: real-data streams included (open-loop run), kept locally in "
        f"{captures / REAL_DIR} and never committed"
    )


def generate(out: Path, real: Path, captures: Path, jobs: int) -> list[str]:
    """Write the synthetic streams under ``out`` and the real-data ones under ``real``.

    Returns the notes on what was skipped or included.

    Parameters
    ----------
    out
        Directory receiving the synthetic (committed) streams.
    real
        Directory receiving the real-data streams, kept locally.
    captures
        Directory of the local recorded captures.
    jobs
        Number of worker processes for the drill sweep.

    Returns
    -------
    list[str]
        Notes on which streams were skipped or included.

    Raises
    ------
    GoldenError
        When the recorded capture is present but the open-loop run produced nothing.
    """
    notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="golden-work-") as scratch:
        work = Path(scratch)
        write_lines(out / FULLRUN_FILE, fullrun_lines(work))
        for name, lines in sweep_streams(work, jobs).items():
            write_lines(out / name, lines)
        if has_recorded(captures):
            write_lines(real / OPENLOOP_FILE, openloop_lines(captures, work))
            notes.append(real_checked(captures))
        else:
            notes.append(openloop_skipped(captures))
    return notes


def golden_files(root: Path) -> list[str]:
    """Return the golden files under ``root`` as sorted relative names."""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def excerpt(line: str, other: str) -> str:
    """Return the part of ``line`` around its first difference from ``other``."""
    first = next((i for i, (a, b) in enumerate(zip(line, other, strict=False)) if a != b), 0)
    start = max(0, first - CONTEXT)
    return f"...{line[start : first + CONTEXT]}..." if start else line[: 2 * CONTEXT]


def differences(golden: Path, fresh: Path, skipped: Sequence[str] = ()) -> list[str]:
    """Return a short summary of how ``fresh`` differs from ``golden``.

    Parameters
    ----------
    golden
        Directory of the committed streams.
    fresh
        Directory of the freshly produced streams.
    skipped
        Names that may be missing from ``fresh`` without counting as a difference.

    Returns
    -------
    list[str]
        Summary lines, empty when the trees are identical.
    """
    found: list[str] = []
    have = golden_files(golden) if golden.is_dir() else []
    want = golden_files(fresh) if fresh.is_dir() else []
    for name in sorted(set(have) - set(want)):
        if name not in skipped:
            found.append(f"{name}: committed but not produced")
    for name in sorted(set(want) - set(have)):
        found.append(f"{name}: produced but not committed")
    for name in sorted(set(have) & set(want)):
        old, new = read_lines(golden / name), read_lines(fresh / name)
        if old == new:
            continue
        changed = [i for i in range(min(len(old), len(new))) if old[i] != new[i]]
        found.append(
            f"{name}: {len(changed)} lines differ, {len(old)} committed vs {len(new)} produced"
        )
        for index in changed[:SHOWN_DIFFERENCES]:
            found.append(f"  line {index + 1}:\n    - {excerpt(old[index], new[index])}")
            found.append(f"    + {excerpt(new[index], old[index])}")
    return found


def replace_tree(target: Path, fresh: Path) -> None:
    """Make ``target`` hold exactly the files of ``fresh`` (stale files are removed)."""
    produced = set(golden_files(fresh))
    target.mkdir(parents=True, exist_ok=True)
    for name in golden_files(target):
        if name not in produced:
            (target / name).unlink()
    for name in sorted(produced):
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fresh / name, destination)


def write(golden: Path, captures: Path, jobs: int) -> int:
    """Regenerate the committed synthetic streams, and the local real-data ones when possible.

    Files of an earlier layout that are no longer produced are removed.
    """
    real = captures / REAL_DIR
    with tempfile.TemporaryDirectory(prefix="golden-out-") as scratch:
        fresh = Path(scratch) / "synthetic"
        fresh_real = Path(scratch) / "real"
        notes = generate(fresh, fresh_real, captures, jobs)
        replace_tree(golden, fresh)
        if has_recorded(captures):
            replace_tree(real, fresh_real)
    total = sum(path.stat().st_size for path in golden.rglob("*") if path.is_file())
    for note in notes:
        print(note)
    print(f"wrote {golden} ({total / 1e6:.2f} MB)")
    if has_recorded(captures):
        print(f"wrote {real} (local only)")
    return 0


def check(golden: Path, captures: Path, jobs: int) -> int:
    """Regenerate into a temporary directory and diff against ``golden`` (and ``golden-real``).

    Parameters
    ----------
    golden
        Directory of the committed streams.
    captures
        Directory of the local recorded captures.
    jobs
        Number of worker processes for the drill sweep.

    Returns
    -------
    int
        Exit code: 0 when identical, 1 when they differ.
    """
    real = captures / REAL_DIR
    with tempfile.TemporaryDirectory(prefix="golden-check-") as scratch:
        fresh = Path(scratch) / "synthetic"
        fresh_real = Path(scratch) / "real"
        notes = generate(fresh, fresh_real, captures, jobs)
        found = differences(golden, fresh)
        if has_recorded(captures):
            found += [f"{REAL_DIR}/{line}" for line in differences(real, fresh_real)]
    for note in notes:
        print(note)
    if found:
        print("golden decision log differs:")
        print("\n".join(found))
        if has_recorded(captures) and not (real / OPENLOOP_FILE).is_file():
            print(f"the real-data streams are not recorded yet: run make golden to write {real}")
        return 1
    print("golden decision log is identical")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command line parser."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_harness.golden", description=__doc__)
    parser.add_argument("action", choices=("write", "check"))
    parser.add_argument("--golden", type=Path, default=GOLDEN_DIR)
    parser.add_argument(
        "--captures",
        type=Path,
        default=None,
        help=f"local captures (default ${CAPTURES_ENV} or {CAPTURES})",
    )
    parser.add_argument("--jobs", type=int, default=None, help="sweep worker processes")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line; ``check`` exits 1 when the streams differ."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level="CRITICAL")
    jobs = args.jobs or default_jobs()
    action = write if args.action == "write" else check
    try:
        return action(args.golden, args.captures or default_captures(), jobs)
    except GoldenError as exc:
        print(f"golden: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
