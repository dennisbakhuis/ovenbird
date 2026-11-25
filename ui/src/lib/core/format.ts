import { translateOptional, type Language } from '$lib/i18n';
import type { Signal } from './types';

/**
 * Narrow no-break space placed between a value and its unit.
 */
export const UNIT_SPACE = ' ';

const DAY_MS = 86_400_000;
const AMERICAN_ZONE = /^(America|US|Canada)\/|^Pacific\/Honolulu$/;

let currentLanguage: () => Language = () => 'en';

/**
 * Set where the duration formatters read the UI language from (the settings store).
 */
export function setFormatLanguage(getter: () => Language): void {
  currentLanguage = getter;
}

let currentClock: () => number = () => Date.now();

/**
 * Set the clock that relative labels ("today 14:22") and data windows default to: the service
 * clock in the app, so a service on its own clock (the simulator) still reads as "now".
 */
export function setClock(clock: () => number): void {
  currentClock = clock;
}

/**
 * The current time in epoch ms on the clock set with `setClock` (the browser clock by default).
 */
export function clockNow(): number {
  return currentClock();
}

type DurationUnit = 'unitSecond' | 'unitMinute' | 'unitHour' | 'unitDay';
const UNIT_FALLBACK: Record<DurationUnit, string> = {
  unitSecond: 's',
  unitMinute: 'min',
  unitHour: 'h',
  unitDay: 'd',
};

function durationUnits(language: Language): Record<DurationUnit, string> {
  const pick = (key: DurationUnit) => translateOptional(language, key) ?? UNIT_FALLBACK[key];
  return {
    unitSecond: pick('unitSecond'),
    unitMinute: pick('unitMinute'),
    unitHour: pick('unitHour'),
    unitDay: pick('unitDay'),
  };
}

/**
 * Format a duration in seconds as a short age such as "12 s", "5 min", "3 h" ("3 u"), "2 d".
 */
export function formatAge(
  seconds: number | null | undefined,
  language: Language = currentLanguage(),
): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '–';
  const u = durationUnits(language);
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} ${u.unitSecond}`;
  if (s < 3600) return `${Math.floor(s / 60)} ${u.unitMinute}`;
  if (s < 86400) return `${Math.floor(s / 3600)} ${u.unitHour}`;
  return `${Math.floor(s / 86400)} ${u.unitDay}`;
}

/**
 * Format a duration in seconds with two units at most, e.g. "45 s", "22 min", "1 h 20 min"
 * ("1 u 20 min" in Dutch), "2 d 3 h".
 */
export function formatDuration(
  seconds: number | null | undefined,
  language: Language = currentLanguage(),
): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '–';
  const u = durationUnits(language);
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} ${u.unitSecond}`;
  const minutes = Math.round(s / 60);
  if (minutes < 60) return `${minutes} ${u.unitMinute}`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24)
    return minutes % 60
      ? `${hours} ${u.unitHour} ${minutes % 60} ${u.unitMinute}`
      : `${hours} ${u.unitHour}`;
  const days = Math.floor(hours / 24);
  return hours % 24 ? `${days} ${u.unitDay} ${hours % 24} ${u.unitHour}` : `${days} ${u.unitDay}`;
}

/**
 * Format a number with at most `digits` decimals, using the given locale.
 */
export function formatNumber(value: number, digits = 1, locale?: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);
}

/**
 * Format a number with its unit, separated by a narrow no-break space; "–" when missing.
 */
export function formatWithUnit(
  value: number | null | undefined,
  unit: string | null | undefined,
  digits = 1,
  locale?: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '–';
  const text = formatNumber(value, digits, locale);
  return unit ? `${text}${UNIT_SPACE}${unit}` : text;
}

/**
 * Render a signal value with its label or unit.
 */
export function formatSignalValue(signal: Signal, locale?: string): string {
  const { value, label, unit } = signal;
  if (value === null || value === undefined) return '–';
  if (label) return `${label} (${String(value)})`;
  if (typeof value === 'number')
    return unit ? `${formatNumber(value, 2, locale)} ${unit}` : formatNumber(value, 2, locale);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return unit ? `${value} ${unit}` : value;
}

/**
 * Convert watts to a kW string with one decimal.
 */
export function formatKilowatts(watts: number, locale?: string): string {
  return formatNumber(watts / 1000, 1, locale);
}

/**
 * Age of a signal at `nowMs`, extending the server-reported age by the time since receipt.
 */
export function effectiveAge(age: number | null, receivedAtMs: number, nowMs: number): number {
  return (age ?? 0) + Math.max(0, (nowMs - receivedAtMs) / 1000);
}

function browserLanguages(): readonly string[] {
  return typeof navigator === 'undefined' ? [] : navigator.languages;
}

function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return 'UTC';
  }
}

/**
 * Locale used for dates and times. A full tag ("en-GB") is used as given. A UI language takes
 * the region of the first browser tag in that language; English without a region, or with US,
 * becomes British English (24 h) unless the device clock is on an American time zone.
 */
export function timeLocale(
  language: string | undefined,
  browser: readonly string[] = browserLanguages(),
  timeZone: string = browserTimeZone(),
): string | undefined {
  if (!language) return undefined;
  if (language.includes('-')) return language;
  const tag = browser.find((candidate) => candidate.toLowerCase().split('-')[0] === language);
  if (language !== 'en') return tag?.includes('-') ? tag : language === 'nl' ? 'nl-NL' : language;
  const region = tag?.split('-')[1]?.toUpperCase();
  if (region && region !== 'US') return tag;
  return AMERICAN_ZONE.test(timeZone) ? 'en-US' : 'en-GB';
}

function toDate(iso: string | number | null | undefined): Date | null {
  if (iso === null || iso === undefined) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(ms: number): number {
  const date = new Date(ms);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/**
 * Whole calendar days from the day of `nowMs` to the day of `ms` (local time): 0 today, -1 yesterday.
 */
export function dayOffset(ms: number, nowMs: number): number {
  return Math.round((startOfDay(ms) - startOfDay(nowMs)) / DAY_MS);
}

/**
 * Format an ISO timestamp as a local clock time, e.g. "14:22" (or "2:22 PM" in the US).
 */
export function formatClock(iso: string | number | null | undefined, locale?: string): string {
  const date = toDate(iso);
  if (!date) return '–';
  return date.toLocaleTimeString(timeLocale(locale), { hour: '2-digit', minute: '2-digit' });
}

/**
 * Format an ISO timestamp as a short local date and time: "today 14:22", "yesterday 08:18",
 * "tomorrow 06:00" for a UI language, otherwise "5 Jan, 14:22" (with the year when it differs).
 */
export function formatDateTime(
  iso: string | number | null | undefined,
  locale?: string,
  nowMs: number = clockNow(),
): string {
  const date = toDate(iso);
  if (!date) return '–';
  const resolved = timeLocale(locale);
  const clock = date.toLocaleTimeString(resolved, { hour: '2-digit', minute: '2-digit' });
  const offset = dayOffset(date.getTime(), nowMs);
  const key = offset === 0 ? 'timeToday' : offset === -1 ? 'timeYesterday' : 'timeTomorrow';
  if (Math.abs(offset) <= 1 && locale && !locale.includes('-')) {
    const relative = translateOptional(locale as Language, key, { time: clock });
    if (relative) return relative;
  }
  const sameYear = date.getFullYear() === new Date(nowMs).getFullYear();
  return date.toLocaleString(resolved, {
    day: 'numeric',
    month: 'short',
    year: sameYear ? undefined : 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Format an ISO timestamp as a day label: "Today", "Tomorrow", "Yesterday" or a short weekday
 * with date ("Mon 5 Jan").
 */
export function formatDay(
  iso: string | number | null | undefined,
  locale?: string,
  nowMs: number = clockNow(),
): string {
  const date = toDate(iso);
  if (!date) return '–';
  const offset = dayOffset(date.getTime(), nowMs);
  const key = offset === 0 ? 'dayToday' : offset === -1 ? 'dayYesterday' : 'dayTomorrow';
  if (Math.abs(offset) <= 1 && locale && !locale.includes('-')) {
    const relative = translateOptional(locale as Language, key);
    if (relative) return relative;
  }
  return date.toLocaleDateString(timeLocale(locale), {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}
