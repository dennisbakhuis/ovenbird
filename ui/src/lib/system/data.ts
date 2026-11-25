import { dispositionName, saveBlob } from '$lib/core/download';
import type { StoredSignal, StorageResolution } from '$lib/core/types';

export type ExportStep = 'raw' | '60' | '900' | '3600';
export type ExportLayout = 'long' | 'wide';
export type ExportFormat = 'csv' | 'ndjson';
export type JournalKind = 'decisions' | 'commands' | 'alarms' | 'forecast';
export type RangePreset = '1d' | '7d' | '30d' | 'all' | 'custom';

export const STEPS: readonly ExportStep[] = ['raw', '60', '900', '3600'];
export const JOURNALS: readonly JournalKind[] = ['decisions', 'commands', 'alarms', 'forecast'];
export const ARCHIVE_PATH = 'api/v1/export/archive';

const DAY_MS = 86_400_000;
const ISO_CHARS = 20;
const VALUE_CHARS = 7;
const NDJSON_LONG_KEYS = 40;
const NDJSON_WIDE_KEYS = 22;
const UNITS = ['B', 'kB', 'MB', 'GB', 'TB'] as const;

export interface SeriesRequest {
  signals: string[] | 'all';
  from: Date | null;
  to: Date | null;
  step: ExportStep;
  layout: ExportLayout;
  format: ExportFormat;
}

export interface Estimate {
  rows: number;
  bytes: number;
}

/**
 * Seconds of an export step (`raw` is 0).
 */
export function stepSeconds(step: ExportStep): number {
  return step === 'raw' ? 0 : Number(step);
}

function windowParams(from: Date | null, to: Date | null): URLSearchParams {
  const query = new URLSearchParams();
  if (from) query.set('from', from.toISOString());
  if (to) query.set('to', to.toISOString());
  return query;
}

/**
 * Path of `GET export/series` for a request (`all` when every signal is chosen).
 */
export function seriesUrl(request: SeriesRequest): string {
  const query = windowParams(request.from, request.to);
  query.set('signals', request.signals === 'all' ? 'all' : request.signals.join(','));
  query.set('step', request.step);
  query.set('layout', request.layout);
  query.set('format', request.format);
  return `api/v1/export/series?${query.toString()}`;
}

/**
 * Path of `GET export/journal/{kind}` for a window and format.
 */
export function journalUrl(
  kind: JournalKind,
  from: Date | null,
  to: Date | null,
  format: ExportFormat,
): string {
  const query = windowParams(from, to);
  query.set('format', format);
  return `api/v1/export/journal/${kind}?${query.toString()}`;
}

/**
 * The window of a range preset ending at `now`; `all` and `custom` leave the bounds to the caller.
 */
export function presetWindow(preset: RangePreset, now: number): { from: Date | null; to: Date } {
  const days = preset === '1d' ? 1 : preset === '7d' ? 7 : preset === '30d' ? 30 : null;
  return { from: days === null ? null : new Date(now - days * DAY_MS), to: new Date(now) };
}

/**
 * Points of one signal expected in `[from, to)` at a step: its stored points times the share of
 * its stored range the window covers (rollups are dense, raw changes roughly even).
 */
export function expectedPoints(
  signal: StoredSignal,
  step: ExportStep,
  from: number,
  to: number,
): number {
  const seconds = stepSeconds(step);
  const range = signal.resolutions.find((item) => item.step === seconds);
  if (!range || to <= from) return 0;
  const first = Date.parse(range.first);
  const last = Date.parse(range.last) + Math.max(seconds, 1) * 1000;
  const overlap = Math.max(0, Math.min(to, last) - Math.max(from, first));
  const span = last - first;
  if (span <= 0) return overlap > 0 ? range.points : 0;
  return Math.round((range.points * overlap) / span);
}

/**
 * Rough size of a series download before compression: rows and bytes for the chosen signals,
 * window, step, layout and format.
 */
export function estimateSeries(
  signals: StoredSignal[],
  step: ExportStep,
  layout: ExportLayout,
  format: ExportFormat,
  from: number,
  to: number,
): Estimate {
  const rollup = step !== 'raw';
  const counts = signals.map((signal) => expectedPoints(signal, step, from, to));
  const total = counts.reduce((sum, n) => sum + n, 0);
  if (total === 0) return { rows: 0, bytes: 0 };
  if (layout === 'long') {
    let bytes = 0;
    signals.forEach((signal, index) => {
      const n = counts[index] ?? 0;
      const fixed = ISO_CHARS + signal.id.length + (signal.unit?.length ?? 0) + VALUE_CHARS + 4;
      const extra = rollup ? 2 * (VALUE_CHARS + 1) : 0;
      const keys = format === 'ndjson' ? NDJSON_LONG_KEYS + (rollup ? 14 : 0) : 0;
      bytes += n * (fixed + extra + keys);
    });
    return { rows: total, bytes };
  }
  const rows = rollup ? Math.max(...counts) : total;
  if (format === 'csv')
    return { rows, bytes: rows * (ISO_CHARS + 1 + signals.length * 2) + total * VALUE_CHARS };
  const perValue =
    signals.reduce((sum, s) => sum + s.id.length, 0) / signals.length + VALUE_CHARS + 4;
  return { rows, bytes: rows * (ISO_CHARS + NDJSON_WIDE_KEYS) + total * perValue };
}

/**
 * The earliest and latest time any of the signals has data at a step, or null.
 */
export function signalsSpan(
  signals: StoredSignal[],
  step: ExportStep,
): { first: number; last: number } | null {
  const seconds = stepSeconds(step);
  let first = Infinity;
  let last = -Infinity;
  for (const signal of signals) {
    const range = signal.resolutions.find((item) => item.step === seconds);
    if (!range) continue;
    first = Math.min(first, Date.parse(range.first));
    last = Math.max(last, Date.parse(range.last));
  }
  return Number.isFinite(first) ? { first, last } : null;
}

/**
 * Bytes as a short text (`12.3 MB`), in the UI language's number format.
 */
export function formatBytes(bytes: number | null | undefined, locale?: string): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '–';
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  const text = new Intl.NumberFormat(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
  return `${text} ${UNITS[unit]}`;
}

/**
 * Resolutions in display order with a stable i18n key suffix.
 */
export function resolutionKey(item: Pick<StorageResolution, 'id'>): string {
  return item.id === 'raw' || item.id === 'journal' || item.id === 'forecast'
    ? item.id
    : `step${item.id}`;
}

export type ArchiveFailure = 'forbidden' | 'space' | 'busy' | 'missing' | 'failed';

/**
 * Why an archive request failed, from its HTTP status.
 */
export function archiveFailure(status: number): ArchiveFailure {
  if (status === 401 || status === 403) return 'forbidden';
  if (status === 507) return 'space';
  if (status === 409) return 'busy';
  if (status === 404 || status === 405) return 'missing';
  return 'failed';
}

/**
 * Fetch `GET export/archive` and save it under the service's file name. Resolves to null when
 * saved, or why it failed.
 */
export function downloadArchive(fallback: string): Promise<ArchiveFailure | null> {
  return downloadFrom(ARCHIVE_PATH, fallback);
}

/**
 * Fetch a zip download (the export archive, or a month, year or season of the yearly archive)
 * and save it under the service's file name. Resolves to null when saved, or why it failed.
 */
export async function downloadFrom(path: string, fallback: string): Promise<ArchiveFailure | null> {
  try {
    const response = await fetch(path, { headers: { Accept: 'application/zip' } });
    if (!response.ok) return archiveFailure(response.status);
    const name = dispositionName(response.headers.get('Content-Disposition')) ?? fallback;
    saveBlob(await response.blob(), name);
    return null;
  } catch {
    return 'failed';
  }
}
