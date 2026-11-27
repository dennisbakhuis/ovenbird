import { ApiError, getJson, isMissing } from '$lib/core/api';
import type { HouseWhatIf, WhatIfInputs, WhatIfLimit } from './shapes';

export const WHATIF_RANGES = {
  outside_c: { min: -30, max: 30 },
  comfort_c: { min: 5, max: 30 },
  sun_wm2: { min: 0, max: 1000 },
  stove_w: { min: 0, max: 15000 },
} as const;

export const SUN_PRESETS = [0, 150, 500] as const;
export const STOVE_PRESETS = [0, 2000, 5000] as const;
export const DEBOUNCE_MS = 300;

const QUERY_KEYS = {
  outside_c: 'outside',
  comfort_c: 'comfort',
  sun_wm2: 'sun',
  stove_w: 'stove',
} as const;

export const WHATIF_DEFAULTS: WhatIfInputs = {
  outside_c: 0,
  comfort_c: 21,
  sun_wm2: 0,
  stove_w: 0,
};

const clamp = (value: number, key: keyof WhatIfInputs) =>
  Math.min(WHATIF_RANGES[key].max, Math.max(WHATIF_RANGES[key].min, value));

/**
 * The what-if inputs from the page's query (`outside`, `comfort`, `sun`, `stove`); a missing or
 * unreadable value takes its default, a number outside its range is clamped into it.
 */
export function parseWhatIfQuery(
  query: Record<string, string | undefined>,
  defaults: WhatIfInputs = WHATIF_DEFAULTS,
): WhatIfInputs {
  const out = { ...defaults };
  for (const key of Object.keys(QUERY_KEYS) as (keyof WhatIfInputs)[]) {
    const raw = query[QUERY_KEYS[key]];
    if (raw === undefined || raw.trim() === '') continue;
    const value = Number(raw);
    if (Number.isFinite(value)) out[key] = clamp(value, key);
  }
  return out;
}

/**
 * The query that reproduces `inputs`: only the values that differ from the defaults.
 */
export function whatIfQuery(
  inputs: WhatIfInputs,
  defaults: WhatIfInputs = WHATIF_DEFAULTS,
): Record<string, string | undefined> {
  const out: Record<string, string | undefined> = {};
  for (const key of Object.keys(QUERY_KEYS) as (keyof WhatIfInputs)[]) {
    if (inputs[key] !== defaults[key]) out[QUERY_KEYS[key]] = String(inputs[key]);
  }
  return out;
}

/**
 * The request path of the what-if endpoint for `inputs`.
 */
export function whatIfPath(inputs: WhatIfInputs): string {
  const params = new URLSearchParams();
  for (const key of Object.keys(QUERY_KEYS) as (keyof WhatIfInputs)[])
    params.set(key, String(inputs[key]));
  return `api/v1/insight/house/whatif?${params.toString()}`;
}

export type WhatIfResult =
  { kind: 'ready'; data: HouseWhatIf } | { kind: 'no_model' } | { kind: 'absent' };

/**
 * Ask the house model what it would take at these conditions. `no_model` is the 404
 * `house_model_missing`; any other 404/405 is an older service (`absent`).
 */
export async function fetchWhatIf(
  inputs: WhatIfInputs,
  signal?: AbortSignal,
): Promise<WhatIfResult> {
  try {
    return { kind: 'ready', data: await getJson<HouseWhatIf>(whatIfPath(inputs), signal) };
  } catch (error) {
    if (error instanceof ApiError && error.code === 'house_model_missing')
      return { kind: 'no_model' };
    if (isMissing(error)) return { kind: 'absent' };
    throw error;
  }
}

/**
 * Whether the answer was limited by `limit`.
 */
export const isLimitedBy = (result: HouseWhatIf, limit: WhatIfLimit): boolean =>
  result.limited_by.includes(limit);

export interface Drift {
  startC: number;
  endC: number;
  minC: number;
  hours: number;
  stepS: number;
}

/**
 * The drift curve's start and end: where the room starts and where it is after the hours.
 */
export function driftSummary(result: HouseWhatIf): Drift | null {
  const room = result.drift.room_c;
  if (room.length === 0) return null;
  return {
    startC: room[0] as number,
    endC: room[room.length - 1] as number,
    minC: Math.min(...room),
    hours: result.drift.hours,
    stepS: result.drift.step_s,
  };
}
