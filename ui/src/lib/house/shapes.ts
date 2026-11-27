import type { Schemas } from '$lib/core/types';

/**
 * Response shapes of the house endpoints added with the balance, the prediction series and the
 * what-if. The balance, series and what-if shapes are the generated ones; the `provenance` additions of
 * `GET insight/house` are still typed by hand (the generated body leaves `provenance` open).
 */

export type BalanceSource = Schemas['HouseSource'];
export type BalanceNote = Schemas['BalanceNote'];
export type BalanceFlows = Schemas['BalanceFlows'];
export type HouseBalance = Schemas['HouseBalance'];
export type SeriesPoint = HouseSeries['points'][number];
export type HouseSeries = Schemas['HouseSeries'];
export type WhatIfLimit = Schemas['WhatIfLimit'];
export type WhatIfInputs = Schemas['WhatIfInputs'];
export type HouseWhatIf = Schemas['HouseWhatIf'];

export interface ToldValues {
  ua_w_per_k: number | null;
  solar_aperture_m2: number | null;
  internal_gain_w: number | null;
}

export interface LearningProvenance {
  fit_days: number;
  test_days: number;
  tolerance_k: number;
  excluded_days: string[];
  excluded_days_in_fit: number;
}

/** What `provenance` of `GET insight/house` gains; the older keys stay untyped. */
export interface HouseProvenance {
  constraints?: Record<string, unknown>;
  told?: ToldValues;
  learning?: LearningProvenance;
  [key: string]: unknown;
}
