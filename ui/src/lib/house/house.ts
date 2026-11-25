import { ApiError, getJson, getOptional, isMissing, postJson } from '$lib/core/api';
import type { Curve } from '$lib/core/curve';
import type { MessageKey, Params } from '$lib/i18n';
import type { Schemas } from '$lib/core/types';

export type Interval = [number, number];

export interface Estimate {
  value: number;
  interval_90: Interval | null;
}

export type ScoreBand = Schemas['ScoreBand'];
export type HouseScore = Schemas['HouseScore'];
export type LastRun = Schemas['LastRun'];
export type LearnerAge = Schemas['LearnerHealth'];
export type HouseLearning = Schemas['HouseWaiting'];
export type HouseHistoryModel = Schemas['HouseHistoryModel'];
export type HouseHistory = Schemas['HouseHistory'];

export interface SignaturePoint {
  date: string;
  outside_c: number;
  heat_w: number;
  indoor_c: number | null;
  ghi_w_m2: number | null;
}

export interface SignatureFit {
  h_w_per_k: number;
  h_interval_90: Interval | null;
  gains_w: number | null;
  solar_m2: number | null;
  balance_c: number | null;
  balance_interval_90: Interval | null;
  rmse_w: number | null;
  mean_indoor_c: number | null;
  mean_ghi_w_m2: number | null;
  model?: string;
}

export interface Credibility {
  credible: boolean;
  days: number;
  heating_days: number;
  cold_days: number;
  outside_span_k: number;
  rules: {
    heating_days: number;
    heating_day_w: number;
    cold_days: number;
    cold_day_below_c: number;
    outside_span_k: number;
  };
  needed: { heating_days: number; cold_days: number; outside_span_k: number };
  reasons: string[];
  low_confidence: boolean;
  message: string | null;
}

export interface Validation {
  test_from: string;
  test_to: string;
  score_horizon_h: number;
  challenger_room_rmse_k: number | null;
  champion_room_rmse_k: number | null;
  champion: string | null;
  promoted: boolean;
  rule: string;
}

export interface ErrorTrendEntry {
  model: string;
  data_to: string;
  promoted: boolean;
  ua_w_per_k: number | null;
  room_rmse_24h_k: number | null;
}

export type LimitedBy = 'min_setpoint' | 'max_supply' | 'envelope';

export interface ProposalPoint {
  outside_c: number;
  model_c: number;
  current_c: number;
  heat_w: number;
  extrapolated: boolean;
  water_c: number;
  change_k: number;
  limited_by: LimitedBy | null;
}

export interface Proposal {
  comfort_c: number;
  flow_lpm: number | null;
  credible: boolean;
  stale: boolean;
  based_on_curve: Curve;
  current_curve: Curve;
  curve: Curve;
  points: ProposalPoint[];
  mean_change_k: number;
  max_change_k: number;
  method: string;
}

export interface HouseInsight {
  state: 'ready';
  learner?: LearnerAge;
  schema: string;
  model: string;
  champion: { model: string; promoted_at: string } | null;
  last_run: LastRun | null;
  data: {
    from: string;
    to: string;
    fit_days: number;
    signature_days: number;
    excluded_days: string[];
  };
  ua: {
    w_per_k: number;
    interval_90: Interval | null;
    source: string;
    signature_w_per_k: number | null;
    signature_interval_90: Interval | null;
    low_confidence: boolean;
  };
  time_constant_h: Estimate | null;
  solar_aperture_m2: Estimate | null;
  internal_gains_w: Estimate | null;
  balance_temperature_c: Estimate | null;
  signature: { indoor: string; points: SignaturePoint[]; fit: SignatureFit | null } | null;
  credibility: Credibility;
  score: HouseScore;
  validation: Validation | null;
  error_trend: ErrorTrendEntry[];
  daily_error: { date: string; room_rmse_24h_k: number | null; origins: number }[];
  proposal: Proposal | null;
  events: unknown[];
  limits: string[];
  provenance: Record<string, unknown>;
}

/** The draft of `POST insight/house/proposal/draft`; its `points` are the learner's. */
export type ProposalDraft = Omit<Schemas['ProposalDraft'], 'points'> & { points: ProposalPoint[] };

export type HouseResult =
  | { kind: 'ready'; data: HouseInsight }
  | { kind: 'learning'; data: HouseLearning }
  | { kind: 'missing' };

/**
 * The learned house model. A body with `state` `learning` or `not_run` means the learner has not
 * promoted a model yet (`learning`): newer services answer 200 with it, older ones 404. A 404
 * without such a body means the backend does not have the endpoint (`missing`).
 */
export async function fetchHouse(signal?: AbortSignal): Promise<HouseResult> {
  try {
    const data = await getJson<HouseInsight | HouseLearning>('api/v1/insight/house', signal);
    if (isLearning(data)) return { kind: 'learning', data };
    return { kind: 'ready', data };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      const body = error.body as Partial<HouseLearning> | null;
      if (isLearning(body)) return { kind: 'learning', data: body };
    }
    if (isMissing(error)) return { kind: 'missing' };
    throw error;
  }
}

function isLearning(body: unknown): body is HouseLearning {
  const state = (body as { state?: unknown } | null)?.state;
  return state === 'learning' || state === 'not_run';
}

/**
 * One entry per promoted model; null when the backend does not have the endpoint.
 */
export function fetchHouseHistory(signal?: AbortSignal): Promise<HouseHistory | null> {
  return getOptional<HouseHistory>('api/v1/insight/house/history', signal);
}

/**
 * Turn the champion's curve proposal into a configuration draft (nothing is stored).
 */
export function draftProposal(): Promise<ProposalDraft> {
  return postJson<ProposalDraft>('api/v1/insight/house/proposal/draft', {});
}

export const BAND_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G'] as const;

/**
 * Where a heat loss per m² sits on a scale of the bands, 0 (left edge of A) to 1 (right edge of
 * G); every band takes the same width and G is drawn as wide as F.
 */
export function bandPosition(wPerM2: number, bands: ScoreBand[]): number {
  const count = bands.length;
  if (count === 0) return 0;
  const uppers: number[] = [];
  for (const [i, band] of bands.entries()) {
    const previous = uppers[i - 1] ?? 0;
    const width = previous - (uppers[i - 2] ?? 0) || 30;
    uppers.push(band.below_w_per_m2 ?? previous + width);
  }
  const index = uppers.findIndex((upper) => wPerM2 < upper);
  if (index < 0) return 1;
  const lower = uppers[index - 1] ?? 0;
  const upper = uppers[index] ?? lower + 1;
  const share = Math.min(1, Math.max(0, (wPerM2 - lower) / (upper - lower)));
  return (index + share) / count;
}

export type NeedKind = 'heating_days' | 'cold_days' | 'outside_span_k';

export interface Need {
  kind: NeedKind;
  amount: number;
}

/**
 * What the credibility rules still miss, in a fixed order, only the positive amounts (days
 * rounded up, the outside spread in K to one decimal).
 */
export function learningNeeds(credibility: Credibility | null | undefined): Need[] {
  if (!credibility || credibility.credible) return [];
  const needed = credibility.needed;
  const out: Need[] = [];
  if (needed.heating_days > 0)
    out.push({ kind: 'heating_days', amount: Math.ceil(needed.heating_days) });
  if (needed.cold_days > 0) out.push({ kind: 'cold_days', amount: Math.ceil(needed.cold_days) });
  if (needed.outside_span_k > 0)
    out.push({ kind: 'outside_span_k', amount: Math.round(needed.outside_span_k * 10) / 10 });
  return out;
}

/**
 * The energy signature's fitted heat at an outside temperature: H × (balance − outside) below
 * the balance temperature, 0 above it; null without a fit.
 */
export function signatureHeat(
  fit: SignatureFit | null | undefined,
  outside: number,
): number | null {
  if (!fit || fit.balance_c === null) return null;
  return Math.max(0, fit.h_w_per_k * (fit.balance_c - outside));
}

/**
 * Whether a proposed curve differs from the current one by more than 0.05 K at any point.
 */
export function curveDiffers(a: Curve | null | undefined, b: Curve | null | undefined): boolean {
  if (!a || !b) return true;
  if (a.length !== b.length) return true;
  return a.some(
    (point, i) =>
      Math.abs(point[0] - (b[i]?.[0] ?? NaN)) > 0.05 ||
      Math.abs(point[1] - (b[i]?.[1] ?? NaN)) > 0.05,
  );
}

export type Translate = (key: MessageKey, params?: Params) => string;

/**
 * "Still learning: 4 more cold days (daily mean below 5 °C) needed", built from the numbers of
 * the credibility rules (not from the service's English message).
 */
export function needsText(
  needs: Need[],
  credibility: Credibility | null | undefined,
  tr: Translate,
  format: (value: number, digits?: number) => string,
): string {
  if (needs.length === 0) return tr('houseStillLearningPlain');
  const below = format(credibility?.rules.cold_day_below_c ?? 5, 0);
  const parts = needs.map((need) => {
    if (need.kind === 'outside_span_k')
      return tr('houseNeed_outside_span_k', { n: format(need.amount, 1) });
    const one = need.amount === 1;
    if (need.kind === 'cold_days')
      return tr(one ? 'houseNeedOne_cold_days' : 'houseNeed_cold_days', {
        n: need.amount,
        below,
      });
    return tr(one ? 'houseNeedOne_heating_days' : 'houseNeed_heating_days', { n: need.amount });
  });
  return tr('houseStillLearning', { list: parts.join(', ') });
}

/**
 * The W/m² limits of each band as short labels under the scale: "< 30" for A, "30–45" for B, …,
 * "≥ 125" for G; null where the service gives no limit for a letter.
 */
export function bandLimits(
  bands: ScoreBand[],
  num: (value: number) => string,
): Record<string, string | null> {
  const out: Record<string, string | null> = {};
  let previous: number | null = null;
  for (const band of bands) {
    const upper = band.below_w_per_m2;
    out[band.band] =
      upper === null
        ? previous === null
          ? null
          : `≥\u202f${num(previous)}`
        : previous === null
          ? `<\u202f${num(upper)}`
          : `${num(previous)}–${num(upper)}`;
    previous = upper ?? previous;
  }
  return out;
}
