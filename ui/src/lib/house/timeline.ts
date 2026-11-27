import type { ErrorTrendEntry, HouseInsight } from '$lib/house/house';

export interface DailyError {
  date: string;
  room_rmse_24h_k: number | null;
  origins: number;
}

export interface ErrorStats {
  days: number;
  mean: number;
  min: number;
  max: number;
  worstDate: string;
}

export interface LeftOut {
  kind: string;
  start: string | null;
  end: string | null;
  hours: number | null;
  excludedHours: number | null;
  peakK: number | null;
  reason: string | null;
}

export interface Fitted {
  from: string | null;
  to: string | null;
  fitDays: number | null;
  stepS: number | null;
  method: string | null;
  fallbackReason: string | null;
  codeVersion: string | null;
  generated: string | null;
  bootstrap: number | null;
  folds: number | null;
}

const text = (value: unknown): string | null =>
  typeof value === 'string' && value !== '' ? value : null;
const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

/**
 * Mean, range and worst day of the daily room error, over the days that have a value; null when
 * no day has one.
 */
export function errorStats(daily: DailyError[]): ErrorStats | null {
  const known = daily.filter(
    (day): day is DailyError & { room_rmse_24h_k: number } => day.room_rmse_24h_k !== null,
  );
  if (known.length === 0) return null;
  const values = known.map((day) => day.room_rmse_24h_k);
  const worst = known.reduce((a, b) => (b.room_rmse_24h_k > a.room_rmse_24h_k ? b : a));
  return {
    days: known.length,
    mean: values.reduce((a, b) => a + b, 0) / values.length,
    min: Math.min(...values),
    max: Math.max(...values),
    worstDate: worst.date,
  };
}

/**
 * The periods the learner left out of the fit (`events`): the wood-stove episodes it detected or
 * read from the service's journal. Fields that are missing stay null.
 */
export function leftOutPeriods(events: unknown[] | null | undefined): LeftOut[] {
  return (events ?? []).flatMap((event) => {
    if (typeof event !== 'object' || event === null) return [];
    const row = event as Record<string, unknown>;
    return [
      {
        kind: text(row['kind']) ?? 'other',
        start: text(row['start_local']),
        end: text(row['end_local']),
        hours: num(row['hours']),
        excludedHours: num(row['excluded_hours']),
        peakK: num(row['peak_k']),
        reason: text(row['reason']),
      },
    ];
  });
}

/**
 * What the current model was fitted on, read from `provenance` (any field may be absent).
 */
export function fittedOn(provenance: Record<string, unknown> | null | undefined): Fitted {
  const row = provenance ?? {};
  return {
    from: text(row['data_from']),
    to: text(row['data_to']),
    fitDays: num(row['fit_days']),
    stepS: num(row['step_s']),
    method: text(row['method']),
    fallbackReason: text(row['fallback_reason']),
    codeVersion: text(row['code_version']),
    generated: text(row['generated']),
    bootstrap: num(row['bootstrap']),
    folds: num(row['folds']),
  };
}

/**
 * The room error of each model run, oldest first, without the runs that have none.
 */
export function runErrors(trend: ErrorTrendEntry[] | null | undefined): number[] {
  return (trend ?? []).flatMap((entry) =>
    entry.room_rmse_24h_k === null ? [] : [entry.room_rmse_24h_k],
  );
}

/**
 * Whole days since the model in use was promoted (null without a date).
 */
export function modelAgeDays(house: HouseInsight, nowMs: number): number | null {
  const stamp = house.champion?.promoted_at ?? house.learner?.last_run_at ?? null;
  const at = stamp === null ? NaN : Date.parse(stamp);
  return Number.isFinite(at) ? Math.max(0, Math.floor((nowMs - at) / 86_400_000)) : null;
}
