import { ApiError, getJson, isMissing } from '$lib/core/api';
import type { MessageKey, Params } from '$lib/i18n';
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

export type SeriesEvent = HouseSeries['events'][number];

export interface EventSpan {
  kind: SeriesEvent['kind'];
  from: number;
  to: number;
  tailTo: number;
}

/**
 * The events of the series as millisecond spans, clipped to a window and dropped when they lie
 * outside it.
 */
export function eventSpans(events: SeriesEvent[], from: number, to: number): EventSpan[] {
  return events
    .map((event) => ({
      kind: event.kind,
      from: Date.parse(event.from),
      to: Date.parse(event.to),
      tailTo: Date.parse(event.tail_to),
    }))
    .filter(
      (span) =>
        Number.isFinite(span.from) &&
        Number.isFinite(span.tailTo) &&
        span.tailTo >= from &&
        span.from <= to,
    );
}

const DAY_MS = 86_400_000;

/**
 * Whether a row at `at` was predicted from an origin the model had not seen: the prediction at a
 * time comes from the state 24 h earlier.
 */
export function isOutOfSample(at: number, outOfSampleFrom: string | null): boolean {
  if (outOfSampleFrom === null) return true;
  const first = Date.parse(outOfSampleFrom);
  return !Number.isFinite(first) || at - DAY_MS >= first;
}

export interface Difference {
  count: number;
  typicalK: number;
  largestK: number;
  largestAt: string;
}

/**
 * How far the 24 h prediction was from the measurement where both exist: the typical (median)
 * and the largest absolute difference in K, and when the largest was. Rows inside an event (its
 * tail included) and, when `outOfSampleFrom` is given, rows from days the model had seen do not
 * count.
 */
export function differences(
  points: SeriesPoint[],
  events: SeriesEvent[] = [],
  outOfSampleFrom: string | null = null,
): Difference | null {
  const spans = events.map((event) => [Date.parse(event.from), Date.parse(event.tail_to)]);
  const diffs: { at: string; k: number }[] = [];
  for (const [at, measured, predicted] of points) {
    if (measured === null || predicted === null) continue;
    const time = Date.parse(at);
    if (spans.some(([start, end]) => time >= (start as number) && time <= (end as number)))
      continue;
    if (!isOutOfSample(time, outOfSampleFrom)) continue;
    diffs.push({ at, k: Math.abs(predicted - measured) });
  }
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

export type Translate = (key: MessageKey, params?: Params) => string;

/**
 * The typical error of a prediction made a day ahead, in plain words from the service's `rmse_k`
 * and `bias_k` (predicted minus measured: below zero is too cold). Without them the sentence is
 * empty.
 */
export function typicalErrorSentence(
  rmseK: number | null,
  biasK: number | null,
  tr: Translate,
  format: (value: number, digits: number) => string,
): string {
  if (rmseK === null) return '';
  const typical = format(rmseK, 1);
  if (biasK === null) return tr('housePredTypical', { typical });
  const lean = format(Math.abs(biasK), 1);
  if (Math.abs(biasK) < 0.05) return tr('housePredTypicalLevel', { typical });
  return tr(biasK < 0 ? 'housePredTypicalCold' : 'housePredTypicalWarm', { typical, lean });
}

/**
 * The kinds of event present among the shown spans, in a fixed order, for the chart's legend.
 */
export function eventKinds(spans: EventSpan[]): ('stove' | 'excluded_day')[] {
  const kinds: ('stove' | 'excluded_day')[] = [];
  if (spans.some((span) => span.kind !== 'excluded_day')) kinds.push('stove');
  if (spans.some((span) => span.kind === 'excluded_day')) kinds.push('excluded_day');
  return kinds;
}
