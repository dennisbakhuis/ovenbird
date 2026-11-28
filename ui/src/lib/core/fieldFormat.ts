import { asCurve, type Curve } from './curve';
import { displayUnit, toDisplay } from './schema';
import type { FieldDef } from './types';

export interface Words {
  on: string;
  off: string;
  none: string;
  forever?: string;
}

export interface QuietWindow {
  start: string;
  end: string;
  level: number;
}

/**
 * Whether a value is a 24-hour clock time written `HH:MM`; used to give a text field of the
 * schema (which has no clock type) a time input.
 */
export function isClockTime(value: unknown): boolean {
  return typeof value === 'string' && /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
}

/**
 * Coerce an unknown value to quiet-mode windows, or null when it is not a list of them.
 */
export function asWindows(value: unknown): QuietWindow[] | null {
  if (!Array.isArray(value)) return null;
  const out: QuietWindow[] = [];
  for (const item of value) {
    const w = item as Partial<QuietWindow> | null;
    if (
      !w ||
      typeof w.start !== 'string' ||
      typeof w.end !== 'string' ||
      typeof w.level !== 'number'
    )
      return null;
    out.push({ start: w.start, end: w.end, level: w.level });
  }
  return out;
}

/**
 * Format a config value for display in its schema unit (minutes/hours for durations).
 */
export function formatValue(
  def: FieldDef | undefined,
  value: unknown,
  locale: string,
  words: Words,
): string {
  if (def?.type === 'retention' && (value === null || value === undefined || value === 0))
    return words.forever ?? words.none;
  if (value === null || value === undefined) return words.none;
  if (def?.type === 'mqtt_inputs' && Array.isArray(value))
    return value.length === 0
      ? words.none
      : value
          .map((item) => {
            const row = (item ?? {}) as { topic?: unknown; signal?: unknown };
            const topic = String(row.topic ?? '');
            return typeof row.signal === 'string' && row.signal
              ? `${topic} → ${row.signal}`
              : topic;
          })
          .join(' · ');
  if (typeof value === 'boolean') return value ? words.on : words.off;
  if (typeof value === 'number') {
    const shown = def ? toDisplay(def, value) : value;
    const unit = def ? displayUnit(def) : '';
    const text = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(shown);
    return unit ? `${text} ${unit}` : text;
  }
  if (Array.isArray(value) && value.length === 0) return words.none;
  const curve = asCurve(value);
  if (curve) return curve.map(([o, w]) => `${o} → ${w}`).join(' · ');
  const windows = asWindows(value);
  if (windows)
    return windows.length === 0
      ? words.none
      : windows.map((w) => `${w.start}–${w.end} (${w.level})`).join(' · ');
  if (Array.isArray(value)) return value.length === 0 ? words.none : value.join(', ');
  return String(value);
}

/**
 * Decimal separator of a locale ("." for en, "," for nl).
 */
export function decimalSeparator(locale: string): string {
  return (
    new Intl.NumberFormat(locale).formatToParts(1.5).find((p) => p.type === 'decimal')?.value ?? '.'
  );
}

/**
 * A number as typed into an input: the locale's decimal separator, no grouping, up to six
 * decimals; empty for null.
 */
export function formatInputNumber(value: number | null | undefined, locale: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '';
  const text = String(Math.round(value * 1e6) / 1e6);
  return text.replace('.', decimalSeparator(locale)).replace('-', '−');
}

/**
 * Parse a typed number accepting a point or a comma and a typographic minus; null when the
 * text is empty or not a number.
 */
export function parseInputNumber(text: string): number | null {
  const clean = text.trim().replace(/\s/g, '').replace(',', '.').replace('−', '-');
  if (clean === '' || clean === '-' || clean === '.') return null;
  if (!/^-?(\d+\.?\d*|\.\d+)$/.test(clean)) return null;
  const value = Number(clean);
  return Number.isFinite(value) ? value : null;
}

/**
 * Signed difference `to − from` with a typographic minus, e.g. "+0.6" or "−2"; null when either
 * side is not a number.
 */
export function formatDelta(from: unknown, to: unknown, locale: string, digits = 1): string | null {
  if (typeof from !== 'number' || typeof to !== 'number') return null;
  const delta = Math.round((to - from) * 10 ** digits) / 10 ** digits;
  const text = new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(
    Math.abs(delta),
  );
  return delta > 0 ? `+${text}` : delta < 0 ? `−${text}` : '±0';
}

/**
 * Short form of a curve: water values and their outside temperatures, each joined by " / ".
 */
export function curveText(curve: Curve, locale: string): { water: string; outside: string } {
  const fmt = (v: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(v).replace('-', '−');
  return {
    water: curve.map(([, water]) => fmt(water)).join(' / '),
    outside: curve.map(([outside]) => fmt(outside)).join(' / '),
  };
}
