import type { Decision, DecisionRecord, StateValue, Term } from '$lib/core/types';

export type RowKind = 'curve' | 'term' | 'sum' | 'clamp' | 'stage' | 'issued' | 'reported';

export interface WaterfallRow {
  kind: RowKind;
  id: string;
  start: number;
  end: number;
  delta: number;
  raw: number | null;
  limited: boolean;
  binding: string | null;
}

export interface WaterfallModel {
  kind: 'bars' | 'reason';
  rows: WaterfallRow[];
  collapsed: string[];
  axis: { min: number; max: number };
  allowed: { low: number; high: number } | null;
  sum: number | null;
  safetyRaw: number | null;
  balanced: boolean;
  setpoint: number | null;
}

const TOLERANCE = 1e-6;
const SKIPPED_TERMS = new Set(['curve', 'safety']);
const ALWAYS_COLLAPSE_WHEN_ZERO = new Set(['start_ramp', 'cycling_floor']);
const STAGE_BINDINGS = new Set(['rounding', 'deadband', 'dwell', 'defrost_hold', 'dhw_hold']);

function numberState(state: Record<string, StateValue>, key: string): number | null {
  const value = state[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function isZero(value: number): boolean {
  return Math.abs(value) < TOLERANCE;
}

function isLimited(term: Term): boolean {
  return Math.abs(term.raw - term.value) > 1e-3 && !ALWAYS_COLLAPSE_WHEN_ZERO.has(term.name);
}

/**
 * Pump-reported water target for the decision, from the arbiter's water setpoint entry.
 */
export function reportedTarget(decision: Decision): number | null {
  const entry = decision.arbiter.find((item) => item.kind === 'water_setpoint');
  return entry?.actual ?? null;
}

/**
 * Whether this decision's water setpoint went (or was already) to the pump: false in Shadow or a
 * pause (mode `shadow`/`off`) and when the arbiter skipped it (a hold, or an unknown pump value).
 */
export function decisionSends(decision: Decision): boolean {
  if (decision.mode !== 'auto' && decision.mode !== 'manual') return false;
  const entry = decision.arbiter.find((item) => item.kind === 'water_setpoint');
  return entry?.action !== 'skip';
}

/**
 * Lay out the decision pipeline as rows on one shared °C axis: curve, signed term steps, the
 * sum, the safety clamp, rounding/deadband/dwell, the issued setpoint and the pump-reported
 * target. Hold and refuse decisions, and records without terms, yield a reason-only model.
 */
export function buildWaterfall(
  record: DecisionRecord,
  reported: number | null = null,
): WaterfallModel {
  const curve = record.terms.find((term) => term.name === 'curve');
  const safety = record.terms.find((term) => term.name === 'safety');
  const reasonOnly = record.ladder === 'hold' || record.ladder === 'refuse' || !curve || !safety;
  if (reasonOnly || !curve || !safety) {
    const values = [record.setpoint, reported].filter((v): v is number => v !== null);
    return {
      kind: 'reason',
      rows: [],
      collapsed: [],
      axis: {
        min: values.length ? Math.floor(Math.min(...values) - 2) : 0,
        max: values.length ? Math.ceil(Math.max(...values) + 2) : 1,
      },
      allowed: null,
      sum: null,
      safetyRaw: safety?.raw ?? null,
      balanced: true,
      setpoint: record.setpoint,
    };
  }

  const rows: WaterfallRow[] = [];
  const collapsed: string[] = [];
  let cumulative = curve.value;
  rows.push({
    kind: 'curve',
    id: 'curve',
    start: Number.NaN,
    end: curve.value,
    delta: curve.value,
    raw: curve.raw,
    limited: false,
    binding: null,
  });

  for (const term of record.terms) {
    if (SKIPPED_TERMS.has(term.name)) continue;
    const limited = isLimited(term);
    const zero = isZero(term.value) && (!limited || ALWAYS_COLLAPSE_WHEN_ZERO.has(term.name));
    if (zero) {
      collapsed.push(term.name);
      continue;
    }
    rows.push({
      kind: 'term',
      id: term.name,
      start: cumulative,
      end: cumulative + term.value,
      delta: term.value,
      raw: limited ? term.raw : null,
      limited,
      binding: null,
    });
    cumulative += term.value;
  }

  const sum = cumulative;
  rows.push({
    kind: 'sum',
    id: 'sum',
    start: sum,
    end: sum,
    delta: 0,
    raw: null,
    limited: false,
    binding: null,
  });

  const low = numberState(record.controller_state, 'safety_low_c');
  const high = numberState(record.controller_state, 'safety_high_c');
  const allowed = low !== null && high !== null ? { low, high } : null;
  const clampDelta = safety.value - safety.raw;
  rows.push({
    kind: 'clamp',
    id: 'safety',
    start: safety.raw,
    end: safety.value,
    delta: clampDelta,
    raw: null,
    limited: !isZero(clampDelta),
    binding: !isZero(clampDelta) ? record.binding : null,
  });

  const issued = record.setpoint;
  if (issued !== null) {
    const preRound = record.pre_round ?? safety.value;
    const stageBinding =
      record.binding !== null && STAGE_BINDINGS.has(record.binding) ? record.binding : null;
    rows.push({
      kind: 'stage',
      id: 'stage',
      start: preRound,
      end: issued,
      delta: issued - preRound,
      raw: null,
      limited: stageBinding !== null,
      binding: stageBinding,
    });
    rows.push({
      kind: 'issued',
      id: 'issued',
      start: Number.NaN,
      end: issued,
      delta: issued,
      raw: null,
      limited: false,
      binding: null,
    });
  }
  if (reported !== null) {
    rows.push({
      kind: 'reported',
      id: 'reported',
      start: Number.NaN,
      end: reported,
      delta: reported,
      raw: null,
      limited: false,
      binding: null,
    });
  }

  const values: number[] = [sum, safety.raw, safety.value];
  for (const row of rows) {
    if (Number.isFinite(row.start)) values.push(row.start);
    values.push(row.end);
  }
  if (allowed) values.push(allowed.low, allowed.high);
  const min = Math.floor(Math.min(...values) - 2);
  const max = Math.ceil(Math.max(...values) + 1);
  for (const row of rows) {
    if (!Number.isFinite(row.start)) row.start = min;
  }

  return {
    kind: 'bars',
    rows,
    collapsed,
    axis: { min, max },
    allowed,
    sum,
    safetyRaw: safety.raw,
    balanced: Math.abs(sum - safety.raw) < 1e-6,
    setpoint: issued,
  };
}
