import type { DecisionSeries, Decision } from '$lib/core/types';

export const BAND_TERMS = [
  'room_feedback',
  'plan',
  'start_ramp',
  'cycling_floor',
  'stove',
  'other',
] as const;
export type BandTerm = (typeof BAND_TERMS)[number];

export interface StackedPoint {
  t: number;
  curve: number;
  preRound: number | null;
  setpoint: number | null;
  low: number | null;
  high: number | null;
  bands: Record<BandTerm, { lo: number; hi: number }>;
}

export interface Marker {
  t: number;
  kind: 'config' | 'hold';
  label: string;
}

export interface ReasonSegment {
  from: number;
  to: number;
  reason: string;
}

export interface StackedSeries {
  points: StackedPoint[];
  markers: Marker[];
  reasons: ReasonSegment[];
  from: number;
  to: number;
}

const num = (value: number | null | undefined): number => (typeof value === 'number' ? value : 0);

/**
 * Turn the columnar decision series into a stacked layout: the curve as a line, positive terms
 * stacked upwards from it, negative terms downwards, plus the pre-round value, the issued step,
 * the safety band, config-version markers and reason segments.
 */
export function stackSeries(series: DecisionSeries): StackedSeries {
  const points: StackedPoint[] = [];
  const markers: Marker[] = [];
  const reasons: ReasonSegment[] = [];
  let previousVersion: number | null = null;
  for (let i = 0; i < series.at.length; i += 1) {
    const t = Date.parse(series.at[i] ?? '');
    if (!Number.isFinite(t)) continue;
    const reason = series.reason[i] ?? null;
    if (reason !== null) {
      const last = reasons[reasons.length - 1];
      if (last && last.reason === reason) last.to = t;
      else reasons.push({ from: t, to: t, reason });
    }
    const curve = series.curve[i];
    if (curve === null || curve === undefined) continue;
    let up = curve;
    let down = curve;
    const bands = {} as StackedPoint['bands'];
    for (const name of BAND_TERMS) {
      const value = num(series[name]?.[i]);
      if (value >= 0) {
        bands[name] = { lo: up, hi: up + value };
        up += value;
      } else {
        bands[name] = { lo: down + value, hi: down };
        down += value;
      }
    }
    points.push({
      t,
      curve,
      preRound: series.pre_round[i] ?? null,
      setpoint: series.setpoint[i] ?? null,
      low: series.safety_low[i] ?? null,
      high: series.safety_high[i] ?? null,
      bands,
    });
    const version = series.config_version[i] ?? null;
    if (version !== null && previousVersion !== null && version !== previousVersion) {
      markers.push({ t, kind: 'config', label: `v${version}` });
    }
    if (version !== null) previousVersion = version;
  }
  for (let i = 0; i < reasons.length - 1; i += 1) {
    const current = reasons[i];
    const next = reasons[i + 1];
    if (current && next) current.to = next.from;
  }
  const tail = reasons[reasons.length - 1];
  const end = Date.parse(series.to);
  if (tail && Number.isFinite(end) && end > tail.to) tail.to = end;
  return {
    points,
    markers,
    reasons,
    from: Date.parse(series.from),
    to: Date.parse(series.to),
  };
}

/**
 * Build the columnar series from decision entries, for servers without `decisions/series`.
 */
export function seriesFromDecisions(
  decisions: Decision[],
  from: string,
  to: string,
): DecisionSeries {
  const out: DecisionSeries = {
    from,
    to,
    step: 0,
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
  const term = (decision: Decision, name: string): number | null =>
    decision.record.terms.find((item) => item.name === name)?.value ?? null;
  for (const decision of decisions) {
    const record = decision.record;
    const safety = record.terms.find((item) => item.name === 'safety');
    const state = record.controller_state;
    const low = state['safety_low_c'];
    const high = state['safety_high_c'];
    out.at.push(decision.at);
    out.setpoint.push(decision.setpoint);
    out.pre_round.push(record.pre_round);
    out.curve.push(term(decision, 'curve'));
    out.room_feedback.push(term(decision, 'room_feedback'));
    out.plan.push(term(decision, 'plan'));
    out.start_ramp.push(term(decision, 'start_ramp'));
    out.cycling_floor.push(term(decision, 'cycling_floor'));
    out.stove?.push(record.terms.length ? (term(decision, 'stove') ?? 0) : null);
    const other = (term(decision, 'boost') ?? 0) + (term(decision, 'override') ?? 0);
    out.other.push(record.terms.length ? other : null);
    out.safety_delta.push(safety ? safety.value - safety.raw : null);
    out.safety_low.push(typeof low === 'number' ? low : null);
    out.safety_high.push(typeof high === 'number' ? high : null);
    out.reason.push(decision.reason);
    out.binding.push(record.binding);
    out.ladder.push(decision.ladder);
    out.config_version.push(decision.config_version ?? null);
  }
  return out;
}

export type ReasonCategory = 'normal' | 'limited' | 'frozen' | 'stopped' | 'manual';

const REASON_CATEGORIES: Record<string, ReasonCategory> = {
  curve: 'normal',
  room_feedback: 'normal',
  plan_preheat: 'normal',
  plan_setback: 'normal',
  pump_duty_heat: 'normal',
  pump_duty_idle: 'normal',
  quiet_schedule: 'normal',
  start_ramp: 'limited',
  cycling_protect: 'limited',
  safety_clamp: 'limited',
  deadband_hold: 'limited',
  dwell_hold: 'limited',
  room_stale: 'limited',
  room_implausible: 'limited',
  defrost_freeze: 'frozen',
  dhw_freeze: 'frozen',
  heishamon_dead: 'stopped',
  mode_mismatch: 'stopped',
  mode_unknown: 'stopped',
  mode_off: 'stopped',
  inputs_missing: 'stopped',
  override_missing: 'stopped',
  override: 'manual',
  stove: 'limited',
};

/**
 * Group a reason code into a colour category for the reason strip.
 */
export function reasonCategory(reason: string): ReasonCategory {
  return REASON_CATEGORIES[reason] ?? 'normal';
}

export const REASON_CATEGORY_LIST: ReasonCategory[] = [
  'normal',
  'limited',
  'frozen',
  'stopped',
  'manual',
];

export const COARSE_REASON_WINDOW_MS = 48 * 3_600_000;
const HOUR_MS = 3_600_000;

/**
 * Reason segments reduced to the dominant category per bucket (an hour by default), merged into
 * runs. Long windows hold thousands of one-minute segments that cannot be read as they are.
 */
export function dominantReasonRuns(
  reasons: ReasonSegment[],
  from: number,
  to: number,
  bucketMs = HOUR_MS,
): { from: number; to: number; state: ReasonCategory }[] {
  const first = Math.floor(from / bucketMs) * bucketMs;
  const out: { from: number; to: number; state: ReasonCategory }[] = [];
  for (let start = first; start < to; start += bucketMs) {
    const end = start + bucketMs;
    const totals = new Map<ReasonCategory, number>();
    for (const segment of reasons) {
      if (segment.to < start && segment.from < start) continue;
      if (segment.from >= end) break;
      const overlap =
        Math.min(Math.max(segment.to, segment.from + 1), end) - Math.max(segment.from, start);
      if (overlap <= 0) continue;
      const category = reasonCategory(segment.reason);
      totals.set(category, (totals.get(category) ?? 0) + overlap);
    }
    let best: ReasonCategory | null = null;
    let bestMs = 0;
    for (const category of REASON_CATEGORY_LIST) {
      const ms = totals.get(category) ?? 0;
      if (ms > bestMs) {
        best = category;
        bestMs = ms;
      }
    }
    if (best === null) continue;
    const last = out[out.length - 1];
    const clipped = { from: Math.max(start, from), to: Math.min(end, to), state: best };
    if (last && last.state === best && last.to >= clipped.from) last.to = clipped.to;
    else out.push(clipped);
  }
  return out;
}
