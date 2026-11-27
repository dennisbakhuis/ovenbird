# Control interface (phase 2)

The contract between controllers, the evaluation harnesses (open-loop run, counterfactual replay,
simulation) and the service. Everything here lives in `ovenbird_core.control` and is pure:
no I/O, no wall-clock reads, no randomness without an explicit seed.

The dataclass field lists and the enum values in the code blocks below are checked against
the code by `packages/core/tests/control/test_interface_doc.py`; a change to either side
fails the test until the other follows.

## Controller protocol

```python
class Controller(Protocol[S]):
    name: str
    def initial_state(self) -> S: ...
    def step(self, state: S, inputs: ControlInputs) -> StepResult[S]: ...
```

- `step` is called on a fixed tick (default 60 s) by whoever drives time. It never sleeps,
  never reads clocks, never mutates `inputs`; the returned state replaces the old one.
- Implementations: `OvenbirdController` (the controller) and, in the evaluation harness,
  `RecordedSetpoints` (the baseline: it writes the recorded applied water setpoint of every
  tick, whatever wrote it). Both are usable interchangeably by every harness.

## Inputs

```python
@dataclass(frozen=True)
class ControlInputs:
    now: Instant                     # ovenbird_core.instant.Instant
    snapshot: Snapshot               # ovenbird_core.store snapshot (values, ages, freshness, reasons)
    room: RoomInput | None           # chosen room-temperature signal resolved by the caller
    plan: PlanSlice | None           # planner output for `now` (None in phase 2 unless testing)
    mode: Mode                       # off | shadow | auto | manual
    override: Override | None        # manual setpoint/boost/stove request with expiry
    actual: PumpActual               # what the pump currently reports as applied (Z1 water target,
                                     # max pump duty, quiet mode, heating mode), with freshness
```

The caller resolves the room sensor into a `RoomInput`, so the controller does not need to
know which entity is the room sensor or how it reports:

```python
@dataclass(frozen=True)
class RoomInput:
    value: float                     # °C
    age: float | None                # s since the last proof of life: a report of the value or
                                     # of a liveness signal (alias property `alive_s`)
    fresh: bool                      # usable under the caller's staleness policy
    source: SignalId                 # signal id of the value
    reason: str | None               # why it is not usable, when the source invalidated it
    quantum_k: float                 # sensor step: the value is known to within this (0: unknown)
    held_s: float | None             # s since the value last changed
    alive_by: SignalId | None        # liveness signal that gave the last proof of life, if not
                                     # the value itself
    profile: RoomProfile             # periodic | on_change
```

### Outside temperature of the heating curve

By default the pump's `main/Outside_Temp` drives everything that depends on the outside
temperature. `OvenbirdConfig.outside` (`OutsideSource(signal, max_age_s, plausible_min_c,
plausible_max_c, max_deviation_k)`, service settings `control_outside_signal`,
`control_outside_max_age_s` (default 30 min, 5 min … 24 h),
`control_outside_plausible_min_c` (default −40 °C, −60 … 0 °C),
`control_outside_plausible_max_c` (default 50 °C, 20 … 70 °C) and
`control_outside_max_deviation_k` (default 10 K, 2 … 50 K)) names another thermometer
(`ha/<entity_id>` or an MQTT input's signal, in °C) for the weather-dependent base only:

- **Uses the chosen sensor:** the outside filter and with it the curve term (its note
  ends `… °C raw from ha/sensor.garden`), the plan's outside-dependent weight and
  `outside_filtered_c` (the filtered value on the curve and weather pages). The chosen
  signal is listed in `inputs_used`; `controller_state` carries `outside_source`,
  `outside_fallback` and `outside_reason` (null while the chosen sensor is used, otherwise
  `missing`, `stale`, `implausible` or `deviates`).
- **Keeps the pump's sensor:** the safety envelope (`SafetyLimits.bounds`, the
  HeishaMon fallback rule knows only that sensor), the held bounds while inputs are
  missing, the safety monitors, the measured outside line of the weather report, the
  daily house-model learning and the trial summaries.
- **Stale:** while the chosen signal is missing, not fresh or older than `max_age_s`,
  the curve uses the pump's value; the note then reads `… °C raw from the pump:
  ha/sensor.garden is stale, 42 min old` (`has no value`, or `has no usable value, unit:
  …` for a value the store refused) and the service raises `outside_sensor_stale`
  until the sensor reports again. The service's store judges the chosen signal by
  `control_outside_max_age_s` too, so a limit above the 30 min source default works (a
  signal that is also the room signal keeps the room profile's limit).
- **Implausible:** a fresh value that is no finite number or lies outside
  `plausible_min_c` … `plausible_max_c` (`… is implausible, 60 °C is outside -40…50 °C`),
  or that is more than `max_deviation_k` from the pump's fresh reading (`… is too far from
  the pump, 20 °C against 8 °C, more than 10 K apart`; without a pump reading only the
  range applies), is not used either: the curve takes the pump's value, so one bad sample
  never enters the outside filter, and the service raises `outside_sensor_implausible`
  (clearing `outside_sensor_stale`, and the other way round).

Without `outside` the decision record is byte-identical to before (no extra note,
reference or state keys).

## Outputs

```python
@dataclass(frozen=True)
class StepResult(Generic[S]):
    state: S
    intents: tuple[CommandIntent, ...]   # desired pump settings this tick (may be empty)
    decision: DecisionRecord

@dataclass(frozen=True)
class CommandIntent:
    kind: IntentKind                 # see IntentKind below
    value: int                       # integer as HeishaMon expects
    reason: ReasonCode
```

Intents are **desired states, not commands**: the harness or the live arbiter compares them
with `actual` and decides what (if anything) to send, applying rate limits and verification.
Which HeishaMon command carries a `water_setpoint` (SetCurves `target.high` vs
`SetZ1HeatRequestTemperature`) is the adapter's concern, decided by the phase-3 spike.

An intent kind that is absent asks for nothing: during a defrost the pump drives its own
duty and ignores `Max_Pump_Duty` (`Pump_Duty` sits at a high value of the pump's own while
`Max_Pump_Duty` keeps the setting), so the ovenbird controller issues no `max_pump_duty`
intent then and keeps its desired duty for after the defrost; the adapter drops a queued
duty while `Defrosting_State` reads 1.

## Decision record

```python
@dataclass(frozen=True)
class DecisionRecord:
    at: Instant
    controller: str
    mode: Mode
    ladder: LadderLevel              # see LadderLevel below
    terms: tuple[Term, ...]          # named contributions, e.g. curve, room_feedback, plan,
                                     # start_ramp, stove — each with value before
                                     # and after its own clamp and a short note
    pre_round: float | None          # setpoint before rounding/deadband/dwell
    setpoint: int | None             # resulting desired water setpoint
    binding: str | None              # the constraint that determined the result, if any
    flip_distance: float | None      # how far an input must move to change the decision
    inputs_used: tuple[InputRef, ...]  # signal id, value, age, source (incl. forecast issue time)
    controller_state: Mapping[str, float | int | str | bool | None]  # integrator, ramp phase,
                                     # timers — flat, JSON-friendly
    reason: ReasonCode
    note: str                        # one human sentence, e.g. "Room 0.4 K below target;
                                     # PI adds +1.2 K to the curve's 31.0 °C"
    flip_input: str | None           # the input `flip_distance` is measured in
    intents: tuple[CommandIntent, ...]  # the step's intents, stored with the decision
    actor: str | None                # who set an active override
    schema: int                      # schema version of the stored form
```

Every record is serialisable to JSON with a stable schema (the open-loop result DB and the
live decision log store exactly this). The note names what shaped the decision: an active
defrost or DHW run ("defrost in progress: integrator frozen, no decrease"), the skipped duty
command in a defrost, whether the cycling floor raised the setpoint or limited a decrease,
an integer safety clamp ("safety bound envelope_max clamps 32 → 31 °C"), and, for an
`on_change` room sensor, the held value with its last proof of life ("device alive
(humidity 4 min ago)" only when a liveness signal reported; "last report 2 h ago"
otherwise) and the cooling authority when it is reduced or the feedback cools. When the
room value is stale or implausible the `room_feedback` term keeps the held offset
`H = min(output_limit_k, max(0, I) + min(held_step_max_k, kp·step))` (the positive
integrator plus the P part of one sensor step, bounded to 0.4 K by default), fading to zero
over 24 h, and its note says so ("keeps the held offset +0.8 K (positive integrator plus
one sensor step), fading to 0 over 24 h (stale for 2 h 10 m)"); at reduced cooling
authority `a` the term is `u_lim·a + (1−a)·H`, so it meets that value as the authority
reaches zero. Cooling the integrator did since the sensor's last proof of life is undone
when the device has been silent past the alive-decay start or its value goes stale or
implausible (`frozen_by` `room_silent_rollback` or `room_lost_rollback`; defrost, DHW and a
wood-stove episode defer it).

## Wood-stove mode

Optional (`OvenbirdConfig.stove`, a `StoveConfig`; `None` disables it, manual requests
included). A wood stove in the room the sensor is in heats that room far above the rest of
the house on the same heating loop; the room PI would saturate, wind its integrator down
and leave the house cold for hours afterwards. Wood-stove mode backs off instead and keeps
the integrator for afterwards.

- **Entry** (automatic, `auto`): the room value is fresh, plausible and trusted with full
  cooling authority (alive, not held too long), no sensor fault is pending (below), with
  a fresh reference room the room is at least `reference_gap_k` (1 K) above it, and it
  reaches `comfort + enter_above_k` (1.5 K, trigger `level`), or it rose by `rise_k`
  (1 K) within `rise_window_s` (30 min) (trigger `rise`; optional). The rise is measured
  from the comfort target or the window's lowest value, whichever is higher, and the
  room must be above the window's highest value at the time that low was set (the level
  before a dip): the rebound after airing (22 → 19 → 22 °C) is no stove. **Manual**: an
  `Override` of kind `stove` with value 1 and its own `until` (trigger `manual`).
- **Sensor fault, not a stove**: a stove warms a room by about 1 K per 10 min at most. A
  plausible room value that rose by `fault_step_k` (2 K) or more within
  `fault_step_window_s` (10 min), counted from that window's lowest value or from the
  level before a dip when that is higher, is a sensor fault (`stove_fault`,
  `stove_jump_k`): it ends an automatic episode (`room_jump`), and the automatic
  detection (also the hand-over) stays off until the trusted room value has been below
  the exit threshold. A manual episode continues. The cross-check (below) then flags
  the value as usual.
- **While active**: the room PI is frozen and its integrator held at its value from before
  the episode (`frozen_by` contains `stove`; no wind-down, no silent-device rollback); a
  plan is paused. The plausibility cross-check keeps running in stove mode: its
  threshold is widened by `crosscheck_allow_k` (4 K, so 5.5 K by default;
  `room_crosscheck_threshold_k` in the record), the offset is not learned, its timer
  restarts at the entry, and a verdict latched before or during the episode holds until
  room and cross-check agree again (a changing room value does not clear it, unlike
  outside an episode). A stove therefore raises no `room_implausible`, a sensor stuck far
  above the house still does (and ends an automatic episode as `room_untrusted`), and a
  manual request never clears a latched `room_implausible`. The `stove` term lowers the
  curve:
  `stove = −backoff · share`, with `backoff = backoff_k` (3 K) or, with `to_minimum`,
  `curve − safety low` (down to the safety minimum), and
  `share = clamp((reference − (floor − band)) / band, 0, 1)` while the optional reference
  room (e.g. the hall, `reference`) is below its floor (`reference_floor_c`, band
  `reference_band_k` 1 K), else 1; a configured reference without a fresh temperature
  (stale, unknown, not °C or outside −40…60 °C) keeps half (`share = 0.5`: fail safe,
  neither the full back-off nor none; the service raises `stove_reference_missing`).
  Start ramp, cycling
  floor, rounding/deadband/dwell, the defrost and DHW rules and the safety clamps apply as
  always: the pump never switches off, "off" is the low setpoint. The reason is `stove`
  unless a binding (a hold, the start ramp, the cycling floor, a safety clamp) decides.
- **Exit** (automatic): an automatic episode stays active while the trusted room value is
  above the exit threshold `comfort + enter_above_k − exit_hysteresis_k`. It ends below
  it once `min_active_s` (60 min) has passed (`cooled`), at the hard cap `max_active_s`
  (8 h, `max_active`), at once when the room value loses that trust (`room_untrusted`,
  also when the stove-mode cross-check latches) or jumps (`room_jump`), or, with a fresh
  reference room, once `min_active_s` has passed and the room is less than half of
  `reference_gap_k` above it (`reference_warm`: the whole house is warm, the room PI
  handles that). A manual episode ends with its override (`manual_ended`), unless the
  room is still above the exit threshold: then the automatic detection takes it over
  (trigger `handover`), but only with a trusted room value that was also trusted when the
  manual episode began, no pending sensor fault and the reference gap met. An override
  of kind `stove` with value 0 stops any episode (`manual_stop`).
- **Re-arming**: after `max_active` the level trigger waits until the room has been below
  the exit threshold once (`stove_level_blocked`), but a new fast rise (its window
  restarts at the exit) starts a new episode. After `room_untrusted` the room value must
  be trusted again without a break for `reentry_hold_s` (15 min; 0: at once) before an
  automatic entry (`stove_reentry_wait`, `stove_trusted_since`). After a manual stop the
  detection re-arms only once the room has cooled below the exit threshold
  (`stove_blocked`). A manual request is never held back.
- **Record**: the state lives in `OvenbirdState` (`stove_source`, `stove_trigger`,
  `stove_since`, `stove_entry_c`, `stove_integral_k`, `stove_blocked`,
  `stove_level_blocked`, `stove_reentry_wait`, `stove_trusted_since`, the fast-rise
  window `stove_low_c`/`stove_low_at`/`stove_high_c`/`stove_high_at`/`stove_predip_c`,
  the sensor-fault window `stove_step_low_c`/`stove_step_low_at` and `stove_fault`),
  carried over configuration changes (a
  configuration without stove mode ends the episode). With stove mode configured every
  decision adds `stove_state` (`active` | `inactive`), `stove_event` (`entered` | `exited`
  on the tick it happened), `stove_exit`, `stove_started` (ISO time), `stove_active_s`,
  `stove_until` (manual), `stove_enter_c`, `stove_exit_c`, `stove_rise_k`,
  `stove_jump_k`, `stove_fault`, `stove_backoff_k` (effective), `stove_reference_c`,
  `stove_reference_floor_c`, `stove_reference_gap_k` (room minus reference) and
  `stove_reference_share`, plus the
  `stove` term with a note; the decision note starts with "Wood-stove mode (auto, level at
  23.4 °C, 1 h 20 m): room PI paused with the integrator held at +0.4 K; …".

## Model plan

A plan slice from the learned house model (`PlanSource.MODEL`, produced by
`ovenbird_core.control.planner.plan_offset`; `docs/decisions/2026-11-27-learned-model-in-controller.md`)
is the one path by which the learned model reaches the controller. It only shifts the room
target of an active room feedback, by at most `ModelPlanConfig.max_setback_k` below and
`max_preheat_k` above comfort (defaults 0.5 K and 0.3 K; absolute ceilings 1.0 K and 0.5 K).
There is no water term.

- The controller clamps every model slice to those bounds, whatever the planner sent, and
  gives it the reason of its sign (`plan_setback` or `plan_preheat`). The ladder level is
  `model_plan`: richer than `rule_plan` (it predicts the house), poorer than
  `optimiser_plan` (no prices, no heat pump model).
- A slice has no effect at all (no water term; ladder and reason as without a plan) from the
  first tick on which the room value is not trusted, a wood-stove episode is active, the
  wood-stove detection is still waiting after an episode or a sensor fault, or the slice is
  valid for longer than 3600 s (`MODEL_PLAN_MAX_SLICE_S`), so a plan cannot outlive its
  planner by more than that. Start ramp, cycling floor, rounding, dwell and the safety clamps act
  after it as always.
- `controller_state` carries `model_plan_requested_k` (what the planner sent),
  `model_plan_applied_k` (after the bounds, 0 while ignored) and `model_plan_ignored`
  (`room_untrusted`, `stove_active`, `stove_recovery`, `slice_too_long`, or `null`), only on
  ticks that were given a model slice; every other record is unchanged. A replay of such a
  record feeds the slice back from `model_plan_requested_k`, valid for that tick, so it
  reproduces the recorded setpoint (`ovenbird.replay.stepping.recorded_model_plan`).
- The service side (``control_model_use`` `off` / `shadow` / `on`, the guards, the quarter-hour
  cadence, what is recorded) is `ovenbird.control.modelplan`; see `docs/api-v1.md`
  (`insight/house/control`). With `shadow` the controller is never given the slice.

## Vocabulary

`IntentKind`:

```text
water_setpoint, max_pump_duty, quiet_mode
```

`LadderLevel`, from the richest to the most defensive behaviour:

```text
optimiser_plan, model_plan, rule_plan, schedule_curve_feedback, curve_only, hold, refuse
```

`ReasonCode`, a closed `StrEnum`:

```text
curve, room_feedback, start_ramp, cycling_protect, defrost_freeze, dhw_freeze, room_stale,
room_implausible, heishamon_dead, mode_mismatch, mode_unknown, mode_off, inputs_missing,
safety_clamp, deadband_hold, dwell_hold, override, override_missing, plan_preheat,
plan_setback, pump_duty_heat, pump_duty_idle, quiet_schedule, stove
```

`RoomProfile`:

```text
periodic, on_change
```

## Safety envelope

`SafetyLimits` (max supply temperature per emitter, min setpoint, envelope band around a
conservative curve) is applied **inside** every controller's step as the last stage and
recorded as a term; harnesses assert it is never violated.

The envelope is the one the stateless fallback rule on HeishaMon enforces from the raw
`Outside_Temp`: `SafetyLimits.bounds(outside)` is the band the rule accepts, and
`SafetyLimits.fallback_setpoint(outside)` what it writes when the setpoint lies outside
it (the envelope curve at that temperature, within the band; `fallback_values` gives the
integers the rule's rounding may produce). Every decision with a fresh `Outside_Temp`
clamps with the same bounds at the same raw reading: a controlled one as its last
stage, a `hold` by clamping the repeated setpoint (the clamp is its `binding` and the
note says "safety bound envelope_max clamps the held 36 → 34 °C"; without a fresh
`Outside_Temp` the last setpoint is repeated as is). So a value of ovenbird's lies
outside the rule's band only when the outside temperature moved since it was decided,
or while `Outside_Temp` is stale. The service's command
adapter, when the owner declared the rule installed, recognises such a correction
(ovenbird's verified value outside the band at the current `Outside_Temp`, the pump now
reporting one of `fallback_values`) as the rule's, not a foreign writer: it journals an
`envelope_correction`, counts it and adopts the value; it raises `envelope_mismatch`
once when ovenbird's value already lay outside the band at the outside temperature it
was set at. Without the declaration every read-back difference stays a foreign
writer.
