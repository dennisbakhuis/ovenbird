import type { ServerResponse } from 'node:http';
import type {
  Compaction,
  CompactResult,
  ConfigDoc,
  HistorySignals,
  HistoryStorage,
  StorageResolution,
  StoredSignal,
} from '../src/lib/core/types';
import { csvCell, toCsv, type CsvExport } from './csv.ts';
import { HISTORY_SIGNALS, historySignalInfo, makeHistory } from './fixtures.ts';
import {
  PRESET_IDS,
  RETENTION_FIELDS,
  RETENTION_PRESETS,
  matchPreset,
  type RetentionField,
} from '../src/lib/system/retention.ts';
import type { Scenario } from './scenario.ts';

const MINUTE = 60_000;
const DAY = 86_400_000;
const HISTORY_DAYS = 40;
const ROLLUP_STEPS = [60, 900, 3600] as const;
const EXPORT_STEPS: Record<string, number> = { raw: 0, '60': 60, '900': 900, '3600': 3600 };
const MAX_EXPORT_DAYS = { fine: 1, coarse: 7 };
const RECLAIMABLE = 24_117_248;
const FREE_BYTES = 182_400_000_000;
const WAL_BYTES = 4_124_152;

interface Rate {
  id: StorageResolution['id'];
  field: string | null;
  rows: number;
  bytes: number;
}

const RATES: readonly Rate[] = [
  { id: 'raw', field: 'history_raw_days', rows: 4_600, bytes: 116_500 },
  { id: '60', field: 'history_1m_days', rows: 61_400, bytes: 2_576_000 },
  { id: '900', field: 'history_15m_days', rows: 4_100, bytes: 171_700 },
  { id: '3600', field: 'history_1h_days', rows: 1_020, bytes: 42_900 },
  { id: 'journal', field: 'history_decision_days', rows: 1_540, bytes: 825_700 },
  { id: 'forecast', field: 'history_decision_days', rows: 150, bytes: 9_200 },
];

const TABLES: readonly [string, Rate['id'][], number][] = [
  ['rollup', ['60', '900', '3600'], 0.69],
  ['rollup_step_bucket', ['60', '900', '3600'], 0.31],
  ['decision', ['journal'], 0.96],
  ['sample', ['raw'], 0.57],
  ['sample_ts', ['raw'], 0.43],
  ['decision_ts', ['journal'], 0.02],
  ['command', ['journal'], 0.02],
  ['forecast', ['forecast'], 1],
];

const compactions = new Map<string, { at: number; freed: number }>();

/**
 * Signal ids the mock history holds (the generated ones, without the legacy room alias).
 */
export const STORED_SIGNALS = HISTORY_SIGNALS.filter((id) => id.includes('/'));

const iso = (ms: number) => new Date(ms).toISOString().replace('.000Z', 'Z');
const floorTo = (ms: number, stepMs: number) => Math.floor(ms / stepMs) * stepMs;

/**
 * `GET history/signals`: every stored signal with a range per resolution. Raw samples go back
 * 14 days (states change rarely, numbers often); the rollups go back 40 days.
 */
export function makeHistorySignals(now: number): HistorySignals {
  const start = floorTo(now, DAY) - HISTORY_DAYS * DAY;
  const signals: StoredSignal[] = STORED_SIGNALS.map((id, index) => {
    const info = historySignalInfo(id);
    const state = info?.state ?? false;
    const rawFirst = floorTo(now, DAY) - 14 * DAY + (index % 5) * MINUTE;
    const resolutions = [
      {
        step: 0,
        first: iso(rawFirst),
        last: iso(floorTo(now, MINUTE) - (index % 3) * MINUTE),
        points: state ? 40 + index * 7 : 2_000 + index * 911,
      },
      ...ROLLUP_STEPS.map((step) => {
        const last = floorTo(now, step * 1000) - step * 1000;
        return {
          step,
          first: iso(start),
          last: iso(last),
          points: Math.floor((last - start) / (step * 1000)) + 1,
        };
      }),
    ];
    return { id, unit: info?.unit ?? null, kind: state ? 'enum' : 'number', resolutions };
  });
  return { signals };
}

function keptDays(doc: ConfigDoc, field: string | null): number | null {
  const value = field ? doc.fields[field]?.value : null;
  return typeof value === 'number' && value > 0 ? value : null;
}

/**
 * Size once every limited resolution is full, and the growth per year of what is kept forever,
 * at the retention `kept` gives per field (null keeps forever).
 */
function project(kept: (field: string | null) => number | null): [number, number] {
  let projected = 65_536;
  let growth = 0;
  for (const rate of RATES) {
    const days = kept(rate.field);
    if (days === null) {
      projected += rate.bytes * (rate.id === 'raw' ? 14 : HISTORY_DAYS);
      growth += rate.bytes * 365;
    } else projected += rate.bytes * days;
  }
  return [Math.round(projected), Math.round(growth)];
}

function compactionOf(key: string): Compaction {
  const done = compactions.get(key);
  return {
    pending: false,
    running: false,
    last_at: done ? iso(done.at) : null,
    freed_bytes: done ? done.freed : null,
    error: null,
  };
}

/**
 * `GET history/storage`: sizes after 40 days of history at the retention in `doc`, the
 * projection, and the state of the last `POST history/compact` of this browser's scenario.
 */
export function makeStorage(now: number, doc: ConfigDoc, key: string): HistoryStorage {
  const compacted = compactions.has(key);
  const resolutions: StorageResolution[] = RATES.map((rate) => {
    const kept = keptDays(doc, rate.field);
    const held = Math.min(kept ?? Infinity, rate.id === 'raw' ? 14 : HISTORY_DAYS);
    return {
      id: rate.id,
      retention_days: kept,
      rows: Math.round(rate.rows * held),
      oldest: iso(floorTo(now, MINUTE) - held * DAY),
      newest: iso(floorTo(now, MINUTE)),
      bytes: Math.round(rate.bytes * held),
      bytes_per_day: rate.bytes,
    };
  });
  const bytesOf = (ids: Rate['id'][]) =>
    resolutions.filter((r) => ids.includes(r.id)).reduce((sum, r) => sum + (r.bytes ?? 0), 0);
  const tables = TABLES.map(([name, ids, share]) => ({
    name,
    bytes: Math.round((bytesOf(ids) * share) / 4096) * 4096,
    rows: name.endsWith('_ts') || name.endsWith('_bucket') ? null : Math.round(bytesOf(ids) / 40),
  })).sort((a, b) => b.bytes - a.bytes);
  const current = project((field) => keptDays(doc, field));
  const presets = PRESET_IDS.map((id) => {
    const values = RETENTION_PRESETS[id];
    const kept = (field: string | null) => {
      const days = field ? values[field as RetentionField] : 0;
      return days > 0 ? days : null;
    };
    const [projected, growth] = project(kept);
    return { id, values: { ...values }, projected_bytes: projected, growth_bytes_per_year: growth };
  });
  const values = Object.fromEntries(
    RETENTION_FIELDS.map((field) => [field, keptDays(doc, field) ?? 0]),
  );
  const preset = matchPreset(values);
  const reclaimable = compacted ? 0 : RECLAIMABLE;
  const database = tables.reduce((sum, table) => sum + table.bytes, 65_536) + reclaimable;
  return {
    files: {
      database,
      wal: WAL_BYTES,
      snapshot: Math.round(database * 0.97),
      free: FREE_BYTES,
    },
    tables,
    resolutions,
    projected_bytes: current[0],
    growth_bytes_per_year: current[1],
    reclaimable_bytes: reclaimable,
    auto_vacuum: compacted ? 'incremental' : 'none',
    presets,
    preset: preset === 'custom' ? null : preset,
    compaction: compactionOf(key),
  };
}

/**
 * `POST history/compact`: the mock compacts at once; the next storage report shows it done.
 */
export function compact(now: number, key: string): CompactResult {
  const freed = compactions.has(key) ? 0 : RECLAIMABLE;
  compactions.set(key, { at: now, freed });
  return { accepted: true, compaction: { ...compactionOf(key), pending: true } };
}

/**
 * Forget the compactions (tests).
 */
export function resetCompactions(): void {
  compactions.clear();
}

export interface Download {
  status: number;
  type: string;
  filename: string | null;
  body: string | Uint8Array;
}

const refusal = (status: number, detail: string): Download => ({
  status,
  type: 'application/json',
  filename: null,
  body: JSON.stringify({ detail }),
});

function windowOf(params: URLSearchParams, now: number): { from: number; to: number } | Download {
  const from = params.get('from') ? Date.parse(params.get('from') as string) : 0;
  const to = params.get('to') ? Date.parse(params.get('to') as string) : now;
  if (Number.isNaN(from) || Number.isNaN(to)) return refusal(400, 'from/to must be ISO 8601');
  if (to < from) return refusal(400, 'to must not be before from');
  return { from, to };
}

const stamp = (ms: number) => iso(ms).replace(/[^0-9A-Za-z_-]/g, '-');

/**
 * `GET export/series` as the service writes it (long or wide, CSV or NDJSON). The mock
 * generates at most the last day of a fine step and the last week of a coarse one.
 */
export function seriesExport(params: URLSearchParams, now: number): Download {
  const stepId = params.get('step') ?? '900';
  const layout = params.get('layout') ?? 'long';
  const format = params.get('format') ?? 'csv';
  if (!(stepId in EXPORT_STEPS)) return refusal(422, 'step must be raw, 60, 900 or 3600');
  if (layout !== 'long' && layout !== 'wide') return refusal(422, 'layout must be long or wide');
  if (format !== 'csv' && format !== 'ndjson') return refusal(422, 'format must be csv or ndjson');
  const asked = (params.get('signals') ?? 'all').trim();
  const ids =
    asked === 'all' ? STORED_SIGNALS : [...new Set(asked.split(',').map((s) => s.trim()))];
  const unknown = ids.filter((id) => !STORED_SIGNALS.includes(id));
  if (unknown.length > 0)
    return refusal(400, `no stored history for signal(s): ${unknown.join(', ')}`);
  const range = windowOf(params, now);
  if ('status' in range) return range;
  const step = EXPORT_STEPS[stepId] ?? 900;
  const cap = (step <= 60 ? MAX_EXPORT_DAYS.fine : MAX_EXPORT_DAYS.coarse) * DAY;
  const to = Math.min(range.to, now);
  const from = Math.max(range.from, to - cap);
  const history = makeHistory(ids, from, to, step === 0 ? 60 : step, {} as Scenario, now);
  const rollup = step > 0;
  const rows: { at: string; signal: string; unit: string | null; value: unknown }[] = [];
  for (const id of ids)
    for (const [at, value] of history.series[id]?.points ?? [])
      rows.push({
        at: iso(Date.parse(at)),
        signal: id,
        unit: history.series[id]?.unit ?? null,
        value,
      });
  rows.sort((a, b) => a.at.localeCompare(b.at) || ids.indexOf(a.signal) - ids.indexOf(b.signal));
  const lines: string[] = [];
  const csvLine = (cells: unknown[]) => cells.map(csvCell).join(',');
  if (layout === 'long') {
    if (format === 'csv')
      lines.push(csvLine(['at', 'signal', 'unit', 'value', ...(rollup ? ['min', 'max'] : [])]));
    for (const row of rows) {
      const tail = rollup ? [row.value, row.value] : [];
      lines.push(
        format === 'csv'
          ? csvLine([row.at, row.signal, row.unit, row.value, ...tail])
          : JSON.stringify(rollup ? { ...row, min: row.value, max: row.value } : row),
      );
    }
  } else {
    if (format === 'csv') lines.push(csvLine(['at', ...ids]));
    const times = [...new Set(rows.map((row) => row.at))];
    for (const at of times) {
      const values = Object.fromEntries(
        rows.filter((row) => row.at === at).map((row) => [row.signal, row.value]),
      );
      lines.push(
        format === 'csv'
          ? csvLine([at, ...ids.map((id) => values[id] ?? null)])
          : JSON.stringify({ at, values }),
      );
    }
  }
  return {
    status: 200,
    type: format === 'csv' ? 'text/csv; charset=utf-8' : 'application/x-ndjson',
    filename: `ovenbird-series-${stepId}-${layout}-${stamp(range.from)}.${format}`,
    body: lines.length > 0 ? `${lines.join('\n')}\n` : '',
  };
}

const JOURNAL_CSV: Record<string, CsvExport | null> = {
  decisions: 'decisions',
  commands: 'commands',
  alarms: 'alarms',
  forecast: null,
};

/**
 * `GET export/journal/{kind}` from the rows the mock already serves for the Activity pages.
 */
export function journalExport(
  kind: string,
  params: URLSearchParams,
  now: number,
  rows: (from: number, to: number) => readonly object[],
): Download {
  if (!(kind in JOURNAL_CSV))
    return refusal(422, 'kind must be decisions, commands, alarms or forecast');
  const format = params.get('format') ?? 'csv';
  if (format !== 'csv' && format !== 'ndjson') return refusal(422, 'format must be csv or ndjson');
  const range = windowOf(params, now);
  if ('status' in range) return range;
  const items = rows(range.from, Math.min(range.to, now));
  const csvName = JOURNAL_CSV[kind];
  const body =
    format === 'ndjson'
      ? items.map((item) => `${JSON.stringify(item)}\n`).join('')
      : csvName
        ? toCsv(csvName, items).replace(/\r\n/g, '\n')
        : 'issued_at,target_at,temp_c,radiation_wm2,cloud_pct,wind_ms\n';
  return {
    status: 200,
    type: format === 'csv' ? 'text/csv; charset=utf-8' : 'application/x-ndjson',
    filename: `ovenbird-${kind}-${stamp(range.from)}.${format}`,
    body,
  };
}

/**
 * `GET export/archive`: an empty zip under the service's file name; 403 for a viewer.
 */
export function archiveExport(now: number, scenario: Scenario): Download {
  if (scenario.role === 'viewer') return refusal(403, 'this action needs the admin role');
  const empty = new Uint8Array(22);
  empty.set([0x50, 0x4b, 0x05, 0x06]);
  return {
    status: 200,
    type: 'application/zip',
    filename: `ovenbird-archive-${stamp(now)}.zip`,
    body: empty,
  };
}

/**
 * Write a download as the service does: its media type, an attachment name and no caching.
 */
export function sendDownload(res: ServerResponse, download: Download): void {
  res.statusCode = download.status;
  res.setHeader('Content-Type', download.type);
  if (download.filename) {
    res.setHeader('Content-Disposition', `attachment; filename="${download.filename}"`);
    res.setHeader('Cache-Control', 'no-store');
  }
  res.end(download.body);
}
