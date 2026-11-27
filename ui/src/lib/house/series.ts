import { ApiError, getJson, isMissing } from '$lib/core/api';
import type { HouseSeries, SeriesPoint } from './shapes';

export const SERIES_RANGES = [3, 7, 14] as const;
export type SeriesRange = (typeof SERIES_RANGES)[number];

export type SeriesResult =
  { kind: 'ready'; data: HouseSeries } | { kind: 'none' } | { kind: 'absent' };

/**
 * Measured and predicted room temperature; `none` when the service has no series yet (404
 * `house_series_missing`), `absent` when it does not have the endpoint (an older service).
 */
export async function fetchHouseSeries(signal?: AbortSignal): Promise<SeriesResult> {
  try {
    return {
      kind: 'ready',
      data: await getJson<HouseSeries>('api/v1/insight/house/series', signal),
    };
  } catch (error) {
    if (error instanceof ApiError && error.code === 'house_series_missing') return { kind: 'none' };
    if (isMissing(error)) return { kind: 'absent' };
    throw error;
  }
}

/**
 * The points of the last `days` days before the end of the series.
 */
export function lastDays(series: HouseSeries, days: number): SeriesPoint[] {
  const end = Date.parse(series.to);
  const start = end - days * 86_400_000;
  return series.points.filter((point) => Date.parse(point[0]) >= start);
}

export interface Difference {
  count: number;
  typicalK: number;
  largestK: number;
  largestAt: string;
}

/**
 * How far the 24 h prediction was from the measurement where both exist: the typical (median)
 * and the largest absolute difference in K, and when the largest was.
 */
export function differences(points: SeriesPoint[]): Difference | null {
  const diffs: { at: string; k: number }[] = [];
  for (const [at, measured, predicted] of points)
    if (measured !== null && predicted !== null)
      diffs.push({ at, k: Math.abs(predicted - measured) });
  if (diffs.length === 0) return null;
  const sorted = diffs.map((d) => d.k).sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const typical =
    sorted.length % 2 === 1
      ? (sorted[mid] as number)
      : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
  const largest = diffs.reduce((a, b) => (b.k > a.k ? b : a));
  return { count: diffs.length, typicalK: typical, largestK: largest.k, largestAt: largest.at };
}
