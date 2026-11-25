"""Open-loop run: any controller driven through a recorded capture, never sending.

At every tick (60 s by default) a :class:`~ovenbird_core.store.StateStore` that has
been fed every recorded input up to that instant is snapshot, the room input is
resolved (:class:`~ovenbird_sim.evaluate.recorded.RoomSource`) and the controller
steps. Its intents and decision records go to the result database only; the
harness holds no MQTT client or any other transport.

Open loop means the recorded plant followed whatever controlled it at the time, not
the controller under test: integrators, ramps and timers react to the recorded
outcomes. The summary is therefore limited to what an open loop may claim —
decisions, reasons, ladder levels, intent changes, the setpoint distribution (the
recorded one shown as reference only) and the handling of stale inputs. Every output says
:data:`~ovenbird_sim.evaluate.meta.NO_CLAIMS_BANNER`.

With :attr:`OpenLoopOptions.stove` an ``ovenbird`` controller runs with wood-stove mode
(its reference room, if any, read from the Datalake like the room) and the summary
lists every episode: entry and exit times, trigger, exit reason and the setpoints.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from ovenbird_core.capture import CaptureRecord, capture_input
from ovenbird_core.catalogue import HeishaSignal
from ovenbird_core.control.config import StoveConfig
from ovenbird_core.control.observe import pump_actual
from ovenbird_core.control.ovenbird import OvenbirdController
from ovenbird_core.control.protocol import Controller, StepResult
from ovenbird_core.control.record import JsonDict, JsonValue
from ovenbird_core.control.types import (
    ControlInputs,
    IntentKind,
    LadderLevel,
    Mode,
    RoomInput,
)
from ovenbird_core.heishamon import MqttMessage
from ovenbird_core.inputs import HA_SIGNAL_PREFIX, InputRouter, MqttSignal
from ovenbird_core.instant import Instant
from ovenbird_core.store import HA_MAX_AGE_S, StalenessPolicy, StateStore
from ovenbird_sim.evaluate import meta
from ovenbird_sim.evaluate.recorded import (
    DATALAKE_SIGNAL,
    MIRROR_SIGNAL,
    MIRROR_TOPIC,
    ROOM_RANGE_C,
    SETCURVES_TOPIC,
    SETDUTY_TOPIC,
    RoomResolver,
    RoomSource,
    StreamItem,
    control_topics,
    datalake_room,
    day_files,
    item_time,
    iter_records,
    merged_stream,
    setcurves_target,
)
from ovenbird_sim.evaluate.resultdb import ResultDB

RUN_ID: Final = "open-loop"
DB_NAME: Final = "openloop.sqlite"
SUMMARY_NAME: Final = "openloop_summary.json"
SECONDS_PER_DAY: Final = 86400.0


@dataclass(frozen=True, slots=True)
class OpenLoopOptions:
    """Options of a open-loop run.

    Parameters
    ----------
    room
        Room input source.
    room_max_age_s
        Maximum age of the recorded room signals: the live Home Assistant policy
        (1800 s) unless configured. The recording holds state changes only, so this
        is pessimistic against live, where ``last_reported`` re-reads confirm
        unchanged values (see :mod:`.recorded`).
    tick_s
        Tick period.
    start, end
        First and last tick bound in unix seconds (``None``: the capture's span).
    mode
        Mode passed to the controller (``shadow``: decide, never send).
    store_inputs
        Also store every input reference as a row of ``inputs``.
    stove
        Wood-stove mode for an ``ovenbird`` controller (``None``: as configured).
    stove_reference_max_age_s
        Maximum age of the wood-stove reference room (``None``: ``room_max_age_s``).
    """

    room: RoomSource = RoomSource.AUTO
    room_max_age_s: float = HA_MAX_AGE_S
    tick_s: float = 60.0
    start: float | None = None
    end: float | None = None
    mode: Mode = Mode.SHADOW
    store_inputs: bool = True
    stove: StoveConfig | None = None
    stove_reference_max_age_s: float | None = None


@dataclass(frozen=True, slots=True)
class Reference:
    """What the recorded control did at a tick, for reference only.

    Parameters
    ----------
    recorded_setpoint
        ``Z1_Water_Target_Temp`` the pump reported (the setpoint it applied).
    recorded_fresh
        Whether that value was fresh.
    last_command
        Value of the last recorded ``SetCurves``.
    last_command_t
        Its time.
    """

    recorded_setpoint: int | None
    recorded_fresh: bool
    last_command: int | None
    last_command_t: float | None


@dataclass(frozen=True, slots=True)
class Tick:
    """One open-loop run tick.

    Parameters
    ----------
    index
        Tick index from 0.
    t
        Tick time in unix seconds.
    result
        The controller's step result.
    room
        Room input given to the controller.
    reference
        The recorded control at the tick.
    heishamon_alive
        Whether the snapshot had a live HeishaMon heartbeat.
    """

    index: int
    t: float
    result: StepResult[Any]
    room: RoomInput | None
    reference: Reference
    heishamon_alive: bool


def staleness_policy(
    room_max_age_s: float, reference: tuple[str, float] | None = None
) -> StalenessPolicy:
    """Default policy with the replay's room maximum age on both room signals.

    ``reference`` adds a signal (the wood-stove reference room) with its own maximum age.
    """
    policy = (
        StalenessPolicy()
        .with_override(DATALAKE_SIGNAL, room_max_age_s)
        .with_override(MIRROR_SIGNAL, room_max_age_s)
    )
    return policy if reference is None else policy.with_override(*reference)


def stove_reference(options: OpenLoopOptions) -> tuple[str, float] | None:
    """Return the wood-stove reference room signal and its maximum age, if any."""
    stove = options.stove
    if stove is None or stove.reference is None:
        return None
    age = options.stove_reference_max_age_s
    return stove.reference, options.room_max_age_s if age is None else age


def stove_option(
    enabled: bool, reference: str | None = None, floor_c: float | None = None
) -> StoveConfig | None:
    """Return the open-loop run's wood-stove mode from command-line values.

    Parameters
    ----------
    enabled
        Run with wood-stove mode (defaults otherwise).
    reference
        Reference room: a signal id or a bare HA entity id (``sensor.x``).
    floor_c
        Reference floor (the default 19 °C when ``None``).
    """
    if not enabled:
        return None
    signal = None
    if reference:
        signal = reference if "/" in reference else f"{HA_SIGNAL_PREFIX}{reference}"
    stove = StoveConfig(reference=signal)
    return stove if floor_c is None else replace(stove, reference_floor_c=floor_c)


def with_stove[S](controller: Controller[S], stove: StoveConfig | None) -> Controller[S]:
    """Return ``controller`` with wood-stove mode, when it is an ovenbird controller."""
    if stove is None or not isinstance(controller, OvenbirdController):
        return controller
    stoved: Any = OvenbirdController(replace(controller.config, stove=stove), controller.name)
    return stoved


def drive[S](
    controller: Controller[S],
    stream: Iterable[StreamItem],
    options: OpenLoopOptions,
    on_tick: Callable[[Tick], None],
) -> int:
    """Run ``controller`` over a time-ordered stream of recorded inputs.

    Parameters
    ----------
    controller
        Any controller.
    stream
        Capture records and Datalake readings in time order. Without
        ``options.start`` the first tick follows the first capture record and,
        without ``options.end``, the last one follows the last capture record;
        Datalake readings outside that span only set state.
    options
        Open-loop run options.
    on_tick
        Called with every tick (the only output path; nothing is sent).

    Returns
    -------
    int
        Number of ticks.
    """
    store = StateStore(staleness_policy(options.room_max_age_s, stove_reference(options)))
    router = InputRouter(
        mqtt_signals={MIRROR_TOPIC: MqttSignal(MIRROR_SIGNAL, "°C", *ROOM_RANGE_C)}
    )
    resolver = RoomResolver(options.room)
    step = options.tick_s
    state = controller.initial_state()
    next_tick = math.ceil(options.start / step) * step if options.start is not None else None
    last_command: tuple[int, float] | None = None
    count = 0
    last_t: float | None = None

    def tick(t: float) -> None:
        nonlocal state, count
        now = Instant.from_unix(t)
        snapshot = store.snapshot(now)
        room = resolver.resolve(snapshot)
        inputs = ControlInputs(
            now=now,
            snapshot=snapshot,
            room=room,
            plan=None,
            mode=options.mode,
            override=None,
            actual=pump_actual(snapshot),
        )
        result = controller.step(state, inputs)
        state = result.state
        applied = inputs.actual.water_target
        reference = Reference(
            recorded_setpoint=None if applied is None else applied.value,
            recorded_fresh=applied is not None and applied.fresh,
            last_command=None if last_command is None else last_command[0],
            last_command_t=None if last_command is None else last_command[1],
        )
        on_tick(Tick(count, t, result, room, reference, snapshot.heishamon.alive))
        count += 1

    pending: deque[StreamItem] = deque()

    def apply(item: StreamItem) -> None:
        nonlocal last_command
        if not isinstance(item, CaptureRecord):
            store.apply(item)
            return
        if item.topic in (SETCURVES_TOPIC, SETDUTY_TOPIC):
            target = setcurves_target(item.payload) if item.topic == SETCURVES_TOPIC else None
            if target is not None and not item.retained:
                last_command = (target, item.t)
            return
        converted = capture_input(item)
        store.apply(router.route(converted) if isinstance(converted, MqttMessage) else converted)

    def advance(until: float, *, inclusive: bool) -> None:
        nonlocal next_tick
        while next_tick is not None and (next_tick < until or (inclusive and next_tick <= until)):
            if options.end is not None and next_tick > options.end:
                return
            while pending and item_time(pending[0]) <= next_tick:
                apply(pending.popleft())
            tick(next_tick)
            next_tick += step

    for item in stream:
        t = item_time(item)
        if options.end is not None and t > options.end:
            break
        if not isinstance(item, CaptureRecord):
            if next_tick is None:
                store.apply(item)
            else:
                pending.append(item)
            continue
        if next_tick is None:
            next_tick = math.ceil(t / step) * step
        advance(t, inclusive=False)
        while pending:
            apply(pending.popleft())
        last_t = t
        apply(item)
    final = options.end if options.end is not None else last_t
    if final is not None:
        advance(final, inclusive=True)
    return count


@dataclass(slots=True)
class Summary:
    """Open-loop metrics accumulated over the ticks (see the module docstring)."""

    ticks: int = 0
    first_t: float | None = None
    last_t: float | None = None
    reasons: Counter[str] = field(default_factory=Counter)
    ladder: Counter[str] = field(default_factory=Counter)
    binding: Counter[str] = field(default_factory=Counter)
    intent_changes: Counter[str] = field(default_factory=Counter)
    intent_ticks: Counter[str] = field(default_factory=Counter)
    setpoints: Counter[int] = field(default_factory=Counter)
    recorded: Counter[int] = field(default_factory=Counter)
    agree_exact: int = 0
    agree_within_1: int = 0
    agree_n: int = 0
    room_missing: int = 0
    room_stale: int = 0
    stale_inputs: Counter[str] = field(default_factory=Counter)
    held_or_refused: Counter[str] = field(default_factory=Counter)
    dead_heishamon: int = 0
    stove_enabled: bool = False
    stove_ticks: int = 0
    stove_episodes: list[JsonDict] = field(default_factory=list)
    _last_intents: dict[str, int] = field(default_factory=dict)

    def add(self, tick: Tick) -> None:
        """Account for one tick."""
        record = tick.result.decision
        self.ticks += 1
        self.first_t = tick.t if self.first_t is None else self.first_t
        self.last_t = tick.t
        self.reasons[record.reason.value] += 1
        self.ladder[record.ladder.value] += 1
        self.binding[record.binding or "none"] += 1
        current = {intent.kind.value: intent.value for intent in tick.result.intents}
        for kind, value in current.items():
            self.intent_ticks[kind] += 1
            previous = self._last_intents.get(kind)
            if previous is not None and previous != value:
                self.intent_changes[kind] += 1
        self._last_intents.update(current)
        setpoint = current.get(IntentKind.WATER_SETPOINT.value)
        if setpoint is not None:
            self.setpoints[setpoint] += 1
        ref = tick.reference
        if ref.recorded_setpoint is not None and ref.recorded_fresh:
            self.recorded[ref.recorded_setpoint] += 1
            if setpoint is not None:
                self.agree_n += 1
                self.agree_exact += setpoint == ref.recorded_setpoint
                self.agree_within_1 += abs(setpoint - ref.recorded_setpoint) <= 1
        if tick.room is None:
            self.room_missing += 1
        elif not tick.room.fresh:
            self.room_stale += 1
        for ref_input in record.inputs_used:
            if not ref_input.fresh:
                self.stale_inputs[ref_input.signal] += 1
        if record.ladder in (LadderLevel.HOLD, LadderLevel.REFUSE):
            self.held_or_refused[f"{record.ladder.value}:{record.reason.value}"] += 1
        if not tick.heishamon_alive:
            self.dead_heishamon += 1
        self._stove(tick, setpoint)

    def _stove(self, tick: Tick, setpoint: int | None) -> None:
        record = tick.result.decision
        state = record.controller_state
        if "stove_state" not in state:
            return
        self.stove_enabled = True
        event = state.get("stove_event")
        curve = next((t.value for t in record.terms if t.name == "curve"), None)
        if event == "entered":
            self.stove_episodes.append(
                {
                    "entered": meta.utc_iso(tick.t),
                    "source": state.get("stove_source"),
                    "trigger": state.get("stove_trigger"),
                    "entry_c": state.get("stove_entry_c"),
                    "enter_c": state.get("stove_enter_c"),
                    "exit_c": state.get("stove_exit_c"),
                    "integral_held_k": state.get("stove_integral_k"),
                    "curve_c_at_entry": curve,
                    "setpoint_at_entry": setpoint,
                    "reference_c_at_entry": state.get("stove_reference_c"),
                    "setpoint_min": setpoint,
                    "setpoint_max": setpoint,
                    "backoff_k_min": state.get("stove_backoff_k"),
                    "backoff_k_max": state.get("stove_backoff_k"),
                    "exited": None,
                    "exit": None,
                    "minutes": None,
                }
            )
        if state.get("stove_state") == "active" and self.stove_episodes:
            self.stove_ticks += 1
            episode = self.stove_episodes[-1]
            if setpoint is not None:
                episode["setpoint_min"] = _lower(episode["setpoint_min"], setpoint)
                episode["setpoint_max"] = _upper(episode["setpoint_max"], setpoint)
            backoff = state.get("stove_backoff_k")
            if isinstance(backoff, int | float):
                episode["backoff_k_min"] = _lower(episode["backoff_k_min"], backoff)
                episode["backoff_k_max"] = _upper(episode["backoff_k_max"], backoff)
        if event == "exited" and self.stove_episodes:
            episode = self.stove_episodes[-1]
            started = datetime.fromisoformat(str(episode["entered"]).replace("Z", "+00:00"))
            episode["exited"] = meta.utc_iso(tick.t)
            episode["exit"] = state.get("stove_exit")
            episode["minutes"] = (tick.t - started.timestamp()) / 60.0
            episode["setpoint_after_exit"] = setpoint

    def to_json(self, tick_s: float) -> JsonDict:
        """Return the summary (open-loop claims only)."""
        n = max(self.ticks, 1)
        days = self.ticks * tick_s / SECONDS_PER_DAY
        return {
            "banner": meta.NO_CLAIMS_BANNER,
            "ticks": self.ticks,
            "days": days,
            "first_tick": None if self.first_t is None else meta.utc_iso(self.first_t),
            "last_tick": None if self.last_t is None else meta.utc_iso(self.last_t),
            "decisions": {
                "reason_codes": _histogram(self.reasons),
                "ladder_time_share": {k: v / n for k, v in sorted(self.ladder.items())},
                "binding": _histogram(self.binding),
            },
            "intents": {
                kind: {
                    "ticks_with_intent": self.intent_ticks[kind],
                    "changes": self.intent_changes[kind],
                    "changes_per_day": self.intent_changes[kind] / days if days else None,
                }
                for kind in sorted(self.intent_ticks)
            },
            "setpoint": {
                "distribution": _shares(self.setpoints),
                "mean": _mean(self.setpoints),
                "recorded_reference_only": {
                    "note": "recorded Z1_Water_Target_Temp, shown as reference only",
                    "distribution": _shares(self.recorded),
                    "mean": _mean(self.recorded),
                    "same_tick_exact_share": self.agree_exact / self.agree_n
                    if self.agree_n
                    else None,
                    "same_tick_within_1k_share": self.agree_within_1 / self.agree_n
                    if self.agree_n
                    else None,
                },
            },
            "stale_inputs": {
                "room_missing_share": self.room_missing / n,
                "room_stale_share": self.room_stale / n,
                "curve_only_share": self.ladder.get("curve_only", 0) / n,
                "heishamon_dead_ticks": self.dead_heishamon,
                "hold_or_refuse_ticks": _histogram(self.held_or_refused),
                "stale_input_ticks": _histogram(self.stale_inputs),
            },
            **(
                {
                    "stove": {
                        "active_ticks": self.stove_ticks,
                        "active_share": self.stove_ticks / n,
                        "episodes": list(self.stove_episodes),
                    }
                }
                if self.stove_enabled
                else {}
            ),
        }


def _lower(current: JsonValue, value: float) -> float:
    return value if not isinstance(current, int | float) else min(current, value)


def _upper(current: JsonValue, value: float) -> float:
    return value if not isinstance(current, int | float) else max(current, value)


def _histogram(counter: Counter[str]) -> JsonDict:
    ordered: list[tuple[str, int]] = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    out: JsonDict = dict(ordered)
    return out


def _shares(counter: Counter[int]) -> JsonDict:
    total = sum(counter.values())
    return {str(k): v / total for k, v in sorted(counter.items())} if total else {}


def _mean(counter: Counter[int]) -> float | None:
    total = sum(counter.values())
    return sum(k * v for k, v in counter.items()) / total if total else None


def recorded_stream(
    capture: Path, datalake: Path | None, options: OpenLoopOptions
) -> tuple[Iterable[StreamItem], list[Path]]:
    """Return the time-ordered recorded inputs of a open-loop run and the capture files used."""
    files = day_files(capture, options.start, options.end)
    records = iter_records(files, control_topics(), options.end)
    use_lake = options.room in (RoomSource.AUTO, RoomSource.DATALAKE)
    lake = datalake_room(datalake if use_lake else None, end=options.end)
    reference = stove_reference(options)
    if reference is None or not reference[0].startswith(HA_SIGNAL_PREFIX):
        return merged_stream(records, lake), files
    entity = reference[0][len(HA_SIGNAL_PREFIX) :]
    extra = datalake_room(datalake, entity=entity, end=options.end)
    return merged_stream(records, lake, extra), files


def open_loop_run[S](
    controller: Controller[S],
    capture: Path,
    out: Path,
    *,
    datalake: Path | None = None,
    options: OpenLoopOptions | None = None,
    extra_meta: dict[str, JsonValue] | None = None,
) -> JsonDict:
    """Run a open-loop run and write ``openloop.sqlite`` and ``openloop_summary.json`` to ``out``.

    Parameters
    ----------
    controller
        Controller under test.
    capture
        Capture directory or one day file.
    out
        Output directory.
    datalake
        Datalake root for the room sensor.
    options
        Open-loop run options.
    extra_meta
        Additional metadata entries.

    Returns
    -------
    JsonDict
        The summary (also written as JSON).
    """
    opts = options or OpenLoopOptions()
    controller = with_stove(controller, opts.stove)
    started = time.perf_counter()
    stream, files = recorded_stream(capture, datalake, opts)
    summary = Summary()
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / DB_NAME
    with ResultDB(db_path) as db:

        def sink(tick: Tick) -> None:
            db.add_step(RUN_ID, tick.index, tick.result, inputs=opts.store_inputs)
            ref = tick.reference
            db.add(
                "reference",
                (
                    RUN_ID,
                    tick.index,
                    ref.recorded_setpoint,
                    int(ref.recorded_fresh),
                    ref.last_command,
                    ref.last_command_t,
                ),
            )
            summary.add(tick)

        drive(controller, stream, opts, sink)
        identity = meta.controller_identity(controller)
        provenance: dict[str, JsonValue] = {
            "mode": "open-loop",
            "banner": meta.NO_CLAIMS_BANNER,
            "controller": identity,
            "config_hash": meta.config_hash(
                {"controller": identity["config"], "options": meta.to_jsonable(opts)}
            ),
            "options": meta.to_jsonable(opts),
            "capture": {
                "path": str(capture),
                "files": [p.name for p in files],
                "first_tick": None if summary.first_t is None else meta.utc_iso(summary.first_t),
                "last_tick": None if summary.last_t is None else meta.utc_iso(summary.last_t),
                "from": None if opts.start is None else meta.utc_iso(opts.start),
                "to": None if opts.end is None else meta.utc_iso(opts.end),
            },
            "datalake": None if datalake is None else str(datalake),
            "git": meta.git_commit(),
            "room_signals": {"datalake": DATALAKE_SIGNAL, "mirror": MIRROR_SIGNAL},
            "applied_setpoint_signal": HeishaSignal.Z1_WATER_TARGET_TEMP.value,
            "seed": None,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        provenance.update(extra_meta or {})
        db.set_meta(provenance)
        result = summary.to_json(opts.tick_s)
        result["meta"] = {k: v for k, v in provenance.items() if k != "created"}
        result["runtime_s"] = time.perf_counter() - started
        db.set_meta({"summary": {k: v for k, v in result.items() if k != "runtime_s"}})
    (out / SUMMARY_NAME).write_text(meta_json(result), encoding="utf-8")
    return result


def render_stove(summary: JsonDict) -> str | None:
    """Render the wood-stove episodes of a open-loop run summary (``None`` without stove mode)."""
    stove = summary.get("stove")
    if not isinstance(stove, dict):
        return None
    episodes = stove.get("episodes")
    rows = episodes if isinstance(episodes, list) else []
    share = stove.get("active_share")
    lines = [
        f"wood-stove mode: {len(rows)} episodes, active "
        f"{100 * share if isinstance(share, int | float) else 0.0:.1f} % of the ticks"
    ]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"  {row.get('entered')} -> {row.get('exited') or 'still active'}: "
            f"{row.get('trigger')} at {_number(row.get('entry_c'))} °C, "
            f"exit {row.get('exit') or '-'}, setpoint {row.get('setpoint_min')}-"
            f"{row.get('setpoint_max')} °C, back-off {_number(row.get('backoff_k_min'))}-"
            f"{_number(row.get('backoff_k_max'))} K"
        )
    return "\n".join(lines)


def _number(value: JsonValue) -> str:
    return f"{value:.1f}" if isinstance(value, int | float) else "?"


def meta_json(value: JsonValue) -> str:
    """Pretty JSON text for summaries."""
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
