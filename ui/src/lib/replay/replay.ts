import { getJson, getOptional, postJson } from '$lib/core/api';
import type { Schemas } from '$lib/core/types';
import { divergenceStep } from '$lib/shadow/shadow';

export type ReplayCoverage = Schemas['ReplayCoverage'];
export type CoverageDay = Schemas['CoverageDay'];
export type ReplayJob = Schemas['ReplayJob'];
export type ReplayResult = Schemas['ReplayResult'];
export type ReplaySummary = Schemas['ReplaySummary'];
export type ReplayEpisode = Schemas['ReplayEpisode'];
export type ReplaySeries = Schemas['ReplaySeries'];
export type ReplayIdentity = Schemas['ReplayIdentity'];
export type ReplayKind = Schemas['ReplayKindName'];

const DAY = 86_400_000;

export interface ReplayBody {
  from: string;
  to: string;
  config: ReplayKind;
  version?: number;
  changes?: Record<string, unknown>;
  step?: number;
}

/**
 * Where stored decisions exist; null when the service has no replay endpoints (older backend).
 */
export function fetchCoverage(
  window: { from: Date; to: Date } | null,
  signal?: AbortSignal,
): Promise<ReplayCoverage | null> {
  const query = window
    ? `?${new URLSearchParams({ from: window.from.toISOString(), to: window.to.toISOString() })}`
    : '';
  return getOptional<ReplayCoverage>(`api/v1/replay/coverage${query}`, signal);
}

export const startReplay = (body: ReplayBody) => postJson<ReplayJob>('api/v1/replay', body);

export const fetchReplayJob = (id: string, signal?: AbortSignal) =>
  getJson<ReplayJob>(`api/v1/replay/${encodeURIComponent(id)}`, signal);

export const cancelReplay = (id: string) =>
  postJson<ReplayJob>(`api/v1/replay/${encodeURIComponent(id)}/cancel`, {});

export const REPLAY_PRESETS = ['1d', '7d', '30d', 'custom'] as const;
export type ReplayPreset = (typeof REPLAY_PRESETS)[number];
export const PRESET_DAYS: Record<Exclude<ReplayPreset, 'custom'>, number> = {
  '1d': 1,
  '7d': 7,
  '30d': 30,
};

export type PeriodProblem = 'invalid' | 'order' | 'too_long';

/**
 * The period of a preset ending at `nowMs`, shortened to the longest period the service allows.
 */
export function presetPeriod(
  preset: Exclude<ReplayPreset, 'custom'>,
  nowMs: number,
  maxDays: number,
): { from: number; to: number } {
  const days = Math.min(PRESET_DAYS[preset], maxDays);
  return { from: nowMs - days * DAY, to: nowMs };
}

/**
 * A custom period from two `datetime-local` texts, or why it cannot be replayed.
 */
export function customPeriod(
  fromText: string,
  toText: string,
  maxDays: number,
): { from: number; to: number } | { problem: PeriodProblem } {
  const from = Date.parse(fromText);
  const to = Date.parse(toText);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return { problem: 'invalid' };
  if (from >= to) return { problem: 'order' };
  if (to - from > maxDays * DAY) return { problem: 'too_long' };
  return { from, to };
}

/**
 * The request body of a replay: the period, the chosen configuration and a chart step with at
 * most 1,500 points.
 */
export function replayBody(
  period: { from: number; to: number },
  choice: { kind: ReplayKind; version?: number | null; changes?: Record<string, unknown> },
): ReplayBody {
  const body: ReplayBody = {
    from: new Date(period.from).toISOString(),
    to: new Date(period.to).toISOString(),
    config: choice.kind,
    step: divergenceStep(period.from, period.to),
  };
  if (choice.kind === 'version' && typeof choice.version === 'number')
    body.version = choice.version;
  if (choice.kind === 'draft') body.changes = { ...(choice.changes ?? {}) };
  return body;
}

export type CoverageLevel = 'none' | 'part' | 'full';

export interface CoverageCell {
  date: string;
  from: number;
  to: number;
  decisions: number;
  share: number;
  level: CoverageLevel;
}

/**
 * One cell per day of the coverage: the share of the expected decisions that are stored. A day
 * with at least 95 % counts as full.
 */
export function coverageCells(coverage: ReplayCoverage): CoverageCell[] {
  return coverage.days.map((day) => {
    const share = day.expected > 0 ? Math.min(1, day.decisions / day.expected) : 0;
    return {
      date: day.date,
      from: Date.parse(day.from),
      to: Date.parse(day.to),
      decisions: day.decisions,
      share,
      level: day.decisions === 0 ? 'none' : share >= 0.95 ? 'full' : 'part',
    };
  });
}

/**
 * Whether a cell lies (partly) inside a period.
 */
export function inPeriod(cell: CoverageCell, period: { from: number; to: number } | null): boolean {
  return period !== null && cell.from < period.to && cell.to > period.from;
}

type Point = [number, number];

/**
 * The points of one series column; steps without a value are left out (drawn as a gap).
 */
export function seriesPoints(series: ReplaySeries, key: 'recorded' | 'replayed' | 'pump'): Point[] {
  const points: Point[] = [];
  series.at.forEach((at, index) => {
    const value = series[key][index];
    if (typeof value === 'number') points.push([Date.parse(at), value]);
  });
  return points;
}

/**
 * The band between the replayed setpoint and the pump's target, drawn in steps like the lines and
 * closed to zero height where either value is missing, so a gap is never shaded.
 */
export function replayBand(series: ReplaySeries): { upper: Point[]; lower: Point[] } {
  const upper: Point[] = [];
  const lower: Point[] = [];
  const add = (t: number, hi: number, lo: number) => {
    upper.push([t, hi]);
    lower.push([t, lo]);
  };
  let previous: [number, number] | null = null;
  series.at.forEach((at, index) => {
    const t = Date.parse(at);
    const a = series.replayed[index];
    const b = series.pump[index];
    if (typeof a !== 'number' || typeof b !== 'number') {
      if (previous) {
        add(t, previous[0], previous[1]);
        add(t, previous[1], previous[1]);
      }
      previous = null;
      return;
    }
    const hi = Math.max(a, b);
    const lo = Math.min(a, b);
    if (previous) add(t, previous[0], previous[1]);
    else add(t, lo, lo);
    add(t, hi, lo);
    previous = [hi, lo];
  });
  return { upper, lower };
}

/**
 * The largest shares of a share map, largest first.
 */
export function topShares(shares: Record<string, number>, count = 5): [string, number][] {
  return Object.entries(shares)
    .sort((a, b) => b[1] - a[1])
    .slice(0, count);
}

export type IdentityState = 'exact' | 'differs' | 'unchecked';

/**
 * How far the replay can be trusted: exact when every compared tick reproduced its setpoint.
 */
export function identityState(identity: ReplayIdentity): IdentityState {
  if (identity.ok === null || identity.ticks === 0) return 'unchecked';
  return identity.ok ? 'exact' : 'differs';
}
