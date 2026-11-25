import type { Schemas } from '$lib/core/types';
import { getOptional } from '$lib/core/api';

export type DivergenceSummary = Schemas['DivergenceSummary'];
export type DivergenceDay = Schemas['DivergenceDay'];
export type DivergenceEpisode = Schemas['Episode'];
export type DivergenceSeries = Schemas['DivergenceSeries'];
export type Divergence = Schemas['Divergence'];

export type EpisodeEnd = 'converged' | 'gap' | 'open';
export type Writer = 'ovenbird' | 'other';

export const DIVERGENCE_STEPS = [60, 300, 900, 3600] as const;

/**
 * The finest step the divergence endpoint accepts that gives at most 1,500 points.
 */
export function divergenceStep(fromMs: number, toMs: number): number {
  const seconds = Math.max(0, (toMs - fromMs) / 1000);
  return DIVERGENCE_STEPS.find((step) => seconds / step <= 1500) ?? 3600;
}

/**
 * Fetch the shadow divergence for a window; null when the backend does not have the endpoint.
 */
export function fetchDivergence(
  opts: { from: Date; to: Date; step?: number; thresholdK?: number },
  signal?: AbortSignal,
): Promise<Divergence | null> {
  const query = new URLSearchParams({
    from: opts.from.toISOString(),
    to: opts.to.toISOString(),
    step: String(opts.step ?? divergenceStep(opts.from.getTime(), opts.to.getTime())),
  });
  if (opts.thresholdK !== undefined) query.set('threshold_k', String(opts.thresholdK));
  return getOptional<Divergence>(`api/v1/shadow/divergence?${query.toString()}`, signal);
}

export const SHADOW_RANGES = ['24h', '7d', '14d', 'custom'] as const;
export type ShadowRange = (typeof SHADOW_RANGES)[number];
export const RANGE_HOURS: Record<Exclude<ShadowRange, 'custom'>, number> = {
  '24h': 24,
  '7d': 168,
  '14d': 336,
};
export const MAX_WINDOW_DAYS = 31;

export type WindowProblem = 'invalid' | 'order' | 'too_long';

/**
 * A custom window from two `datetime-local` texts, or why it cannot be used.
 */
export function customWindow(
  fromText: string,
  toText: string,
): { from: number; to: number } | { problem: WindowProblem } {
  const from = Date.parse(fromText);
  const to = Date.parse(toText);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return { problem: 'invalid' };
  if (from >= to) return { problem: 'order' };
  if (to - from > MAX_WINDOW_DAYS * 86_400_000) return { problem: 'too_long' };
  return { from, to };
}

type Point = [number, number];

/**
 * The points of one series column, minutes without a value left out (drawn as a gap).
 */
export function seriesPoints(series: DivergenceSeries, key: 'ovenbird' | 'pump'): Point[] {
  const points: Point[] = [];
  series.at.forEach((at, index) => {
    const value = series[key][index];
    if (typeof value === 'number') points.push([Date.parse(at), value]);
  });
  return points;
}

/**
 * The band between ovenbird's and the pump's value where both are known: the difference to shade.
 */
export function differenceBand(series: DivergenceSeries): { upper: Point[]; lower: Point[] } {
  const upper: Point[] = [];
  const lower: Point[] = [];
  series.at.forEach((at, index) => {
    const a = series.ovenbird[index];
    const b = series.pump[index];
    if (typeof a !== 'number' || typeof b !== 'number') return;
    const t = Date.parse(at);
    upper.push([t, Math.max(a, b)]);
    lower.push([t, Math.min(a, b)]);
  });
  return { upper, lower };
}

export type WriterState = 'ovenbird' | 'other' | 'gap';

export interface WriterSegment {
  from: number;
  to: number;
  state: WriterState;
}

/**
 * Runs of who wrote the pump's value per step; a step without both values is a gap.
 */
export function writerSegments(series: DivergenceSeries, stepS: number): WriterSegment[] {
  const stepMs = stepS * 1000;
  const segments: WriterSegment[] = [];
  series.at.forEach((at, index) => {
    const from = Date.parse(at);
    const compared =
      typeof series.ovenbird[index] === 'number' && typeof series.pump[index] === 'number';
    const writer = series.writer[index];
    const state: WriterState = !compared ? 'gap' : writer === 'ovenbird' ? 'ovenbird' : 'other';
    const last = segments[segments.length - 1];
    if (last && last.state === state && last.to === from) last.to = from + stepMs;
    else segments.push({ from, to: from + stepMs, state });
  });
  return segments;
}

export type Direction = 'cooler' | 'warmer' | 'level';

/**
 * Which way ovenbird leans against the pump: `diff = ovenbird − pump`, below zero ovenbird would run
 * cooler; within 0.05 K level.
 */
export function direction(diffK: number | null | undefined): Direction {
  if (diffK === null || diffK === undefined || Math.abs(diffK) < 0.05) return 'level';
  return diffK < 0 ? 'cooler' : 'warmer';
}

/**
 * Hours a day row covers; a day at the edge of the window covers less than 24.
 */
export function dayHours(day: Pick<DivergenceDay, 'from' | 'to'>): number {
  return Math.max(0, (Date.parse(day.to) - Date.parse(day.from)) / 3_600_000);
}
