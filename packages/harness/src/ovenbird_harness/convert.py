"""Convert a recorded capture period into an ovenbird ``history.db`` (one-off tool).

The result lets a local ovenbird (the dev stack or ``python -m ovenbird``) pointed at the
output directory show the recording in System -> Replay. Everything is written with the
service's own code, on the schema and migrations it ships:

- **Samples and rollups**: every recorded reading becomes a sample the way the service's
  runtime does it (:func:`ovenbird.history.database.sample_from_reading`, a gap sample for
  an invalidating error, the derived loop heat after a heat input), written with
  :meth:`~ovenbird.history.database.HistoryDatabase.write_batch`, which also maintains the
  1 min, 15 min and 1 h rollups. The room readings (Datalake and mirror) are stored under
  the configured room signal.
- **Decisions**: ovenbird's controller, built from the configuration seed, driven over the
  recording exactly like the open-loop run (:func:`ovenbird_sim.evaluate.openloop.drive`:
  same stream, room resolution and staleness policy). One decision row per tick with the
  record JSON as the service stores it.
- **Commands**: the ``SetCurves`` and ``SetMaxPumpDuty`` messages of the capture, sent by
  the controller that ran then, as ``command`` rows with the status ``recorded``. They are
  neither ``sent`` nor ``verified``, so nothing counts them as ovenbird's own writes.

Open loop: the recorded plant followed whatever controlled it at the time; the decisions
show what ovenbird would have decided on those inputs, not what it would have caused.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sqlite3
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from ovenbird.config import DATA_DIR_ENV, DEFAULT_DATA_DIR, ConfigError, Settings
from ovenbird.configstore import read_seed
from ovenbird.configstore.effective import MergedSettings, merge, storable
from ovenbird.history.database import (
    HEAT_INPUTS,
    HistoryDatabase,
    Sample,
    gap_sample,
    heat_sample,
    sample_from_reading,
)
from ovenbird.history.journal import CommandRow, DecisionRow, write_journal
from ovenbird.history.packing import DecisionPacker
from ovenbird.history.schema import open_history
from ovenbird_core.capture import CaptureRecord, capture_input
from ovenbird_core.control import (
    ControlInputs,
    OvenbirdConfig,
    OvenbirdController,
    OvenbirdState,
    StepResult,
)
from ovenbird_core.control.types import IntentKind, RoomInput
from ovenbird_core.heishamon import MqttMessage
from ovenbird_core.inputs import HA_SIGNAL_PREFIX, InputRouter, MqttSignal
from ovenbird_core.readings import ParseError, Reading, SignalId
from ovenbird_core.store import StateStore
from ovenbird_sim.evaluate.openloop import (
    OpenLoopOptions,
    Tick,
    drive,
    recorded_stream,
    staleness_policy,
    stove_reference,
)
from ovenbird_sim.evaluate.recorded import (
    DATALAKE_SIGNAL,
    MIRROR_SIGNAL,
    MIRROR_TOPIC,
    ROOM_RANGE_C,
    SETCURVES_TOPIC,
    SETDUTY_TOPIC,
    RoomSource,
    StreamItem,
    setcurves_target,
)

HISTORY_NAME: Final = "history.db"
SEED_NAME: Final = "config-seed.json"
RECORDED_STATUS: Final = "recorded"
RECORDED_DETAIL: Final = "recorded from the capture: sent by the controller that ran then"
DAY_S: Final = 86_400
TICK_S: Final = 60.0
FLUSH_SAMPLES: Final = 20_000
COMPACT: Final = (",", ":")
STUB_HA_URL: Final = "http://conversion.invalid"
STUB_HA_TOKEN: Final = "conversion"  # noqa: S105
STUB_TOPIC_BASE: Final = "conversion/"
STUB_RANGE: Final = (-1000.0, 100_000.0)
FOREVER_ENV: Final = (
    "OVENBIRD_HISTORY_RAW_DAYS=0",
    "OVENBIRD_HISTORY_1M_DAYS=0",
    "OVENBIRD_HISTORY_15M_DAYS=0",
    "OVENBIRD_HISTORY_1H_DAYS=0",
    "OVENBIRD_HISTORY_DECISION_DAYS=0",
)


class ConvertError(Exception):
    """The conversion cannot run as asked (bad output path, existing database, bad seed)."""


@dataclass(frozen=True, slots=True)
class ConvertOptions:
    """What to convert and how.

    Parameters
    ----------
    capture
        Capture directory (or one day file).
    out
        Output directory; ``history.db`` and ``config-seed.json`` are written there.
    start, end
        First and last day (UTC, inclusive).
    datalake
        Datalake root for the room sensor.
    config
        Configuration seed (``OVENBIRD_CONFIG_SEED`` format) on top of the default
        settings; ``None`` runs the defaults.
    room
        Room input source of the open-loop run.
    room_max_age_s
        Maximum age of the recorded room signals (the open-loop run's staleness policy).
        ``None`` takes the seed's room profile limit, as the live service does.
    config_version
        Configuration version stored with every decision. ``None`` is the version
        before the configuration store existed; a local instance started with the seed
        runs version 1, and the Replay identity check only compares decisions of the
        active version.
    force
        Replace an existing non-empty ``history.db``.
    """

    capture: Path
    out: Path
    start: date
    end: date
    datalake: Path | None = None
    config: Path | None = None
    room: RoomSource = RoomSource.AUTO
    room_max_age_s: float | None = None
    config_version: int | None = None
    force: bool = False


@dataclass(slots=True)
class DayStats:
    """Work of one recorded day.

    Parameters
    ----------
    day
        UTC day.
    seconds
        Wall-clock seconds spent on its ticks (and the samples read meanwhile).
    ticks, samples, commands
        Decision rows, raw samples and command rows written.
    """

    day: date
    seconds: float = 0.0
    ticks: int = 0
    samples: int = 0
    commands: int = 0


@dataclass(slots=True)
class ConvertResult:
    """Outcome of a conversion.

    Parameters
    ----------
    history_path, seed_path
        Files written.
    days
        Per-day statistics, in order.
    decisions, commands, samples, rollup_rows, skipped
        Totals (``skipped``: samples older than the signal's previous one).
    seconds
        Total wall-clock seconds.
    size_bytes
        Size of ``history.db``.
    """

    history_path: Path
    seed_path: Path
    days: list[DayStats] = field(default_factory=list)
    decisions: int = 0
    commands: int = 0
    samples: int = 0
    rollup_rows: int = 0
    skipped: int = 0
    seconds: float = 0.0
    size_bytes: int = 0


class RoomRelabelled:
    """Controller wrapper: the open-loop run's room input under the configured room signal.

    The open-loop run resolves the room from its own signals (Datalake or mirror). The service
    names it by ``control_room_signal`` and gives it the sensor profile's step and kind;
    the replay only rebuilds a room input that carries that signal.

    Parameters
    ----------
    inner
        The ovenbird controller.
    signal
        Configured room signal.
    """

    def __init__(self, inner: OvenbirdController, signal: SignalId | None) -> None:
        self._inner = inner
        self._signal = signal

    @property
    def name(self) -> str:
        """Controller name recorded in every decision."""
        return self._inner.name

    @property
    def config(self) -> OvenbirdConfig:
        """The wrapped controller's configuration."""
        return self._inner.config

    def initial_state(self) -> OvenbirdState:
        """Return the state before the first tick."""
        return self._inner.initial_state()

    def step(self, state: OvenbirdState, inputs: ControlInputs) -> StepResult[OvenbirdState]:
        """Advance one tick with the room input relabelled."""
        room = inputs.room
        if room is None or self._signal is None:
            return self._inner.step(state, dataclasses.replace(inputs, room=None))
        view = inputs.snapshot.get(room.source)
        profile = self._inner.config.room
        relabelled = RoomInput(
            room.value,
            room.age,
            room.fresh,
            self._signal,
            room.reason,
            quantum_k=profile.quantum_k,
            held_s=None if view is None else view.held,
            alive_by=None if view is None else view.alive_by,
            profile=profile.kind,
        )
        return self._inner.step(state, dataclasses.replace(inputs, room=relabelled))


def build_settings(config: Path | None) -> tuple[Settings, dict[str, Any]]:
    """Return the effective settings of a seed on top of the defaults, and its stored values.

    The conversion has no MQTT inputs or Home Assistant, so the signals the seed names
    (room, liveness, cross-check, stove reference) that would need them get a stub
    for validation only; the values returned are the seed's own.

    Parameters
    ----------
    config
        Seed file (``OVENBIRD_CONFIG_SEED`` format), or ``None`` for the defaults.

    Returns
    -------
    tuple
        The settings and the seed's storable values.

    Raises
    ------
    ConvertError
        When the seed cannot be read or does not validate.
    """
    try:
        values = {} if config is None else storable(read_seed(config))
    except ConfigError as exc:
        raise ConvertError(str(exc)) from None
    named = _named_signals(values)
    stubs: dict[str, Any] = {}
    if any(signal.startswith(HA_SIGNAL_PREFIX) for signal in named):
        stubs.update(ha_url=STUB_HA_URL, ha_token=STUB_HA_TOKEN)
    bare = [s for s in named if "/" not in s]
    if bare:
        stubs["mqtt_inputs"] = [
            {
                "topic": f"{STUB_TOPIC_BASE}{signal}",
                "signal": signal,
                "minimum": STUB_RANGE[0],
                "maximum": STUB_RANGE[1],
            }
            for signal in bare
        ]
    try:
        settings = merge(MergedSettings(**stubs), {}, values)
        settings.controller_config()
    except ValueError as exc:
        raise ConvertError(f"the configuration does not validate: {exc}") from None
    return settings, values


def _named_signals(values: dict[str, Any]) -> list[str]:
    names: list[str] = []
    room = values.get("control_room_signal")
    if isinstance(room, str):
        names.append(room)
    liveness = values.get("control_room_liveness_signals") or []
    names.extend(s for s in liveness if isinstance(s, str))
    for key in ("control_room_crosscheck_signal", "control_stove_reference_signal"):
        value = values.get(key)
        if isinstance(value, str):
            names.append(value)
    return list(dict.fromkeys(names))


def check_output(out: Path, *, force: bool) -> Path:
    """Return ``out``'s ``history.db`` path after checking it may be written.

    Parameters
    ----------
    out
        Output directory.
    force
        Whether an existing non-empty database may be replaced.

    Raises
    ------
    ConvertError
        When ``out`` is the service's production data directory, or holds a non-empty
        ``history.db`` and ``force`` is not set.
    """
    resolved = out.expanduser().resolve()
    protected = {DEFAULT_DATA_DIR.resolve()}
    configured = _env_data_dir()
    if configured is not None:
        protected.add(configured.resolve())
    if resolved in protected:
        raise ConvertError(f"{out} is the service's data directory; choose another --out")
    path = resolved / HISTORY_NAME
    if path.exists() and path.stat().st_size > 0 and not force:
        raise ConvertError(f"{path} exists and is not empty; use --force to replace it")
    return path


def _env_data_dir() -> Path | None:
    raw = os.environ.get(DATA_DIR_ENV)
    return Path(raw) if raw else None


def _remove_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def _span(options: ConvertOptions) -> tuple[float, float]:
    start = datetime(options.start.year, options.start.month, options.start.day, tzinfo=UTC)
    end = datetime(options.end.year, options.end.month, options.end.day, tzinfo=UTC)
    return start.timestamp(), end.timestamp() + DAY_S - TICK_S


class _Sampler:
    """Turns the stream's items into the history samples and command rows the service writes.

    Runs its own state store next to the open-loop run's (same staleness policy), because the
    loop heat needs a snapshot at each heat input, as the runtime's ``apply`` takes it.
    """

    def __init__(self, options: OpenLoopOptions, settings: Settings, room: RoomSource) -> None:
        self.policy = staleness_policy(options.room_max_age_s, stove_reference(options))
        self.store = StateStore(self.policy)
        self.router = InputRouter(
            mqtt_signals={MIRROR_TOPIC: MqttSignal(MIRROR_SIGNAL, "°C", *ROOM_RANGE_C)}
        )
        self.relabel: dict[SignalId, SignalId] = {}
        room_signal = settings.control_room_signal
        if room_signal is not None:
            if room in (RoomSource.AUTO, RoomSource.DATALAKE):
                self.relabel[DATALAKE_SIGNAL] = room_signal
            if room in (RoomSource.AUTO, RoomSource.MIRROR):
                self.relabel[MIRROR_SIGNAL] = room_signal
        self.samples: list[Sample] = []
        self.commands: list[CommandRow] = []

    def feed(self, item: StreamItem) -> None:
        """Apply one stream item to the store and collect its samples or command row."""
        if isinstance(item, CaptureRecord):
            if item.topic in (SETCURVES_TOPIC, SETDUTY_TOPIC):
                self._command(item)
                return
            converted = capture_input(item)
            parsed = (
                self.router.route(converted) if isinstance(converted, MqttMessage) else converted
            )
        else:
            parsed = item
        changed = self.store.apply(parsed)
        if isinstance(parsed, Reading):
            self._reading(parsed)
        elif isinstance(parsed, ParseError) and changed:
            self._gap(parsed)

    def _reading(self, reading: Reading) -> None:
        sample = sample_from_reading(reading, self.policy)
        if sample is not None:
            self._add(sample)
        if not reading.retained and reading.signal in HEAT_INPUTS:
            snapshot = self.store.snapshot(reading.observed)
            self.samples.append(heat_sample(snapshot, self.policy))

    def _gap(self, error: ParseError) -> None:
        sample = gap_sample(error)
        if sample is not None:
            self._add(sample)

    def _add(self, sample: Sample) -> None:
        target = self.relabel.get(sample.signal)
        self.samples.append(
            sample if target is None else dataclasses.replace(sample, signal=target)
        )

    def _command(self, record: CaptureRecord) -> None:
        if record.retained:
            return
        if record.topic == SETCURVES_TOPIC:
            kind, value = IntentKind.WATER_SETPOINT, setcurves_target(record.payload)
        else:
            kind, value = IntentKind.MAX_PUMP_DUTY, _integer(record.payload)
        if value is None:
            return
        self.commands.append(
            CommandRow(
                record.t,
                kind.value,
                value,
                RECORDED_STATUS,
                0,
                record.topic,
                record.payload,
                RECORDED_DETAIL,
            )
        )


def _integer(payload: str) -> int | None:
    try:
        return int(payload.strip())
    except ValueError:
        return None


def _utc_day(t: float) -> date:
    return datetime.fromtimestamp(t, UTC).date()


class _Writer:
    """Writes samples, decisions and commands in batches through the service's own code."""

    def __init__(self, conn: sqlite3.Connection, version: int | None) -> None:
        self.conn = conn
        self.db = HistoryDatabase(conn)
        self.packer = DecisionPacker()
        self.version = version
        self.decisions: list[DecisionRow] = []
        self.result = ConvertResult(Path(), Path())

    def decision(self, tick: Tick) -> None:
        record = tick.result.decision
        self.decisions.append(
            DecisionRow(
                ts=tick.t,
                controller=record.controller,
                mode=record.mode.value,
                ladder=record.ladder.value,
                reason=record.reason.value,
                setpoint=record.setpoint,
                record=json.dumps(record.to_json_dict(), separators=COMPACT, ensure_ascii=False),
                arbiter="[]",
                commands="[]",
                config_version=self.version,
            )
        )

    def write_samples(self, sampler: _Sampler) -> None:
        """Write the collected samples (and their rollups) and forget them."""
        written = self.db.write_batch(sampler.samples)
        self.result.samples += written.samples
        self.result.rollup_rows += written.rollup_rows
        self.result.skipped += written.skipped
        sampler.samples.clear()

    def flush(self, sampler: _Sampler) -> tuple[int, int, int]:
        """Write what is collected; returns ``(decisions, commands, raw samples so far)``."""
        self.write_samples(sampler)
        decisions, commands = len(self.decisions), len(sampler.commands)
        write_journal(self.conn, self.decisions, sampler.commands, packer=self.packer)
        self.result.decisions += decisions
        self.result.commands += commands
        sampler.commands.clear()
        self.decisions.clear()
        return decisions, commands, self.result.samples


def convert(options: ConvertOptions, settings: Settings, values: dict[str, Any]) -> ConvertResult:
    """Convert the recorded period into ``history.db`` and write the effective seed.

    Parameters
    ----------
    options
        What to convert.
    settings
        Effective settings (:func:`build_settings`).
    values
        The seed's storable values, written to ``config-seed.json``.

    Returns
    -------
    ConvertResult
        Totals and per-day statistics.
    """
    history_path = check_output(options.out, force=options.force)
    if history_path.exists():
        _remove_database(history_path)
    started = time.perf_counter()
    room_max_age_s = (
        settings.room_profile().max_age_s
        if options.room_max_age_s is None
        else options.room_max_age_s
    )
    start, end = _span(options)
    controller = RoomRelabelled(
        OvenbirdController(settings.controller_config()), settings.control_room_signal
    )
    stove = controller.config.stove
    drive_options = OpenLoopOptions(
        room=options.room,
        room_max_age_s=room_max_age_s,
        tick_s=TICK_S,
        start=start,
        end=end,
        stove=stove if stove is not None and stove.reference is not None else None,
    )
    stream, _ = recorded_stream(options.capture, options.datalake, drive_options)
    sampler = _Sampler(drive_options, settings, options.room)
    seed_path = history_path.with_name(SEED_NAME)
    conn = open_history(history_path)
    writer = _Writer(conn, options.config_version)
    writer.result = ConvertResult(history_path, seed_path)
    current: DayStats | None = None
    mark = time.perf_counter()
    counted = 0

    def close_day(stats: DayStats) -> None:
        nonlocal counted
        decisions, commands, total = writer.flush(sampler)
        stats.ticks, stats.commands, stats.samples = decisions, commands, total - counted
        counted = total
        stats.seconds += time.perf_counter() - mark
        writer.result.days.append(stats)
        print(
            f"{stats.day}: {stats.ticks} ticks, {stats.samples} samples, "
            f"{stats.commands} commands, {stats.seconds:.1f} s",
            flush=True,
        )

    def tee() -> Iterator[StreamItem]:
        for item in stream:
            sampler.feed(item)
            if len(sampler.samples) >= FLUSH_SAMPLES:
                writer.write_samples(sampler)
            yield item

    def on_tick(tick: Tick) -> None:
        nonlocal current, mark
        day = _utc_day(tick.t)
        if current is None or current.day != day:
            if current is not None:
                close_day(current)
            current = DayStats(day)
            mark = time.perf_counter()
        writer.decision(tick)

    try:
        drive(controller, tee(), drive_options, on_tick)
        if current is not None:
            close_day(current)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    seed_path.write_text(_seed_document(values), encoding="utf-8")
    result = writer.result
    result.seconds = time.perf_counter() - started
    result.size_bytes = history_path.stat().st_size
    return result


def _seed_document(values: dict[str, Any]) -> str:
    document = {
        "ovenbird_config": 1,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": 0,
        "values": values,
    }
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface definition."""
    parser = argparse.ArgumentParser(prog="python -m ovenbird_harness.convert", description=__doc__)
    parser.add_argument("--capture", type=Path, required=True, help="capture dir or day file")
    parser.add_argument("--datalake", type=Path, help="Datalake root (room sensor)")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, required=True)
    parser.add_argument("--config", type=Path, help="configuration seed JSON (default settings)")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--room", choices=[r.value for r in RoomSource], default="auto")
    parser.add_argument(
        "--room-max-age",
        type=float,
        metavar="S",
        help="room staleness limit (default: the seed's room profile limit)",
    )
    parser.add_argument(
        "--config-version",
        type=int,
        help="configuration version stored with the decisions (1 for a freshly seeded instance)",
    )
    parser.add_argument("--force", action="store_true", help="replace a non-empty history.db")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the conversion from the command line; exit code 1 when it cannot run."""
    args = build_parser().parse_args(argv)
    if args.end < args.start:
        print("--to is before --from", file=sys.stderr)
        return 1
    options = ConvertOptions(
        capture=args.capture,
        out=args.out,
        start=args.start,
        end=args.end,
        datalake=args.datalake,
        config=args.config,
        room=RoomSource(args.room),
        room_max_age_s=args.room_max_age,
        config_version=args.config_version,
        force=args.force,
    )
    try:
        check_output(options.out, force=options.force)
        settings, values = build_settings(options.config)
        result = convert(options, settings, values)
    except ConvertError as exc:
        print(f"convert: {exc}", file=sys.stderr)
        return 1
    days = max(len(result.days), 1)
    print(
        f"{len(result.days)} days in {result.seconds:.1f} s "
        f"({result.seconds / days:.1f} s per recorded day); {result.decisions} decisions, "
        f"{result.commands} recorded commands, {result.samples} samples; "
        f"{result.size_bytes / 1e6:.1f} MB ({result.size_bytes / days / 1e6:.2f} MB per day)"
    )
    print(f"history: {result.history_path}\nseed: {result.seed_path}")
    print("keep forever: " + " ".join(FOREVER_ENV))
    return 0


if __name__ == "__main__":
    sys.exit(main())
