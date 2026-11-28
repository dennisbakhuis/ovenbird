import { formatNumber } from '$lib/core/format';
import { minus } from '$lib/core/minus';

export const BOOST_OFFSETS = [-1, 0.5, 1, 1.5] as const;
export const BOOST_HOURS = [1, 2, 4] as const;
export const AWAY_MAX_DAYS = 60;

const HOUR_S = 3600;
const DAY_MS = 86_400_000;

/**
 * The offset choice closest to the service's default boost, so the control opens on it.
 */
export function nearestOffset(defaultK: number | null | undefined): number {
  const target = typeof defaultK === 'number' ? defaultK : 1;
  return BOOST_OFFSETS.reduce((best, k) =>
    Math.abs(k - target) < Math.abs(best - target) ? k : best,
  );
}

/**
 * The duration choice (hours) closest to the service's default boost length.
 */
export function nearestHours(defaultS: number | null | undefined): number {
  const target = typeof defaultS === 'number' ? defaultS / HOUR_S : 2;
  return BOOST_HOURS.reduce((best, h) =>
    Math.abs(h - target) < Math.abs(best - target) ? h : best,
  );
}

/**
 * An offset with its sign: "+0.5", "−1".
 */
export function signedOffset(k: number, locale: string): string {
  const text = formatNumber(Math.abs(k), 2, locale);
  return k < 0 ? minus(`-${text}`) : `+${text}`;
}

/**
 * Seconds left of a request that ends at `untilIso`, measured on the service clock; never below 0.
 */
export function secondsLeft(untilIso: string | null | undefined, nowMs: number): number | null {
  if (!untilIso) return null;
  const until = Date.parse(untilIso);
  return Number.isFinite(until) ? Math.max(0, Math.round((until - nowMs) / 1000)) : null;
}

const pad = (n: number) => String(n).padStart(2, '0');

/**
 * Local `YYYY-MM-DD` of a moment.
 */
export function localDate(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * Where the away form starts: the evening of the day after tomorrow, local time.
 */
export function defaultAwayEnd(nowMs: number): { date: string; time: string } {
  return { date: localDate(nowMs + 2 * DAY_MS), time: '18:00' };
}

/**
 * The ISO moment a local date and time stand for, or null for an incomplete or impossible entry.
 */
export function awayUntil(date: string, time: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time)) return null;
  const moment = new Date(`${date}T${time}:00`);
  return Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}

export type AwayProblem = 'too_soon' | 'too_far';

/**
 * Why the service would refuse this end of away: it must lie beyond the comfort lead and within
 * 60 days. Null when it is fine.
 */
export function awayProblem(untilMs: number, nowMs: number, leadS: number): AwayProblem | null {
  if (untilMs <= nowMs + leadS * 1000) return 'too_soon';
  if (untilMs > nowMs + AWAY_MAX_DAYS * DAY_MS) return 'too_far';
  return null;
}
