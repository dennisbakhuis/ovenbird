import { timeLocale } from '$lib/core/format';
import type { ConfigDoc, ConfigVersion } from '$lib/core/types';
import type { HouseInsight } from './house';

export type Subset = 'facts' | 'bounds' | 'learning' | 'plan';

export const SUBSET_GROUP: Record<Subset, string> = {
  facts: 'house',
  bounds: 'house_bounds',
  learning: 'house_learning',
  plan: 'model_plan',
};

export const EXCLUDED_DAYS = 'house_learn_excluded_days';
export const MAX_EXCLUDED_DAYS = 60;

/** Facts the learner starts from; the floor area only feeds the insulation score. */
export const FACT_FIELDS = [
  'house_build_period',
  'house_floor_heating_share',
  'house_occupants',
  'house_volume_m3',
  'house_window_area_m2',
  'house_window_orientation',
] as const;

export interface BoundRow {
  id: 'ua' | 'tau' | 'aperture' | 'gain';
  min: string;
  max: string;
  unit: string;
  digits: number;
}

export const BOUND_ROWS: readonly BoundRow[] = [
  { id: 'ua', min: 'house_ua_min_w_per_k', max: 'house_ua_max_w_per_k', unit: 'W/K', digits: 0 },
  {
    id: 'tau',
    min: 'house_time_constant_min_h',
    max: 'house_time_constant_max_h',
    unit: 'h',
    digits: 0,
  },
  {
    id: 'aperture',
    min: 'house_solar_aperture_min_m2',
    max: 'house_solar_aperture_max_m2',
    unit: 'm²',
    digits: 1,
  },
  {
    id: 'gain',
    min: 'house_internal_gain_min_w',
    max: 'house_internal_gain_max_w',
    unit: 'W',
    digits: 0,
  },
];

export const LEARNING_FIELDS = [
  'house_learn_enabled',
  'house_learn_interval_h',
  'house_learn_fit_days',
  'house_learn_test_days',
  'house_learn_tolerance_k',
  EXCLUDED_DAYS,
] as const;

/** Settings the next learner run applies (the schedule and the floor area do not count). */
export const FIT_FIELDS: ReadonlySet<string> = new Set([
  ...FACT_FIELDS,
  ...BOUND_ROWS.flatMap((row) => [row.min, row.max]),
  'house_learn_fit_days',
  'house_learn_test_days',
  'house_learn_tolerance_k',
  EXCLUDED_DAYS,
]);

export interface Learned {
  value: number;
  interval: [number, number] | null;
}

/**
 * The learned value of a bounded quantity with its 90 % range; null without a model.
 */
export function learnedOf(house: HouseInsight | null, id: BoundRow['id']): Learned | null {
  if (!house) return null;
  const estimate =
    id === 'ua'
      ? { value: house.ua.w_per_k, interval_90: house.ua.interval_90 }
      : id === 'tau'
        ? house.time_constant_h
        : id === 'aperture'
          ? house.solar_aperture_m2
          : house.internal_gains_w;
  return estimate ? { value: estimate.value, interval: estimate.interval_90 } : null;
}

/**
 * Whether a bound pair pins its quantity: both sides set and equal.
 */
export function isPinned(min: unknown, max: unknown): boolean {
  return typeof min === 'number' && typeof max === 'number' && min === max;
}

/**
 * Whether at least one fact about the house is set.
 */
export function anyFactSet(config: ConfigDoc | null): boolean {
  return FACT_FIELDS.some((id) => {
    const value = config?.fields[id]?.value;
    return value !== null && value !== undefined;
  });
}

/**
 * Left-out days as a sorted list of unique ISO dates; anything that is not a date is dropped.
 */
export function cleanDays(days: unknown): string[] {
  if (!Array.isArray(days)) return [];
  const ok = days.filter(
    (d): d is string => typeof d === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(d),
  );
  return [...new Set(ok)].sort();
}

/**
 * Local calendar day (`YYYY-MM-DD`) of a moment.
 */
export function localDay(ms: number): string {
  const date = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * The last day that may be left out: tomorrow, as the service allows a day ahead.
 */
export function latestDay(nowMs: number): string {
  return localDay(nowMs + 86_400_000);
}

export type AddRefusal = 'invalid' | 'future' | 'full';

/**
 * Add a day to the left-out days: sorted, once; refused when it is not a date, lies more than a
 * day ahead, or the list is full. A day already in the list leaves it as it is.
 */
export function addDay(
  days: string[],
  day: string,
  nowMs: number,
  max = MAX_EXCLUDED_DAYS,
): { days: string[]; refusal: AddRefusal | null } {
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(day) && !Number.isNaN(Date.parse(`${day}T00:00:00Z`));
  if (!valid) return { days, refusal: 'invalid' };
  if (day > latestDay(nowMs)) return { days, refusal: 'future' };
  if (days.includes(day)) return { days, refusal: null };
  if (days.length >= max) return { days, refusal: 'full' };
  return { days: cleanDays([...days, day]), refusal: null };
}

/**
 * Leave a day out, or take it back in when it is already left out.
 */
export function toggleDay(days: string[], day: string, max = MAX_EXCLUDED_DAYS): string[] {
  if (days.includes(day)) return days.filter((d) => d !== day);
  return days.length >= max ? days : cleanDays([...days, day]);
}

/**
 * Whether a settings change since the learner last ran has to wait for its next run: a stored
 * version newer than the run that touched a field the fit uses.
 */
export function changedSinceRun(versions: ConfigVersion[], runAt: string | null): boolean {
  if (runAt === null) return false;
  const since = Date.parse(runAt);
  if (!Number.isFinite(since)) return false;
  return versions.some((version) => {
    const at = Date.parse(version.applied_at ?? version.created_at);
    return at > since && version.changed.some((change) => FIT_FIELDS.has(change.field));
  });
}

/**
 * The time of the learner's last run, else of the model in use.
 */
export function modelMadeAt(house: HouseInsight | null): string | null {
  return house?.learner?.last_run_at ?? house?.champion?.promoted_at ?? null;
}

/**
 * A plain `YYYY-MM-DD` day as a short date in the language ("5 Jan 2026").
 */
export function dayLabel(day: string, language: string): string {
  const [year, month, date] = day.split('-').map(Number);
  if (!year || !month || !date) return day;
  return new Date(year, month - 1, date).toLocaleDateString(timeLocale(language), {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}
