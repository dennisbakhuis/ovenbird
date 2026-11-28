import { ApiError, isMissing } from '$lib/core/api';
import type { BarItem } from '$components/charts/Bars.svelte';
import { formatNum } from '$lib/core/chartSummary';
import { timeLocale } from '$lib/core/format';
import type { Language } from '$lib/i18n';
import type { Schemas } from '$lib/core/types';

export type InsightBasics = Schemas['InsightBasics'];
export type HeatLoss = Schemas['HeatLoss'];
export type HeatLossPoint = Schemas['HeatLossPoint'];
export type LossEstimate = Schemas['LossEstimate'];
export type LossNow = Schemas['LossNow'];
export type Emitter = Schemas['Emitter'];
export type EmitterRow = Schemas['EmitterRow'];
export type WeatherBin = Schemas['WeatherBinRow'];
export type BasicsStatus = Schemas['BasicsStatusName'];

export type BasicsResult = { kind: 'ok'; data: InsightBasics } | { kind: 'missing' };

export const QUALIFYING_DAYS = 10;
export const BALANCED_W = 50;

/**
 * Fetch the house basics; an older backend without the endpoint gives `{kind: 'missing'}`.
 */
export async function fetchBasics(signal?: AbortSignal): Promise<BasicsResult> {
  const path = 'api/v1/insight/basics';
  const response = await fetch(path, { headers: { Accept: 'application/json' }, signal });
  if (response.ok) return { kind: 'ok', data: (await response.json()) as InsightBasics };
  const error = new ApiError(path, response.status);
  if (isMissing(error)) return { kind: 'missing' };
  throw error;
}

export type BasicsView = 'disabled' | 'collecting' | 'provisional' | 'credible';

/**
 * Which state of the page a response shows.
 */
export function basicsView(data: InsightBasics): BasicsView {
  if (!data.enabled || data.heat_loss === null) return 'disabled';
  return data.heat_loss.status;
}

/**
 * Kilowatts with one decimal from watts, "–" for null.
 */
export function kw(watts: number | null | undefined, lang: Language): string {
  if (watts === null || watts === undefined || !Number.isFinite(watts)) return '–';
  return new Intl.NumberFormat(lang, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    .format(watts / 1000)
    .replace('-', '−');
}

/**
 * A temperature in °C with at most one decimal.
 */
export function celsius(value: number | null | undefined, lang: Language): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '–';
  return `${formatNum(value, 1, lang)} °C`;
}

/**
 * Index of the table row whose supply temperature is nearest to `supply`, 0 without one.
 */
export function nearestRow(table: EmitterRow[], supply: number | null): number {
  if (table.length === 0 || supply === null) return 0;
  let best = 0;
  for (let i = 1; i < table.length; i++) {
    const row = table[i] as EmitterRow;
    const current = table[best] as EmitterRow;
    if (Math.abs(row.supply_c - supply) < Math.abs(current.supply_c - supply)) best = i;
  }
  return best;
}

export type Verdict = 'surplus' | 'shortfall' | 'balanced';

/**
 * Surplus, shortfall or balance of one table row against the heat loss now; null without a loss.
 */
export function verdict(row: EmitterRow): Verdict | null {
  if (row.margin_w === null) return null;
  if (Math.abs(row.margin_w) < BALANCED_W) return 'balanced';
  return row.margin_w > 0 ? 'surplus' : 'shortfall';
}

export type ScatterKind = 'used' | 'outlier' | 'near_balance';

export interface FitPoint {
  x: number;
  y: number;
  mark: ScatterKind;
  label: string;
}

/**
 * Chart points of the fit windows: room minus outside (K) against heat (kW).
 */
export function fitPoints(points: HeatLossPoint[], describe: (p: HeatLossPoint) => string) {
  return points.map((p): FitPoint => ({
    x: p.delta_k,
    y: p.heat_w / 1000,
    mark: p.use,
    label: describe(p),
  }));
}

/**
 * The fitted line `P = H x dT - G` in kW, from where it crosses zero to the largest dT shown.
 */
export function fitLine(
  loss: HeatLoss,
  xMax: number,
): { from: [number, number]; to: [number, number] } | null {
  const { h_w_per_k: h, offset_w: g } = loss;
  if (h === null || g === null || h <= 0) return null;
  const x0 = Math.max(g / h, 0);
  return {
    from: [x0, (h * x0 - g) / 1000],
    to: [xMax, (h * xMax - g) / 1000],
  };
}

/**
 * Bars of one figure per outside-temperature bin; bins with few days are drawn muted.
 */
export function binItems(
  bins: WeatherBin[],
  pick: (bin: WeatherBin) => number | null,
  options: {
    color: string;
    lang: Language;
    note: (bin: WeatherBin, from: string, to: string) => string;
  },
): BarItem[] {
  return bins.map((bin) => {
    const value = pick(bin);
    const from = formatNum(bin.from_c, 0, options.lang);
    const to = formatNum(bin.to_c, 0, options.lang);
    return {
      label: from,
      value: value !== null && Number.isFinite(value) ? value : null,
      color: bin.few_days ? `color-mix(in srgb, ${options.color} 35%, transparent)` : options.color,
      note: options.note(bin, from, to),
    };
  });
}

/**
 * A local date such as "1 Dec" from a `YYYY-MM-DD` string.
 */
export function shortDate(date: string, lang: Language): string {
  const parsed = new Date(`${date}T12:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return date;
  return parsed.toLocaleDateString(timeLocale(lang), {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });
}
