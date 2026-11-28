import type {
  Alarm,
  AlarmEvent,
  AlarmsResponse,
  AuditEvent,
  AwayStatus,
  BoostStatus,
  CommandEvent,
  ControlStatus,
  Decision,
  DecisionRecord,
  DecisionSeries,
  Mode,
  Monitor,
  StateValue,
  StoveStatus,
  SummerStatus,
  Term,
} from '../src/lib/core/types';

const MINUTE = 60_000;
const CYCLE_MIN = 360;

export type Scenario =
  | 'normal'
  | 'curve_only'
  | 'ramp'
  | 'cycling'
  | 'clamp_high'
  | 'clamp_low'
  | 'dwell'
  | 'defrost'
  | 'hold'
  | 'refuse'
  | 'override';

export const TARGET_C = 21.0;

const CURVE_POINTS: [number, number][] = [
  [-10, 39],
  [0, 34],
  [15, 25],
];

/**
 * Water temperature of the mock heating curve at an outside temperature.
 */
export function curveWater(outside: number): number {
  const first = CURVE_POINTS[0] as [number, number];
  const last = CURVE_POINTS[CURVE_POINTS.length - 1] as [number, number];
  if (outside <= first[0]) return first[1];
  if (outside >= last[0]) return last[1];
  for (let i = 1; i < CURVE_POINTS.length; i += 1) {
    const a = CURVE_POINTS[i - 1] as [number, number];
    const b = CURVE_POINTS[i] as [number, number];
    if (outside <= b[0]) return a[1] + ((b[1] - a[1]) * (outside - a[0])) / (b[0] - a[0]);
  }
  return last[1];
}

/**
 * Scenario active at a minute of the 6-hour mock cycle.
 */
export function scenarioAt(minuteOfCycle: number): Scenario {
  const m = minuteOfCycle;
  if (m < 40) return 'ramp';
  if (m >= 60 && m < 80) return 'dwell';
  if (m >= 100 && m < 120) return 'cycling';
  if (m >= 150 && m < 170) return 'curve_only';
  if (m >= 200 && m < 225) return 'clamp_high';
  if (m >= 250 && m < 260) return 'defrost';
  if (m >= 280 && m < 290) return 'clamp_low';
  if (m >= 300 && m < 305) return 'hold';
  if (m >= 330 && m < 335) return 'refuse';
  if (m >= 340 && m < 350) return 'override';
  return 'normal';
}

const round1 = (value: number) => Math.round(value * 10) / 10;
const roundHalfUp = (value: number) => Math.floor(value + 0.5);

/**
 * Outside temperature: a daily swing peaking mid-afternoon (local time) on a slow multi-day drift.
 */
export function outsideAt(ms: number): number {
  const date = new Date(ms);
  const hour = date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600;
  const daily = 2.5 * Math.sin(((hour - 8.5) / 24) * 2 * Math.PI);
  const drift = 2 * Math.sin(ms / (3.7 * 86_400_000));
  return 3 + daily + drift;
}

export function roomAt(ms: number): number {
  return 20.8 + 0.4 * Math.sin(ms / 5_400_000);
}

export function configVersionAt(ms: number, nowMs: number): number {
  const changeAt = Math.floor((nowMs - 7 * 3_600_000) / 3_600_000) * 3_600_000;
  return ms < changeAt ? 11 : 12;
}

function term(name: string, raw: number, value: number, unit: string, note: string): Term {
  return { name, raw, value, unit, note };
}

interface Built {
  record: DecisionRecord;
  scenario: Scenario;
}

export const ROOM_SIGNAL = 'ha/sensor.living_room_temperature';

/**
 * A wood-stove episode in the mock: automatic (level trigger) or started by hand, with its start,
 * optional end (manual) and the room value at entry.
 */
export interface StoveEpisode {
  source: 'auto' | 'manual';
  trigger: 'level' | 'rise' | 'manual' | 'handover';
  sinceMs: number;
  untilMs: number | null;
  entryC: number;
}

/**
 * Wood-stove mode as the mock controller sees it: configured or not, the current episode and the
 * waiting state of the detection when no episode runs.
 */
export interface StoveMock {
  enabled: boolean;
  auto: boolean;
  backoffK: number;
  episode: StoveEpisode | null;
  waiting: 'blocked' | 'level_blocked' | 'reentry_wait' | null;
}

export const STOVE_ROOM_C = 23.6;
const STOVE_ENTER_K = 1.5;
const STOVE_EXIT_K = 1.0;

/**
 * Whether the episode covers `ms`.
 */
export function stoveActiveAt(stove: StoveMock | null | undefined, ms: number): boolean {
  const episode = stove?.episode;
  if (!stove?.enabled || !episode) return false;
  return ms >= episode.sinceMs && (episode.untilMs === null || ms < episode.untilMs);
}
export const ROOM_STALE_S = 9000;
const ROOM_QUANTUM_K = 0.2;
const KP = 2;

export interface RoomFacts {
  value: number;
  heldS: number;
  aliveS: number;
  stale: boolean;
}

/**
 * Room input at `ms` as the controller sees it: an on-change sensor whose value is held between
 * reports, kept alive by its humidity; `stale` when the scenario silenced it for 2.5 h.
 */
export function roomFacts(ms: number, stale = false): RoomFacts {
  const seconds = Math.floor(ms / 1000);
  if (stale)
    return {
      value: round1(roomAt(ms - ROOM_STALE_S * 1000)),
      heldS: ROOM_STALE_S + 1800,
      aliveS: ROOM_STALE_S,
      stale,
    };
  return {
    value: round1(roomAt(ms)),
    heldS: 1200 + (seconds % 10_800),
    aliveS: 30 + (seconds % 600),
    stale,
  };
}

/**
 * A duration as the controller writes it in notes: "45 s", "4 min", "2 h 10 m".
 */
export function durationText(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} h ${String(minutes).padStart(2, '0')} m`;
}

const signed = (value: number) => {
  const r = Math.round(value * 10) / 10 + 0;
  return `${r >= 0 ? '+' : ''}${r.toFixed(1)}`;
};

function roomStatus(room: RoomFacts, cooling: boolean): string {
  const text = `held value ${room.value.toFixed(1)} °C (${durationText(room.heldS)}), device alive (humidity ${durationText(room.aliveS)} ago), ±${ROOM_QUANTUM_K.toFixed(1)} K`;
  return cooling ? `${text}, cooling authority 100 %` : text;
}

/**
 * Build a decision record following the controller's term semantics for the scenario at `ms`.
 */
export function buildRecord(
  ms: number,
  mode: Mode = 'auto',
  options: {
    roomStale?: boolean;
    stove?: StoveMock | null;
    targetC?: number;
  } = {},
): Built {
  const comfort = options.targetC ?? TARGET_C;
  const minute = Math.floor(ms / MINUTE);
  const cycleMinute = ((minute % CYCLE_MIN) + CYCLE_MIN) % CYCLE_MIN;
  const cycleScenario = scenarioAt(cycleMinute);
  const scenario: Scenario =
    options.roomStale && !['hold', 'refuse', 'override'].includes(cycleScenario)
      ? 'curve_only'
      : cycleScenario;
  const roomStale = scenario === 'curve_only';
  const target = round1(comfort);
  const stoveConfig = options.stove?.enabled ? options.stove : null;
  const stoveOn = stoveActiveAt(stoveConfig, ms) && !roomStale;
  const roomBase = roomFacts(ms, roomStale);
  const facts = stoveOn ? { ...roomBase, value: STOVE_ROOM_C } : roomBase;
  const wall = new Date(minute * MINUTE).toISOString();
  const outside = round1(outsideAt(ms));
  const outsideFiltered = round1(outside - 0.2);
  const curve = curveWater(outsideFiltered);
  const room = facts.value;
  const error = round1(target - room);
  const envelopeHigh = curveWater(outside) + 5;
  const envelopeLow = Math.max(25, curveWater(outside) - 6);

  const base = (
    ladder: string,
    reason: string,
    note: string,
    terms: Term[],
    setpoint: number | null,
    preRound: number | null,
    binding: string | null,
    extra: Record<string, StateValue> = {},
  ): Built => ({
    scenario,
    record: {
      schema: 1,
      at: { monotonic: minute * 60, wall },
      controller: 'ovenbird',
      mode,
      ladder,
      terms,
      pre_round: preRound,
      setpoint,
      binding,
      flip_distance: preRound === null || setpoint === null ? null : 0.3,
      flip_input: preRound === null ? null : 'room_temperature',
      inputs_used: [
        {
          signal: 'main/Outside_Temp',
          value: outside,
          age: 40,
          fresh: true,
          source: 'heishamon',
          issued: null,
        },
        {
          signal: 'main/Main_Outlet_Temp',
          value: 31.5,
          age: 40,
          fresh: true,
          source: 'heishamon',
          issued: null,
        },
        {
          signal: 'main/Z1_Water_Target_Temp',
          value: setpoint,
          age: 40,
          fresh: true,
          source: 'actual',
          issued: null,
        },
        {
          signal: 'room_temperature',
          value: room,
          age: facts.aliveS,
          fresh: !facts.stale,
          source: 'room',
          issued: null,
        },
      ],
      controller_state: {
        crosscheck_latched_c: null,
        crosscheck_offset_k: 0.99,
        crosscheck_since: null,
        dwell_remaining_s: 0,
        frozen_by: null,
        integral_k: -0.6,
        integral_at_life_k: -0.6,
        outside_filtered_c: outsideFiltered,
        pump_duty: scenario === 'defrost' ? null : 159,
        quiet_level: null,
        ramp_phase: 'idle',
        room_alive_by: 'room_humidity',
        room_alive_s: facts.aliveS,
        room_authority: 1,
        room_crosscheck_deviation_k: -0.69,
        room_crosscheck_threshold_k: 1.5,
        room_error_k: error,
        room_held_s: facts.heldS,
        room_lost_at: facts.stale ? minute * 60 - facts.aliveS : null,
        room_plausible: true,
        room_profile: 'on_change',
        room_quantum_k: ROOM_QUANTUM_K,
        room_target_c: target,
        running: true,
        safety_high_c: round1(envelopeHigh),
        safety_low_c: round1(envelopeLow),
        setpoint,
        stove_blocked: false,
        stove_entry_c: null,
        stove_event: null,
        stove_exit: null,
        stove_fault: false,
        stove_high_c: null,
        stove_integral_k: null,
        stove_level_blocked: false,
        stove_low_c: null,
        stove_predip_c: null,
        stove_reentry_wait: false,
        stove_since: null,
        stove_source: null,
        stove_step_low_c: null,
        stove_trigger: null,
        stove_trusted_since: null,
        ...extra,
      },
      reason,
      note,
      intents:
        setpoint === null
          ? []
          : [
              { kind: 'water_setpoint', value: setpoint, reason },
              ...(scenario === 'defrost'
                ? []
                : [{ kind: 'max_pump_duty', value: 159, reason: 'pump_duty_heat' }]),
            ],
      actor: scenario === 'override' ? 'admin' : null,
    },
  });

  const wave = Math.sin(ms / 2_400_000);
  let feedback = round1(0.5 * wave - 0.4);
  let ramp = 0;
  let cycling = 0;
  let override = 0;
  let reason = 'room_feedback';
  let binding: string | null = null;
  const extra: Record<string, StateValue> = {};
  const noteParts: string[] = [];

  if (scenario === 'hold') {
    return base(
      'hold',
      'inputs_missing',
      'Holding: a required input is missing; keeping the last intents.',
      [],
      30,
      null,
      null,
      { frozen_by: 'inputs_missing' },
    );
  }
  if (scenario === 'refuse') {
    return base(
      'refuse',
      'heishamon_dead',
      'Refusing control: no live HeishaMon heartbeat; no intents, integrator frozen.',
      [],
      null,
      null,
      null,
      { frozen_by: 'heishamon_dead' },
    );
  }

  const terms: Term[] = [
    term(
      'curve',
      curve,
      curve,
      '°C',
      `curve at ${outsideFiltered.toFixed(2)} °C filtered outside (${Math.round(outside)} °C raw)`,
    ),
  ];
  const curveText = `the curve's ${curve.toFixed(1)} °C at ${outsideFiltered.toFixed(1)} °C outside`;
  if (scenario === 'curve_only') {
    reason = 'room_stale';
    feedback = 0;
    extra['frozen_by'] = 'room_stale';
  }
  if (stoveOn) {
    reason = 'stove';
    feedback = 0;
    extra['frozen_by'] = 'stove';
  }
  if (scenario === 'clamp_high') feedback = 6;
  if (scenario === 'clamp_low') feedback = -7;
  const feedbackRaw = scenario === 'clamp_high' ? 7.2 : scenario === 'clamp_low' ? -8.4 : feedback;
  const proportional = round1(KP * error);
  const status = roomStatus(facts, feedback < 0);
  const episode = stoveConfig?.episode ?? null;
  terms.push(
    term(
      'room_feedback',
      feedbackRaw,
      feedback,
      'K',
      roomStale
        ? `room sensor ${ROOM_SIGNAL} stale (last proof of life ${durationText(facts.aliveS)} ago); feedback off (curve only)`
        : stoveOn
          ? `paused by wood-stove mode; integrator held at ${signed(-0.6)} K; ${status}`
          : `room ${room.toFixed(2)} °C vs target ${target.toFixed(2)} °C: P ${signed(proportional)} K + I ${signed(feedbackRaw - proportional)} K; ${status}`,
    ),
  );
  if (roomStale) noteParts.push(`No usable room temperature, so ${curveText} alone`);
  else if (stoveOn && episode)
    noteParts.push(
      `Wood-stove mode (${episode.source}, ${episode.trigger}${episode.source === 'auto' ? ` at ${episode.entryC.toFixed(1)} °C` : ''}, ${durationText((ms - episode.sinceMs) / 1000)}): room PI paused with the integrator held at ${signed(-0.6)} K; the curve's ${curve.toFixed(1)} °C at ${outsideFiltered.toFixed(1)} °C outside lowered by ${(stoveConfig?.backoffK ?? 3).toFixed(1)} K`,
    );
  else
    noteParts.push(
      `Room ${Math.abs(error).toFixed(1)} K ${error > 0 ? 'below' : 'above'} target; PI adds ${signed(feedback)} K to ${curveText}`,
      status,
    );
  terms.push(term('plan', 0, 0, 'K', stoveOn ? 'paused by wood-stove mode' : 'no plan'));
  let stoveValue = 0;
  if (stoveConfig) {
    const enter = target + STOVE_ENTER_K;
    const exit = enter - STOVE_EXIT_K;
    stoveValue = stoveOn ? -stoveConfig.backoffK : 0;
    const where = `room ${room.toFixed(1)} °C`;
    const waitNote =
      stoveConfig.waiting === 'blocked'
        ? `inactive, detection re-arms below ${exit.toFixed(1)} °C (${where})`
        : stoveConfig.waiting === 'reentry_wait'
          ? `inactive, detection re-arms after the room value has been trusted for 15 min (${where})`
          : stoveConfig.waiting === 'level_blocked'
            ? `inactive, only a new fast rise enters until the room has been below ${exit.toFixed(1)} °C (${where})`
            : `inactive (${where}; enters at ${enter.toFixed(1)} °C)`;
    terms.push(
      term(
        'stove',
        stoveValue,
        stoveValue,
        'K',
        stoveOn ? `back-off ${stoveConfig.backoffK.toFixed(1)} K` : waitNote,
      ),
    );
    Object.assign(extra, {
      stove_state: stoveOn ? 'active' : 'inactive',
      stove_source: stoveOn && episode ? episode.source : null,
      stove_trigger: stoveOn && episode ? episode.trigger : null,
      stove_started: stoveOn && episode ? new Date(episode.sinceMs).toISOString() : null,
      stove_active_s: stoveOn && episode ? Math.round((ms - episode.sinceMs) / 1000) : null,
      stove_until:
        stoveOn && episode?.untilMs != null ? new Date(episode.untilMs).toISOString() : null,
      stove_entry_c: stoveOn && episode ? episode.entryC : null,
      stove_integral_k: stoveOn ? -0.6 : null,
      stove_enter_c: round1(enter),
      stove_exit_c: round1(exit),
      stove_backoff_k: stoveOn ? stoveConfig.backoffK : null,
      stove_blocked: stoveConfig.waiting === 'blocked',
      stove_level_blocked: stoveConfig.waiting === 'level_blocked',
      stove_reentry_wait: stoveConfig.waiting === 'reentry_wait',
    });
  }
  if (scenario === 'ramp') {
    ramp = -round1(3 * (1 - cycleMinute / 40));
    reason = 'start_ramp';
    binding = null;
    extra['ramp_phase'] = cycleMinute < 20 ? 'hold' : 'release';
  }
  const rampPhase = cycleMinute < 20 ? 'hold' : 'release';
  terms.push(
    term(
      'start_ramp',
      ramp,
      ramp,
      'K',
      ramp === 0
        ? 'no ramp'
        : `${rampPhase} phase, cap ${(curve + ramp).toFixed(2)} °C (${cycleMinute + 2} min run)`,
    ),
  );
  if (scenario === 'override') {
    const sum = curve + feedback + ramp;
    override = 33 - sum;
    terms.push(term('override', override, override, 'K', 'setpoint 33 °C by admin'));
    reason = 'override';
    binding = 'override';
  }
  if (scenario === 'cycling') {
    cycling = 0.8;
    reason = 'cycling_protect';
    binding = 'cycling_floor';
    terms.push(
      term(
        'cycling_floor',
        0.8,
        0.8,
        'K',
        `min-run window: keep ≥ ${(curve + feedback + 0.8).toFixed(2)} °C (outlet 31.5 °C)`,
      ),
    );
  } else {
    terms.push(term('cycling_floor', 0, 0, 'K', 'outside min-run window'));
  }

  const rawSum = curve + feedback + stoveValue + ramp + override + cycling;
  const preRound = Math.min(Math.max(rawSum, envelopeLow), envelopeHigh);
  terms.push(
    term(
      'safety',
      rawSum,
      preRound,
      '°C',
      `allowed [${envelopeLow.toFixed(2)}, ${envelopeHigh.toFixed(2)}] °C at ${Math.round(outside)} °C outside`,
    ),
  );
  if (scenario === 'clamp_high' || scenario === 'clamp_low') {
    reason = 'safety_clamp';
    binding = scenario === 'clamp_high' ? 'envelope_max' : 'envelope_min';
  }
  let setpoint = roundHalfUp(preRound);
  if (scenario === 'dwell') {
    setpoint = roundHalfUp(preRound - 1.2);
    reason = 'dwell_hold';
    binding = 'dwell';
    extra['dwell_remaining_s'] = 720;
  }
  if (scenario === 'defrost') {
    setpoint = roundHalfUp(preRound + 1.2);
    reason = 'defrost_freeze';
    binding = 'defrost_hold';
  }
  if (scenario === 'defrost')
    noteParts.push(
      'defrost in progress: integrator frozen, no decrease',
      'defrost: the pump sets its own duty; no duty command',
    );
  if (ramp < 0) noteParts.push(`start ramp caps at ${(curve + ramp).toFixed(1)} °C`);
  if (scenario === 'cycling') noteParts.push(`cycling floor raises to ${setpoint} °C`);
  if (scenario === 'override') noteParts.push('override by admin: 33 °C');
  if (preRound !== rawSum)
    noteParts.push(`safety clamps ${rawSum.toFixed(1)} to ${preRound.toFixed(1)} °C`);
  const outcome =
    scenario === 'dwell'
      ? `setpoint stays ${setpoint} °C, dwell time not over (12 min left)`
      : scenario === 'defrost'
        ? `setpoint stays ${setpoint} °C, no decrease during defrost`
        : `setpoint ${setpoint} °C`;
  const note = `${noteParts.join('; ')}; ${outcome}.`;
  return base('schedule_curve_feedback', reason, note, terms, setpoint, preRound, binding, extra);
}

/**
 * The configuration a decision at a moment ran with: its version and comfort target.
 */
export interface ConfigAt {
  version: number;
  comfortC: number;
}

export interface DecisionOptions {
  roomStaleSince?: number | null;
  stove?: StoveMock | null;
  configAt?: (ms: number) => ConfigAt;
}

/**
 * Build one full decision entry as served by `api/v1/decisions`: the arbiter compares the intents
 * with what the pump reports (the previous tick's setpoint), and a changed setpoint queues a
 * command.
 */
export function makeDecision(
  ms: number,
  nowMs: number,
  mode: Mode = 'auto',
  options: DecisionOptions = {},
): Decision {
  const stale = (t: number) =>
    options.roomStaleSince !== null &&
    options.roomStaleSince !== undefined &&
    t >= options.roomStaleSince;
  const config = options.configAt?.(ms);
  const { record, scenario } = buildRecord(ms, mode, {
    roomStale: stale(ms),
    stove: options.stove,
    targetC: config?.comfortC,
  });
  const previous = buildRecord(ms - MINUTE, mode, {
    roomStale: stale(ms - MINUTE),
    stove: options.stove,
  }).record.setpoint;
  const minute = Math.floor(ms / MINUTE) * MINUTE;
  const at = new Date(minute).toISOString();
  const send =
    mode === 'auto' &&
    record.setpoint !== null &&
    previous !== null &&
    previous !== record.setpoint;
  const arbiter =
    record.setpoint === null
      ? []
      : [
          {
            kind: 'water_setpoint',
            intent: record.setpoint,
            actual: send ? previous : record.setpoint,
            action: send ? 'send' : 'none',
            reason: send ? `pump reports ${previous}` : 'already applied',
          },
          ...(scenario === 'defrost'
            ? []
            : [
                {
                  kind: 'max_pump_duty',
                  intent: 159,
                  actual: 159,
                  action: 'none',
                  reason: 'already applied',
                },
              ]),
        ];
  return {
    at,
    controller: record.controller,
    mode,
    ladder: record.ladder,
    reason: record.reason,
    setpoint: record.setpoint,
    note: record.note,
    arbiter,
    commands:
      send && record.setpoint !== null
        ? [
            {
              at,
              kind: 'water_setpoint',
              value: record.setpoint,
              status: 'queued',
              attempt: 0,
              detail: 'queued',
              topic: COMMAND_TOPIC['water_setpoint'] as string,
              payload: commandPayload('water_setpoint', record.setpoint),
            },
          ]
        : [],
    record,
    config_version: config?.version ?? configVersionAt(ms, nowMs),
  };
}

/**
 * Decisions in a window, oldest first, newest `limit` kept.
 */
export function makeDecisions(
  fromMs: number,
  toMs: number,
  limit: number,
  nowMs: number,
  options: DecisionOptions = {},
): Decision[] {
  const first = Math.ceil(fromMs / MINUTE) * MINUTE;
  const all: Decision[] = [];
  for (let t = first; t <= toMs; t += MINUTE) all.push(makeDecision(t, nowMs, 'auto', options));
  return all.slice(-limit);
}

/**
 * Columnar series for the window, thinned to `step` seconds (0 = every tick).
 */
export function makeSeries(
  fromMs: number,
  toMs: number,
  stepSeconds: number,
  nowMs: number,
  stove: StoveMock | null = null,
  configAt?: (ms: number) => ConfigAt,
): DecisionSeries {
  const stepMs = Math.max(stepSeconds, 60) * 1000;
  const out: DecisionSeries = {
    from: new Date(fromMs).toISOString(),
    to: new Date(toMs).toISOString(),
    step: stepSeconds,
    at: [],
    setpoint: [],
    pre_round: [],
    curve: [],
    room_feedback: [],
    plan: [],
    start_ramp: [],
    cycling_floor: [],
    stove: [],
    other: [],
    safety_delta: [],
    safety_low: [],
    safety_high: [],
    reason: [],
    binding: [],
    ladder: [],
    config_version: [],
  };
  const first = Math.ceil(fromMs / stepMs) * stepMs;
  for (let t = first; t <= toMs; t += stepMs) {
    const config = configAt?.(t);
    const { record } = buildRecord(t, 'auto', {
      stove,
      targetC: config?.comfortC,
    });
    const named = (name: string) => record.terms.find((item) => item.name === name)?.value ?? null;
    const safety = record.terms.find((item) => item.name === 'safety');
    const state = record.controller_state;
    out.at.push(record.at.wall);
    out.setpoint.push(record.setpoint);
    out.pre_round.push(record.pre_round);
    out.curve.push(named('curve'));
    out.room_feedback.push(named('room_feedback'));
    out.plan.push(named('plan'));
    out.start_ramp.push(named('start_ramp'));
    out.cycling_floor.push(named('cycling_floor'));
    out.stove?.push(record.terms.length ? (named('stove') ?? 0) : null);
    out.other.push(record.terms.length ? (named('boost') ?? 0) + (named('override') ?? 0) : null);
    out.safety_delta.push(safety ? safety.value - safety.raw : null);
    out.safety_low.push(typeof state['safety_low_c'] === 'number' ? state['safety_low_c'] : null);
    out.safety_high.push(
      typeof state['safety_high_c'] === 'number' ? state['safety_high_c'] : null,
    );
    out.reason.push(record.reason);
    out.binding.push(record.binding);
    out.ladder.push(record.ladder);
    out.config_version.push(config?.version ?? configVersionAt(t, nowMs));
  }
  return out;
}

export interface MockState {
  paused: boolean;
  configVersion?: number;
  holdReleased: boolean;
}

export const initialState = (): MockState => ({ paused: false, holdReleased: false });

const ROOM_SILENCE_LIMIT_S = 86_400;

/**
 * The `room_sensor_silent` monitor for the room sensor's last proof of life, as the service words
 * it: ok with the time since the last report, active beyond the silence limit.
 */
export function roomSilentMonitor(aliveS: number, nowMs: number): Monitor {
  const active = aliveS > ROOM_SILENCE_LIMIT_S;
  return {
    code: 'room_sensor_silent',
    severity: 'warning',
    status: active ? 'active' : 'ok',
    message: active
      ? `no report from the room sensor or its liveness signals for ${Math.round(aliveS / 60)} min (limit ${ROOM_SILENCE_LIMIT_S / 60} min)`
      : `last report ${Math.round(aliveS / 60)} min ago`,
    value: aliveS,
    limit: ROOM_SILENCE_LIMIT_S,
    unit: 's',
    direction: 'above',
    since: active ? new Date(nowMs - (aliveS - ROOM_SILENCE_LIMIT_S) * 1000).toISOString() : null,
  };
}

/**
 * The `setpoint_above_max` monitor for the water target the pump reports.
 */
export function setpointMonitor(waterC: number): Monitor {
  return {
    code: 'setpoint_above_max',
    severity: 'critical',
    status: 'ok',
    message: `water setpoint ${waterC} °C within 40 °C`,
    value: waterC,
    limit: 40,
    unit: '°C',
    direction: 'above',
    since: null,
  };
}

/**
 * Mock control status with a foreign-writer hold until released. `pumpWaterC` is the water target
 * the pump reports (the `setpoint_above_max` monitor), 29 °C when not given. Every monitor is ok:
 * the scenarios raise their own.
 */
const NO_STOVE: StoveStatus = {
  enabled: false,
  auto: false,
  active: false,
  source: null,
  trigger: null,
  since: null,
  entry_c: null,
  integral_k: null,
  blocked: false,
  level_blocked: false,
  reentry_wait: false,
  backoff_k: null,
  enter_c: null,
  exit_c: null,
  reference_c: null,
  request: null,
};

const NO_BOOST: BoostStatus = {
  enabled: true,
  active: false,
  paused: null,
  shift_k: null,
  target_c: null,
  remaining_s: null,
  default_s: 7200,
  default_k: 1,
  request: null,
};

const NO_AWAY: AwayStatus = {
  enabled: true,
  active: false,
  phase: null,
  paused: null,
  target_c: null,
  until: null,
  comfort_from: null,
  default_target_c: 16,
  default_lead_s: 21_600,
  request: null,
};

const NO_SUMMER: SummerStatus = {
  enabled: false,
  active: false,
  mean_c: null,
  mean_tau_s: null,
  off_c: null,
  on_c: null,
  warming_up: false,
};

export type MockControl = ControlStatus & { safety: NonNullable<ControlStatus['safety']> };

export function makeControl(nowMs: number, state: MockState, pumpWaterC = 29): MockControl {
  const holdActive = !state.holdReleased;
  const alarms: Alarm[] = [
    {
      code: 'heishamon_restarted',
      severity: 'info',
      message: 'HeishaMon restarted 3 h ago',
      since: new Date(nowMs - 3 * 3_600_000).toISOString(),
      detail: {},
    },
  ];
  if (holdActive) {
    alarms.unshift({
      code: 'foreign_writer',
      severity: 'warning',
      message: 'Z1 water target changed to 31 by someone else',
      since: new Date(nowMs - 25 * MINUTE).toISOString(),
      detail: {},
    });
  }
  return {
    mode: state.paused ? 'shadow' : 'auto',
    configured_mode: 'auto',
    paused: state.paused,
    reset_pending: false,
    releasing: false,
    controller: 'ovenbird',
    interval_s: 60,
    ticks: 1519,
    restored_state: false,
    publishing: !state.paused,
    refusals: state.paused ? ['control is paused'] : [],
    alarms,
    safety: {
      level: holdActive ? 'warning' : 'ok',
      interval_s: 5,
      monitors: [
        setpointMonitor(pumpWaterC),
        {
          code: 'outlet_overshoot',
          severity: 'critical',
          status: 'ok',
          message: 'Main_Outlet_Temp 30.8 °C against a limit of 45.0 °C',
          value: 30.75,
          limit: 45,
          unit: '°C',
          direction: 'above',
          since: null,
        },
        {
          code: 'low_flow',
          severity: 'critical',
          status: 'ok',
          message: 'Pump_Flow 21.5 l/min with the compressor running (minimum 8.0 l/min)',
          value: 21.5,
          limit: 8,
          unit: 'l/min',
          direction: 'below',
          since: null,
        },
        {
          code: 'pump_error',
          severity: 'critical',
          status: 'ok',
          message: 'No error',
          value: 'No error',
          limit: null,
          unit: null,
          direction: null,
          since: null,
        },
        {
          code: 'backup_heater',
          severity: 'warning',
          status: 'ok',
          message: 'backup heater off',
          value: 0,
          limit: null,
          unit: null,
          direction: null,
          since: null,
        },
        roomSilentMonitor(roomFacts(nowMs).aliveS, nowMs),
      ],
    },
    adapter: state.paused
      ? null
      : {
          setpoint_register: 'setcurves_target_high',
          hold: holdActive ? 'foreign writer' : null,
          hold_until: holdActive ? new Date(nowMs + 35 * MINUTE).toISOString() : null,
          hold_latched: false,
          hold_incidents: holdActive ? 2 : 0,
          safety_hold: [],
          corrections: { recent: 0, limit: 3, window_s: 3600 },
          in_flight: null,
          queued: {},
          verified: { water_setpoint: 29, max_pump_duty: 159 },
          budget: {
            day: new Date(nowMs).toISOString().slice(0, 10),
            used: 12,
            limit: 150,
            safety_reserve: 10,
          },
          counters: {
            sent: 12,
            verified: 12,
            retried: 0,
            failed: 0,
            refused: 0,
            clamped: 0,
            foreign: 1,
            superseded: 0,
            corrections: 0,
            restarts: 0,
          },
        },
    room: {
      signal: 'ha/sensor.living_room_temperature',
      profile: 'on_change',
      step_k: 0.1,
      max_age_s: 86400,
      report_interval_s: 300,
      silence_limit_s: 86400,
      liveness: ['ha/sensor.living_room_humidity'],
      crosscheck: null,
      value: roomFacts(nowMs).value,
      fresh: true,
      held_s: roomFacts(nowMs).heldS,
      alive_s: roomFacts(nowMs).aliveS,
      alive_by: 'ha/sensor.living_room_humidity',
      link_up: true,
      authority: 1,
      plausible: null,
    },
    config_version: state.configVersion ?? configVersionAt(nowMs, nowMs),
    stove: NO_STOVE,
    boost: NO_BOOST,
    away: NO_AWAY,
    summer: NO_SUMMER,
  };
}

/**
 * The alarm journal. With `latched` (scenario `hold:latched`) the second hold has expired and a
 * third foreign write 10 min ago started the hold that is latched, so the journal holds as many
 * holds within 12 h as the adapter counts.
 */
export function makeAlarms(
  nowMs: number,
  state: MockState,
  stove: StoveMock | null = null,
  latched = false,
): AlarmsResponse {
  const control = makeControl(nowMs, state);
  const at = (minutesAgo: number) => new Date(nowMs - minutesAgo * MINUTE).toISOString();
  const episode = stove?.enabled ? stove.episode : null;
  const stoveEvents: AlarmEvent[] = episode
    ? [
        {
          at: new Date(episode.sinceMs).toISOString(),
          code: 'stove_mode',
          severity: 'info',
          event: 'started',
          message:
            episode.source === 'auto'
              ? `wood-stove mode on (auto, level at ${episode.entryC.toFixed(1)} °C)`
              : 'wood-stove mode on (manual)',
          detail: { source: episode.source, trigger: episode.trigger },
        },
      ]
    : [];
  const foreignDetail = {
    setting: 'water_setpoint',
    signal: 'main/Z1_Water_Target_Temp',
    register: 'setcurves_target_high',
    ovenbird_value: 33,
    seen_value: 31,
    seen_since: at(26),
    pump_keeps: 31,
    hold_until: new Date(nowMs + 2100 * 1000).toISOString(),
    latched: false,
    incident: 2,
    at_hold_end: 'write_again',
    controller_wants: 33,
  };
  const latchedEvents: AlarmEvent[] = latched
    ? [
        {
          at: at(15),
          code: 'command_hold',
          severity: 'warning',
          event: 'expired',
          message: 'hold 2 expired (foreign writer)',
          detail: { reason: 'foreign writer', until: null, latched: false, incident: 2 },
        },
        {
          at: at(10),
          code: 'command_hold',
          severity: 'warning',
          event: 'started',
          message: 'hold 3 within 12 h (foreign writer), latched until an operator releases it',
          detail: {
            reason: 'foreign writer',
            until: null,
            ...foreignDetail,
            hold_until: null,
            latched: true,
            incident: 3,
            at_hold_end: 'await_release',
          },
        },
      ]
    : [];
  const events: AlarmEvent[] = [
    ...stoveEvents,
    ...latchedEvents,
    {
      at: at(25),
      code: 'foreign_writer',
      severity: 'warning',
      event: 'raised',
      message: 'Z1 water target changed to 31 by someone else',
      detail: foreignDetail,
    },
    {
      at: at(25),
      code: 'command_hold',
      severity: 'warning',
      event: 'started',
      message: 'hold 2 within 12 h (foreign writer), until the timeout',
      detail: {
        reason: 'foreign writer',
        until: Math.floor(nowMs / 1000) + 2100,
        ...foreignDetail,
      },
    },
    {
      at: at(300),
      code: 'command_hold',
      severity: 'warning',
      event: 'expired',
      message: 'hold 1 expired (foreign writer)',
      detail: { reason: 'foreign writer', until: null, latched: false, incident: 1 },
    },
    {
      at: at(330),
      code: 'command_hold',
      severity: 'warning',
      event: 'started',
      message: 'hold 1 within 12 h (foreign writer)',
      detail: { reason: 'foreign writer', until: null, latched: false, incident: 1 },
    },
    {
      at: at(180),
      code: 'heishamon_restarted',
      severity: 'info',
      event: 'raised',
      message: 'HeishaMon restarted',
      detail: {},
    },
    {
      at: at(600),
      code: 'low_flow',
      severity: 'critical',
      event: 'cleared',
      message: 'Pump_Flow back above 8.0 l/min',
      detail: {},
    },
    {
      at: at(612),
      code: 'low_flow',
      severity: 'critical',
      event: 'raised',
      message: 'Pump_Flow 3.0 l/min with the compressor running (minimum 8.0 l/min)',
      detail: {},
    },
    {
      at: at(3 * 1440 + 125),
      code: 'room_below_floor',
      severity: 'warning',
      event: 'cleared',
      message: 'room back above the comfort floor',
      detail: {},
    },
    {
      at: at(3 * 1440 + 200),
      code: 'room_below_floor',
      severity: 'warning',
      event: 'raised',
      message: 'room 20.1 °C below the comfort floor of 20.5 °C for 1 h',
      detail: {},
    },
    {
      at: at(5 * 1440 + 30),
      code: 'command_hold',
      severity: 'warning',
      event: 'expired',
      message: 'hold 1 expired (foreign writer)',
      detail: { reason: 'foreign writer', until: null, latched: false, incident: 1 },
    },
    {
      at: at(5 * 1440 + 60),
      code: 'command_hold',
      severity: 'warning',
      event: 'started',
      message: 'hold 1 within 12 h (foreign writer)',
      detail: { reason: 'foreign writer', until: null, latched: false, incident: 1 },
    },
  ];
  events.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return {
    from: new Date(nowMs - 24 * 3_600_000).toISOString(),
    to: new Date(nowMs).toISOString(),
    limit: 500,
    active: control.alarms,
    events: state.holdReleased
      ? [
          {
            at: at(1),
            code: 'command_hold',
            severity: 'warning',
            event: 'released',
            message: 'hold released by admin',
            detail: { reason: 'foreign writer', until: null, latched: false, incident: 2 },
          },
          ...events.slice(2),
        ]
      : events,
  };
}

const COMMAND_TOPIC: Record<string, string> = {
  water_setpoint: 'panasonic_heat_pump/commands/SetCurves',
  max_pump_duty: 'panasonic_heat_pump/commands/SetMaxPumpDuty',
};

/**
 * Command payload as the adapter publishes it: the SetCurves JSON for the water setpoint, the
 * bare value otherwise.
 */
function commandPayload(kind: string, value: number): string {
  return kind === 'water_setpoint'
    ? JSON.stringify({ zone1: { heat: { target: { high: value } } } })
    : String(value);
}

/**
 * Command journal with the adapter's own detail texts (queued, "published to <topic>",
 * "applied in N s", "not applied, pump reports N", "hold: <reason>", refusal reasons).
 */
export function makeCommands(nowMs: number): CommandEvent[] {
  const at = (secondsAgo: number) => new Date(nowMs - secondsAgo * 1000).toISOString();
  const rows: [number, string, number, string, number, string][] = [
    [300, 'water_setpoint', 29, 'queued', 0, 'queued'],
    [299, 'water_setpoint', 29, 'sent', 1, 'published to {topic}'],
    [287, 'water_setpoint', 29, 'verified', 1, 'applied in 12 s'],
    [5700, 'water_setpoint', 30, 'queued', 0, 'queued'],
    [5699, 'water_setpoint', 30, 'sent', 1, 'published to {topic}'],
    [5690, 'water_setpoint', 30, 'verified', 1, 'applied in 9 s'],
    [10800, 'max_pump_duty', 159, 'queued', 0, 'queued'],
    [10799, 'max_pump_duty', 159, 'sent', 1, 'published to {topic}'],
    [10791, 'max_pump_duty', 159, 'verified', 1, 'applied in 8 s'],
    [13200, 'max_pump_duty', 120, 'queued', 0, 'queued'],
    [13140, 'max_pump_duty', 120, 'dropped', 0, 'defrost: the pump sets its own duty; not sent'],
    [15600, 'water_setpoint', 31, 'refused', 0, 'control is paused'],
    [15720, 'water_setpoint', 31, 'queued', 0, 'queued'],
    [15719, 'water_setpoint', 31, 'dropped', 0, 'hold: foreign writer'],
    [19860, 'water_setpoint', 32, 'queued', 0, 'queued'],
    [19859, 'water_setpoint', 32, 'sent', 1, 'published to {topic}'],
    [19800, 'water_setpoint', 32, 'retry', 1, 'not applied, pump reports 31'],
    [19799, 'water_setpoint', 32, 'sent', 2, 'published to {topic}'],
    [19740, 'water_setpoint', 32, 'failed', 2, 'not applied after 2 attempts, pump reports 31'],
    [2 * 86400 + 600, 'water_setpoint', 33, 'queued', 0, 'queued'],
    [2 * 86400 + 599, 'water_setpoint', 33, 'sent', 1, 'published to {topic}'],
    [2 * 86400 + 588, 'water_setpoint', 33, 'verified', 1, 'applied in 11 s'],
    [4 * 86400 + 900, 'max_pump_duty', 102, 'queued', 0, 'queued'],
    [4 * 86400 + 899, 'max_pump_duty', 102, 'sent', 1, 'published to {topic}'],
    [4 * 86400 + 890, 'max_pump_duty', 102, 'verified', 1, 'applied in 9 s'],
  ];
  return rows
    .map(([ago, kind, value, status, attempt, detail]) => {
      const topic = COMMAND_TOPIC[kind] ?? 'panasonic_heat_pump/commands';
      return {
        at: at(ago),
        kind,
        value,
        status,
        attempt,
        detail: detail.replace('{topic}', topic),
        topic,
        payload: commandPayload(kind, value),
      };
    })
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

export function makeAudit(
  nowMs: number,
  stove: { on: boolean; untilMs: number | null; atMs: number; actor: string } | null = null,
): AuditEvent[] {
  const at = (minutesAgo: number) => new Date(nowMs - minutesAgo * MINUTE).toISOString();
  const stoveEvents: AuditEvent[] = stove
    ? [
        {
          at: new Date(stove.atMs).toISOString(),
          actor: stove.actor,
          source_ip: '127.0.0.1',
          action: 'stove_request',
          detail: {
            on: stove.on,
            until: stove.untilMs === null ? null : new Date(stove.untilMs).toISOString(),
            actor: stove.actor,
            at: new Date(stove.atMs).toISOString(),
          },
        },
      ]
    : [];
  const older: AuditEvent[] = [
    {
      at: at(30 * 60),
      actor: 'admin from 192.168.1.20',
      source_ip: '192.168.1.20',
      action: 'config_apply',
      detail: {
        version: 11,
        changed: [
          { field: 'control_comfort_c', from: 20.6, to: 21.0 },
          { field: 'control_dwell_s', from: null, to: 1200 },
        ],
        comment: 'Longer wait time',
      },
    },
    {
      at: at(72 * 60),
      actor: 'admin from 192.168.1.20',
      source_ip: '192.168.1.20',
      action: 'config_apply',
      detail: {
        version: 10,
        changed: [{ field: 'control_comfort_c', from: 21, to: 21.4 }],
        comment: 'A bit warmer',
      },
    },
  ];
  return [
    ...stoveEvents,
    {
      at: at(8),
      actor: 'admin from 192.168.1.20',
      source_ip: '192.168.1.20',
      action: 'mode_resume',
      detail: {},
    },
    {
      at: at(14),
      actor: 'admin from 192.168.1.20',
      source_ip: '192.168.1.20',
      action: 'mode_pause',
      detail: { reason: 'checking the remote' },
    },
    {
      at: at(130),
      actor: 'admin from 192.168.1.20',
      source_ip: '192.168.1.20',
      action: 'hold_release',
      detail: {
        reason: 'checked the remote',
        until: null,
        latched: false,
        incident: 2,
      },
    },
    {
      at: at(420),
      actor: 'admin from 192.168.1.20',
      source_ip: '192.168.1.20',
      action: 'config_apply',
      detail: {
        version: 12,
        changed: [{ field: 'control_comfort_c', from: 20.8, to: 21.0 }],
        comment: 'a bit warmer',
      },
    },
    ...older,
  ].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}
