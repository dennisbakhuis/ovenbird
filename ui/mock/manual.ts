import type {
  AwayStatus,
  BoostStatus,
  ConfigDoc,
  DayShift,
  DayShiftPhase,
  FeatureEntry,
  FeatureId,
  Features,
  SummerStatus,
} from '../src/lib/core/types';
import type { Scenario } from './scenario.ts';

const MINUTE = 60_000;
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const ACTOR = 'admin from 127.0.0.1';

export const BOOST_MIN_S = 900;
export const BOOST_MAX_S = 43_200;
export const AWAY_MAX_AHEAD_MS = 60 * DAY;

/**
 * A boost as `POST control/boost` stores it.
 */
export interface BoostRequestState {
  offsetK: number;
  untilMs: number;
  atMs: number;
}

/**
 * An away period as `PUT control/away` stores it.
 */
export interface AwayRequestState {
  targetC: number;
  untilMs: number;
  leadS: number;
  atMs: number;
}

type Result = { status: number; body: unknown };

const number = (doc: ConfigDoc, id: string, fallback: number): number => {
  const value = doc.fields[id]?.value;
  return typeof value === 'number' ? value : fallback;
};
const flag = (doc: ConfigDoc, id: string, fallback: boolean): boolean => {
  const value = doc.fields[id]?.value;
  return typeof value === 'boolean' ? value : fallback;
};
const iso = (ms: number) => new Date(ms).toISOString();

/**
 * The request a scenario starts with: `boost:active` is a +1 K boost begun 30 min ago, running
 * 90 min more. A stored request (or a stored end, `null`) wins over the scenario.
 */
export function scenarioBoost(scenario: Scenario, now: number): BoostRequestState | null {
  return scenario.boost === 'active'
    ? { offsetK: 1, atMs: now - 30 * MINUTE, untilMs: now + 90 * MINUTE }
    : null;
}

/**
 * The away period a scenario starts with: `away:active` ends in two days (comfort again 6 h
 * before), `away:returning` is inside the lead.
 */
export function scenarioAway(scenario: Scenario, now: number): AwayRequestState | null {
  if (scenario.away === 'active')
    return { targetC: 16, leadS: 21_600, atMs: now - 5 * HOUR, untilMs: now + 2 * DAY };
  if (scenario.away === 'returning')
    return { targetC: 16, leadS: 21_600, atMs: now - 2 * DAY, untilMs: now + 3 * HOUR };
  return null;
}

/**
 * The `boost` block of the control status.
 */
export function boostStatus(
  doc: ConfigDoc,
  request: BoostRequestState | null,
  now: number,
  paused: string | null,
): BoostStatus {
  const running = request !== null && request.untilMs > now;
  const comfort = number(doc, 'control_comfort_c', 21);
  return {
    enabled: flag(doc, 'control_boost_enabled', true),
    active: running,
    paused: running ? paused : null,
    shift_k: running ? request.offsetK : null,
    target_c: running ? comfort + request.offsetK : null,
    remaining_s: running ? Math.round((request.untilMs - now) / 1000) : null,
    default_s: number(doc, 'control_boost_default_s', 7200),
    default_k: number(doc, 'control_boost_default_k', 1),
    request: running
      ? {
          offset_k: request.offsetK,
          target_c: null,
          until: iso(request.untilMs),
          actor: ACTOR,
          at: iso(request.atMs),
        }
      : null,
  };
}

/**
 * The `away` block of the control status.
 */
export function awayStatus(
  doc: ConfigDoc,
  request: AwayRequestState | null,
  now: number,
  paused: string | null,
): AwayStatus {
  const running = request !== null && request.untilMs > now;
  const comfortFrom = running ? request.untilMs - request.leadS * 1000 : null;
  return {
    enabled: flag(doc, 'control_away_enabled', true),
    active: running,
    phase: running ? (comfortFrom !== null && now >= comfortFrom ? 'returning' : 'away') : null,
    paused: running ? paused : null,
    target_c: running ? request.targetC : null,
    until: running ? iso(request.untilMs) : null,
    comfort_from: comfortFrom === null ? null : iso(comfortFrom),
    default_target_c: number(doc, 'control_away_target_c', 16),
    default_lead_s: number(doc, 'control_away_comfort_lead_s', 21_600),
    request: running
      ? {
          target_c: request.targetC,
          until: iso(request.untilMs),
          comfort_lead_s: request.leadS,
          comfort_from: iso(comfortFrom ?? request.untilMs),
          actor: ACTOR,
          at: iso(request.atMs),
        }
      : null,
  };
}

/**
 * The `summer` block of the control status: `summer:on` holds heating off, `summer:warming`
 * is switched on but still collecting the outside mean.
 */
export function summerStatus(doc: ConfigDoc, scenario: Scenario): SummerStatus {
  const enabled = flag(doc, 'control_summer_enabled', false);
  const offC = number(doc, 'control_summer_off_c', 18);
  const hysteresis = number(doc, 'control_summer_hysteresis_k', 2);
  const warming = enabled && scenario.summer === 'warming';
  const active = enabled && scenario.summer === 'on';
  return {
    enabled,
    active,
    mean_c: enabled && !warming ? (active ? 19.4 : 11.2) : null,
    mean_tau_s: enabled ? number(doc, 'control_summer_mean_s', 86_400) : null,
    off_c: enabled ? offC : null,
    on_c: enabled ? offC - hysteresis : null,
    warming_up: warming,
  };
}

const bodyProblem = (message: string, status = 400): Result => ({
  status,
  body: { detail: message },
});

/**
 * `POST control/boost`: refused (409) while away is set or boost is off, 400 out of range.
 */
export function startBoost(
  body: Record<string, unknown>,
  doc: ConfigDoc,
  away: AwayStatus,
  now: number,
): { result: Result; request: BoostRequestState | null } {
  const refuse = (result: Result) => ({ result, request: null });
  if (!flag(doc, 'control_boost_enabled', true)) return refuse(bodyProblem('boost is off', 409));
  if (away.active) return refuse(bodyProblem('end away before a boost', 409));
  const offset = body['offset_k'] ?? number(doc, 'control_boost_default_k', 1);
  const duration = body['duration_s'] ?? number(doc, 'control_boost_default_s', 7200);
  if (typeof offset !== 'number' || offset === 0 || offset < -3 || offset > 2)
    return refuse(bodyProblem('offset_k must be -3 to 2 and not 0'));
  if (typeof duration !== 'number' || duration < BOOST_MIN_S || duration > BOOST_MAX_S)
    return refuse(bodyProblem('duration_s must be 900 to 43200'));
  return {
    result: { status: 200, body: null },
    request: { offsetK: offset, atMs: now, untilMs: now + duration * 1000 },
  };
}

/**
 * `PUT control/away`: until must lie beyond the lead and within 60 days.
 */
export function startAway(
  body: Record<string, unknown>,
  doc: ConfigDoc,
  now: number,
): { result: Result; request: AwayRequestState | null } {
  const refuse = (result: Result) => ({ result, request: null });
  if (!flag(doc, 'control_away_enabled', true)) return refuse(bodyProblem('away is off', 409));
  const until = typeof body['until'] === 'string' ? Date.parse(body['until']) : Number.NaN;
  if (!Number.isFinite(until)) return refuse(bodyProblem('until must be an ISO time'));
  const target = body['target_c'] ?? number(doc, 'control_away_target_c', 16);
  const lead = body['comfort_lead_s'] ?? number(doc, 'control_away_comfort_lead_s', 21_600);
  if (typeof target !== 'number' || target < 10 || target > 20)
    return refuse(bodyProblem('target_c must be 10 to 20'));
  if (typeof lead !== 'number' || lead < 0 || lead > 86_400)
    return refuse(bodyProblem('comfort_lead_s must be 0 to 86400'));
  if (until <= now + lead * 1000) return refuse(bodyProblem('until must lie beyond the lead'));
  if (until > now + AWAY_MAX_AHEAD_MS)
    return refuse(bodyProblem('until lies more than 60 days ahead'));
  return {
    result: { status: 200, body: null },
    request: { targetC: target, leadS: lead, atMs: now, untilMs: until },
  };
}

export interface ManualContext {
  doc: ConfigDoc;
  scenario: Scenario;
  now: number;
  autoMode: boolean;
  stoveActive: boolean;
  boost: BoostStatus;
  away: AwayStatus;
  summer: SummerStatus;
}

const SWITCH: Record<FeatureId, string> = {
  weather_compensation: 'control_weather_compensation',
  room_feedback: 'control_feedback_enabled',
  slow_start: 'control_ramp_enabled',
  minimum_run: 'control_cycling_enabled',
  pump_duty: 'control_pump_duty',
  quiet: 'control_quiet_enabled',
  stove: 'control_stove_enabled',
  dayshift: 'control_dayshift_use',
  summer: 'control_summer_enabled',
  away: 'control_away_enabled',
  boost: 'control_boost_enabled',
  house_basics: 'house_basics_enabled',
  starts_alarm: 'safety_starts_alarm_enabled',
};

/**
 * `GET control/features`: every feature with its state in the service's fixed order.
 */
export function featuresReport(ctx: ManualContext): Features {
  const dayshiftMode = String(ctx.doc.fields['control_dayshift_use']?.value ?? 'off');
  const observers: FeatureId[] = ['house_basics', 'starts_alarm'];
  const entry = (id: FeatureId): FeatureEntry => {
    const value = ctx.doc.fields[SWITCH[id]]?.value;
    const enabled = id === 'dayshift' ? value !== 'off' : value !== false;
    const flags = {
      experimental: id === 'dayshift',
      on_available:
        id !== 'dayshift' || ctx.doc.fields['control_dayshift_experimental_ok']?.value === true,
    };
    if (!enabled) return { id, enabled: false, active: false, state: 'off', ...flags };
    const acting: Partial<Record<FeatureId, boolean>> = {
      stove: ctx.stoveActive,
      boost: ctx.boost.active,
      away: ctx.away.active,
      summer: ctx.summer.active,
      dayshift: dayshiftMode === 'on' && dayshiftOf(ctx).phase !== 'idle',
      quiet: ctx.scenario.quiet === 'on',
    };
    const active = acting[id] ?? !observers.includes(id);
    if (observers.includes(id)) return { id, enabled, active: true, state: 'on', ...flags };
    if (!ctx.autoMode || (id === 'dayshift' && dayshiftMode === 'shadow'))
      return { id, enabled, active: ctx.autoMode ? active : false, state: 'shadow', ...flags };
    return { id, enabled, active, state: active ? 'active_now' : 'on', ...flags };
  };
  return {
    mode: ctx.autoMode ? 'auto' : 'shadow',
    features: (Object.keys(SWITCH) as FeatureId[]).map(entry),
  };
}

const PHASE_REASONS: Record<DayShiftPhase, DayShift['reasons']> = {
  idle: ['outside_windows'],
  boost: ['sun_forecast', 'outside_mild'],
  setback: ['night_after_boost'],
  recovery: ['recovery_lead'],
  blocked: ['forecast_stale'],
};

/**
 * `GET control/dayshift`: the scenario's phase (`dayshift:boost`, `setback`, `recovery`,
 * `blocked`, `idle`; `shadow` is a boost recorded only; `on` is a boost applied, with the
 * experimental acknowledgement stored).
 */
export function dayshiftOf(ctx: ManualContext): DayShift {
  const mode = String(ctx.doc.fields['control_dayshift_use']?.value ?? 'off') as
    'off' | 'shadow' | 'on';
  const scenarioPhase = ctx.scenario.dayshift;
  const phase: DayShiftPhase =
    mode === 'off'
      ? 'idle'
      : scenarioPhase === 'shadow' || scenarioPhase === 'on'
        ? 'boost'
        : (scenarioPhase ?? 'idle');
  const sign = phase === 'setback' ? -1 : phase === 'boost' || phase === 'recovery' ? 1 : 0;
  const desired =
    phase === 'boost' ? 0.5 : phase === 'setback' ? -0.5 : phase === 'recovery' ? 0.25 : 0;
  const offset =
    sign *
    (phase === 'boost' ? 0.25 : phase === 'setback' ? 0.25 : phase === 'recovery' ? 0.25 : 0);
  const day = Math.floor(ctx.now / DAY) * DAY;
  const at = (hours: number) => day + hours * HOUR;
  const text = (id: string, fallback: string) => String(ctx.doc.fields[id]?.value ?? fallback);
  const guards: DayShift['guards'] = phase === 'blocked' ? ['forecast_stale'] : [];
  const nextAt = at(ctx.now - day < 17 * HOUR ? 17 : 23) + (ctx.now - day >= 23 * HOUR ? DAY : 0);
  return {
    mode,
    configured: mode,
    on_available: ctx.doc.fields['control_dayshift_experimental_ok']?.value === true,
    experimental: true,
    phase,
    offset_k: mode === 'off' ? 0 : offset,
    desired_k: mode === 'off' ? 0 : desired,
    applied_k: mode === 'on' ? offset : 0,
    reasons: mode === 'off' ? ['off'] : PHASE_REASONS[phase],
    guards,
    evaluated_at: mode === 'off' ? null : iso(ctx.now - 4 * MINUTE),
    valid_until: mode === 'on' ? iso(ctx.now + 16 * MINUTE) : null,
    next_change:
      mode === 'off' || phase === 'blocked'
        ? null
        : { at: iso(nextAt), phase: phase === 'boost' ? 'idle' : 'setback' },
    boosted_today: phase !== 'idle' && phase !== 'blocked',
    windows: {
      day_start: text('control_dayshift_day_start', '09:00'),
      day_end: text('control_dayshift_day_end', '17:00'),
      night_start: text('control_dayshift_night_start', '23:00'),
      night_end: text('control_dayshift_night_end', '05:00'),
      comfort_at: text('control_dayshift_comfort_at', '07:00'),
      setback_end: iso(at(24 + 3)),
      timezone: 'Europe/Amsterdam',
    },
    forecast:
      mode === 'off'
        ? null
        : {
            issued_at: iso(ctx.now - 90 * MINUTE),
            hours: 54,
            sun_wm2: phase === 'blocked' ? null : 310.4,
            sun_limit_wm2: number(ctx.doc, 'control_dayshift_min_sun_wm2', 150),
            outside_c: 8.2,
            outside_min_c: 7.5,
            outside_limit_c: number(ctx.doc, 'control_dayshift_min_outside_c', 5),
            night_min_c: 3.1,
            night_limit_c: number(ctx.doc, 'control_dayshift_min_outside_c', 5),
          },
  };
}
