import { ApiError, isMissing } from '$lib/core/api';
import type { BarItem } from '$components/charts/Bars.svelte';
import { timeLocale } from '$lib/core/format';
import type { Schemas } from '$lib/core/types';

export type InsightDay = Schemas['InsightDay'];
export type InsightDaily = Schemas['InsightDaily'];

export type InsightResult = { kind: 'ok'; data: InsightDaily } | { kind: 'missing' };

export const INSIGHT_SPANS = [7, 30] as const;
export type InsightSpan = (typeof INSIGHT_SPANS)[number];

export const LOW_COVERAGE = 0.8;

/**
 * Fetch the daily insight figures; an older backend without the endpoint gives `{kind: 'missing'}`.
 */
export async function fetchInsightDaily(
  days: number,
  signal?: AbortSignal,
): Promise<InsightResult> {
  const path = `api/v1/insight/daily?days=${Math.min(Math.max(Math.round(days), 1), 90)}`;
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal });
  if (response.ok) return { kind: 'ok', data: (await response.json()) as InsightDaily };
  const error = new ApiError(path, response.status);
  if (isMissing(error)) return { kind: 'missing' };
  throw error;
}

/**
 * The last `span` days, oldest first.
 */
export function lastDays(days: InsightDay[], span: number): InsightDay[] {
  return days.slice(-span);
}

export interface InsightTotals {
  days: number;
  electricKwh: number | null;
  heatKwh: number | null;
  cop: number | null;
  starts: number | null;
  runH: number | null;
  defrosts: number | null;
  belowKh: number | null;
  lowCoverageDays: number;
  missingDays: number;
  partialIncluded: boolean;
}

function sumKnown(values: (number | null)[]): number | null {
  const known = values.filter((v): v is number => v !== null && Number.isFinite(v));
  return known.length === 0 ? null : known.reduce((a, b) => a + b, 0);
}

/**
 * Totals over a set of days. A figure with no known day stays null; COP is heat over electricity
 * on the days where both are known, so one gap does not skew it.
 */
export function totals(days: InsightDay[]): InsightTotals {
  const both = days.filter(
    (d) => d.electric_kwh !== null && d.heat_kwh !== null && d.electric_kwh > 0,
  );
  const electricBoth = sumKnown(both.map((d) => d.electric_kwh));
  const heatBoth = sumKnown(both.map((d) => d.heat_kwh));
  const runS = sumKnown(days.map((d) => d.run_s));
  return {
    days: days.length,
    electricKwh: sumKnown(days.map((d) => d.electric_kwh)),
    heatKwh: sumKnown(days.map((d) => d.heat_kwh)),
    cop: electricBoth && heatBoth !== null ? heatBoth / electricBoth : null,
    starts: sumKnown(days.map((d) => d.compressor_starts)),
    runH: runS === null ? null : runS / 3600,
    defrosts: sumKnown(days.map((d) => d.defrosts)),
    belowKh: sumKnown(days.map((d) => d.below_comfort_kh)),
    lowCoverageDays: days.filter((d) => d.coverage !== null && d.coverage < LOW_COVERAGE).length,
    missingDays: days.filter((d) => d.electric_kwh === null && d.heat_kwh === null).length,
    partialIncluded: days.some((d) => d.partial),
  };
}

export interface BarNotes {
  partial: string;
  coverage: (percent: number) => string;
}

/**
 * Short axis label of a local day: weekday for a week, day of the month for longer spans.
 */
export function dayLabel(day: InsightDay, language: string, span: number): string {
  const date = new Date(`${day.date}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return day.date;
  const locale = timeLocale(language);
  return span <= 7
    ? date.toLocaleDateString(locale, { weekday: 'short', timeZone: 'UTC' })
    : date.toLocaleDateString(locale, { day: 'numeric', timeZone: 'UTC' });
}

/**
 * Bar items for one figure: nulls stay null (drawn as gaps), today is lightened and noted as
 * partial, and a day with low coverage carries its coverage in the note.
 */
export function barItems(
  days: InsightDay[],
  pick: (day: InsightDay) => number | null,
  options: { color: string; language: string; notes: BarNotes },
): BarItem[] {
  return days.map((day) => {
    const notes: string[] = [];
    if (day.partial) notes.push(options.notes.partial);
    if (day.coverage !== null && day.coverage < LOW_COVERAGE)
      notes.push(options.notes.coverage(Math.round(day.coverage * 100)));
    const value = pick(day);
    return {
      label: dayLabel(day, options.language, days.length),
      value: value !== null && Number.isFinite(value) ? value : null,
      color: day.partial ? `color-mix(in srgb, ${options.color} 55%, transparent)` : options.color,
      ...(notes.length > 0 ? { note: notes.join(', ') } : {}),
    };
  });
}

/**
 * Index of today's bar (the partial day), or null.
 */
export function partialIndex(days: InsightDay[]): number | null {
  const index = days.findIndex((d) => d.partial);
  return index < 0 ? null : index;
}

/**
 * Run time of a day in hours, null when unknown.
 */
export const runHours = (day: InsightDay): number | null =>
  day.run_s === null ? null : day.run_s / 3600;
