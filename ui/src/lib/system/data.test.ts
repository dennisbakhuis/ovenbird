import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  archiveExport,
  compact,
  journalExport,
  makeHistorySignals,
  makeStorage,
  resetCompactions,
  seriesExport,
  STORED_SIGNALS,
} from '$mock/data';
import config from '$mock/fixtures/config.json';
import { checkField } from '$lib/core/schema';
import { formatValue } from '$lib/core/fieldFormat';
import schema from '$mock/fixtures/schema.json';
import type { ConfigDoc, ConfigSchema, StoredSignal } from '$lib/core/types';
import {
  archiveFailure,
  downloadArchive,
  estimateSeries,
  expectedPoints,
  formatBytes,
  journalUrl,
  presetWindow,
  resolutionKey,
  seriesUrl,
  signalsSpan,
} from './data';

const NOW = Date.parse('2026-11-20T12:00:00Z');
const DAY = 86_400_000;
const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;

const signal = (id: string, unit: string | null, points: number, days = 10): StoredSignal => ({
  id,
  unit,
  kind: 'number',
  resolutions: [
    {
      step: 0,
      first: new Date(NOW - days * DAY).toISOString(),
      last: new Date(NOW).toISOString(),
      points,
    },
    {
      step: 900,
      first: new Date(NOW - days * DAY).toISOString(),
      last: new Date(NOW - 900_000).toISOString(),
      points: days * 96,
    },
  ],
});

afterEach(() => {
  resetCompactions();
  vi.unstubAllGlobals();
});

describe('export paths', () => {
  it('builds the series path with every choice and `all` for every signal', () => {
    const from = new Date('2026-11-01T00:00:00Z');
    const to = new Date('2026-11-02T00:00:00Z');
    const path = seriesUrl({ signals: 'all', from, to, step: '60', layout: 'wide', format: 'csv' });
    const [base, query] = path.split('?') as [string, string];
    expect(base).toBe('api/v1/export/series');
    expect(Object.fromEntries(new URLSearchParams(query))).toEqual({
      from: '2026-11-01T00:00:00.000Z',
      to: '2026-11-02T00:00:00.000Z',
      signals: 'all',
      step: '60',
      layout: 'wide',
      format: 'csv',
    });
    const some = seriesUrl({
      signals: ['main/Outside_Temp', 'main/Pump_Flow'],
      from: null,
      to: null,
      step: 'raw',
      layout: 'long',
      format: 'ndjson',
    });
    expect(new URLSearchParams(some.split('?')[1]).get('signals')).toBe(
      'main/Outside_Temp,main/Pump_Flow',
    );
    expect(some).not.toContain('from=');
  });

  it('builds journal paths and preset windows', () => {
    expect(journalUrl('alarms', null, null, 'ndjson')).toBe(
      'api/v1/export/journal/alarms?format=ndjson',
    );
    expect(presetWindow('7d', NOW).from?.getTime()).toBe(NOW - 7 * DAY);
    expect(presetWindow('all', NOW).from).toBeNull();
  });
});

describe('size estimate', () => {
  it('scales the stored points by the share of the range covered', () => {
    const outside = signal('main/Outside_Temp', '°C', 1000);
    expect(expectedPoints(outside, 'raw', NOW - 5 * DAY, NOW)).toBe(500);
    expect(expectedPoints(outside, 'raw', NOW - 20 * DAY, NOW)).toBe(1000);
    expect(expectedPoints(outside, '900', NOW - 2 * DAY, NOW)).toBe(192);
    expect(expectedPoints(outside, '60', NOW - DAY, NOW)).toBe(0);
    expect(expectedPoints(outside, 'raw', NOW, NOW - DAY)).toBe(0);
  });

  it('estimates rows and bytes for long and wide layouts', () => {
    const chosen = [
      signal('main/Outside_Temp', '°C', 1000),
      signal('main/Pump_Flow', 'l/min', 500),
    ];
    const long = estimateSeries(chosen, '900', 'long', 'csv', NOW - DAY, NOW);
    expect(long.rows).toBe(192);
    expect(long.bytes).toBeGreaterThan(192 * 40);
    const wide = estimateSeries(chosen, '900', 'wide', 'csv', NOW - DAY, NOW);
    expect(wide.rows).toBe(96);
    expect(wide.bytes).toBeLessThan(long.bytes);
    const ndjson = estimateSeries(chosen, '900', 'long', 'ndjson', NOW - DAY, NOW);
    expect(ndjson.bytes).toBeGreaterThan(long.bytes);
    expect(estimateSeries([], '900', 'long', 'csv', NOW - DAY, NOW)).toEqual({ rows: 0, bytes: 0 });
  });

  it('finds the span of the chosen signals at a step', () => {
    const span = signalsSpan([signal('a/b', null, 10, 3), signal('c/d', null, 10, 8)], '900');
    expect(span).toEqual({ first: NOW - 8 * DAY, last: NOW - 900_000 });
    expect(signalsSpan([signal('a/b', null, 10)], '3600')).toBeNull();
  });

  it('formats bytes in the UI language', () => {
    expect(formatBytes(512, 'en')).toBe('512 B');
    expect(formatBytes(152_027_136, 'en')).toBe('152 MB');
    expect(formatBytes(2_575_952, 'nl')).toBe('2,6 MB');
    expect(formatBytes(null, 'en')).toBe('–');
    expect(resolutionKey({ id: '900' })).toBe('step900');
    expect(resolutionKey({ id: 'journal' })).toBe('journal');
  });
});

describe('archive download', () => {
  it('names each refusal', () => {
    expect([401, 403, 507, 409, 404, 500].map(archiveFailure)).toEqual([
      'forbidden',
      'forbidden',
      'space',
      'busy',
      'missing',
      'failed',
    ]);
  });

  it('reports a refused archive without saving anything', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 403 })),
    );
    expect(await downloadArchive('x.zip')).toBe('forbidden');
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new Error('offline'))),
    );
    expect(await downloadArchive('x.zip')).toBe('failed');
  });
});

describe('retention fields', () => {
  it('accepts 0 as forever without a soft warning and checks other values', () => {
    expect(checkField(sch, 'history_raw_days', 0, doc)).toEqual({ error: null, warning: null });
    expect(checkField(sch, 'history_raw_days', 120, doc).warning).toBe('above_soft_max');
    expect(checkField(sch, 'history_raw_days', -1, doc).error).toBe('below_min');
  });

  it('shows 0 and an unset retention as forever', () => {
    const words = { on: 'on', off: 'off', none: 'none', forever: 'forever' };
    const def = sch.fields['history_1h_days'];
    expect(formatValue(def, null, 'en', words)).toBe('forever');
    expect(formatValue(def, 0, 'en', words)).toBe('forever');
    expect(formatValue(def, 400, 'en', words)).toBe('400 d');
  });
});

describe('mock data endpoints', () => {
  it('lists every stored signal with raw and rollup ranges', () => {
    const body = makeHistorySignals(NOW);
    expect(body.signals.map((s) => s.id)).toEqual(STORED_SIGNALS);
    const outlet = body.signals.find((s) => s.id === 'main/Main_Outlet_Temp');
    expect(outlet?.unit).toBe('°C');
    expect(outlet?.resolutions.map((r) => r.step)).toEqual([0, 60, 900, 3600]);
    expect(outlet?.resolutions[3]?.points).toBe(40 * 24 + 12);
  });

  it('follows the retention in the configuration and the compaction', () => {
    const before = makeStorage(NOW, doc, 'k');
    expect(before.resolutions.find((r) => r.id === '60')?.retention_days).toBe(90);
    expect(before.resolutions.find((r) => r.id === '3600')?.retention_days).toBeNull();
    expect(before.growth_bytes_per_year).toBeGreaterThan(0);
    expect(before.reclaimable_bytes).toBeGreaterThan(0);
    const result = compact(NOW, 'k');
    expect(result.accepted).toBe(true);
    const after = makeStorage(NOW, doc, 'k');
    expect(after.reclaimable_bytes).toBe(0);
    expect(after.auto_vacuum).toBe('incremental');
    expect(after.compaction?.freed_bytes).toBe(before.reclaimable_bytes);
    expect(after.files.database).toBe(before.files.database - before.reclaimable_bytes);
  });

  it('writes series exports in the service layouts and refuses unknown signals', () => {
    const query = (text: string) => new URLSearchParams(text);
    const long = seriesExport(query('signals=main/Outside_Temp&step=3600'), NOW);
    const lines = String(long.body).trim().split('\n');
    expect(lines[0]).toBe('at,signal,unit,value,min,max');
    expect(lines[1]).toMatch(/^2026-11-\d\dT\d\d:00:00Z,main\/Outside_Temp,°C,/);
    expect(long.filename).toMatch(/^ovenbird-series-3600-long-.*\.csv$/);
    const wide = seriesExport(
      query('signals=main/Outside_Temp,main/Pump_Flow&step=900&layout=wide&format=ndjson'),
      NOW,
    );
    const first = JSON.parse(String(wide.body).split('\n')[0] ?? '{}');
    expect(Object.keys(first.values)).toEqual(['main/Outside_Temp', 'main/Pump_Flow']);
    expect(seriesExport(query('signals=nope'), NOW).status).toBe(400);
    expect(seriesExport(query('step=5'), NOW).status).toBe(422);
  });

  it('writes journals and refuses the archive to a viewer', () => {
    const rows = () => [{ at: '2026-11-20T10:00:00Z', code: 'x', message: '=SUM(A1)' }];
    const csv = journalExport('alarms', new URLSearchParams(), NOW, rows);
    expect(String(csv.body).split('\n')[0]).toBe('at,code,severity,event,message,detail');
    expect(String(csv.body)).toContain("'=SUM(A1)");
    expect(journalExport('forecast', new URLSearchParams(), NOW, () => []).body).toBe(
      'issued_at,target_at,temp_c,radiation_wm2,cloud_pct,wind_ms\n',
    );
    expect(journalExport('other', new URLSearchParams(), NOW, rows).status).toBe(422);
    expect(archiveExport(NOW, {}).type).toBe('application/zip');
    expect(archiveExport(NOW, { role: 'viewer' }).status).toBe(403);
  });
});
