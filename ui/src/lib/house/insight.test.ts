import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  barItems,
  dayLabel,
  fetchInsightDaily,
  lastDays,
  partialIndex,
  totals,
  type InsightDay,
} from './insight';

function day(date: string, over: Partial<InsightDay> = {}): InsightDay {
  return {
    date,
    from: `${date}T00:00:00Z`,
    to: `${date}T23:59:59Z`,
    hours: 24,
    partial: false,
    coverage: 1,
    electric_kwh: 10,
    heat_kwh: 40,
    cop: 4,
    dhw_electric_kwh: null,
    dhw_heat_kwh: null,
    compressor_starts: 4,
    run_s: 7200,
    defrosts: 2,
    defrost_s: 600,
    dhw_runs: 0,
    dhw_s: 0,
    outside_mean_c: 3,
    outside_min_c: 0,
    room_mean_c: 21,
    room_min_c: 20.5,
    comfort_c: 21,
    below_comfort_kh: 1,
    setpoint_mean_c: 30,
    setpoint_changes: 10,
    writes: 10,
    ...over,
  };
}

const NULLS: Partial<InsightDay> = {
  electric_kwh: null,
  heat_kwh: null,
  cop: null,
  compressor_starts: null,
  run_s: null,
  defrosts: null,
  below_comfort_kh: null,
};

const notes = { partial: 'so far', coverage: (p: number) => `coverage ${p} %` };

afterEach(() => vi.unstubAllGlobals());

describe('totals', () => {
  it('sums the known days and skips nulls', () => {
    const result = totals([day('2026-01-13'), day('2026-01-14', NULLS), day('2026-01-15')]);
    expect(result.electricKwh).toBe(20);
    expect(result.heatKwh).toBe(80);
    expect(result.cop).toBeCloseTo(4);
    expect(result.starts).toBe(8);
    expect(result.runH).toBe(4);
    expect(result.missingDays).toBe(1);
  });

  it('keeps a figure null when no day has it', () => {
    const result = totals([day('2026-01-14', NULLS)]);
    expect(result.electricKwh).toBeNull();
    expect(result.cop).toBeNull();
    expect(result.runH).toBeNull();
  });

  it('computes COP only over days with both energies', () => {
    const result = totals([
      day('a', { heat_kwh: null }),
      day('b', { electric_kwh: 5, heat_kwh: 20 }),
    ]);
    expect(result.cop).toBeCloseTo(4);
    expect(result.electricKwh).toBe(15);
  });

  it('flags low coverage and a partial today', () => {
    const result = totals([day('a', { coverage: 0.5 }), day('b', { partial: true })]);
    expect(result.lowCoverageDays).toBe(1);
    expect(result.partialIncluded).toBe(true);
  });
});

describe('spans', () => {
  const thirty = Array.from({ length: 30 }, (_, i) =>
    day(`2026-01-${String(i + 1).padStart(2, '0')}`, { electric_kwh: i }),
  );

  it('slices the last 7 or 30 days, oldest first', () => {
    expect(lastDays(thirty, 7)).toHaveLength(7);
    expect(lastDays(thirty, 7)[0]?.date).toBe('2026-01-24');
    expect(lastDays(thirty, 30)).toHaveLength(30);
    expect(lastDays(thirty.slice(0, 3), 7)).toHaveLength(3);
  });

  it('labels weekdays for a week and day numbers for a month', () => {
    const d = day('2026-01-14');
    expect(dayLabel(d, 'en', 7)).toBe('Wed');
    expect(dayLabel(d, 'en', 30)).toBe('14');
  });
});

describe('barItems', () => {
  const days = [
    day('2026-01-13', { electric_kwh: null }),
    day('2026-01-14', { coverage: 0.62 }),
    day('2026-01-15', { partial: true }),
  ];

  it('draws nulls as gaps, notes low coverage and lightens the partial day', () => {
    const items = barItems(days, (d) => d.electric_kwh, { color: 'red', language: 'en', notes });
    expect(items[0]?.value).toBeNull();
    expect(items[1]?.note).toBe('coverage 62 %');
    expect(items[2]?.note).toBe('so far');
    expect(items[2]?.color).toContain('color-mix');
    expect(items[1]?.color).toBe('red');
    expect(partialIndex(days)).toBe(2);
  });
});

describe('fetchInsightDaily', () => {
  it('returns the document', async () => {
    const body = { timezone: 'UTC', band_below_k: 0.5, room_signal: null, days: [] };
    const spy = vi.fn(async () => new Response(JSON.stringify(body)));
    vi.stubGlobal('fetch', spy);
    const result = await fetchInsightDaily(30);
    expect(result).toEqual({ kind: 'ok', data: body });
    expect(String((spy.mock.calls[0] as unknown[])[0])).toBe('api/v1/insight/daily?days=30');
  });

  it('reports a 404 as missing', async () => {
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 404 }));
    expect(await fetchInsightDaily(7)).toEqual({ kind: 'missing' });
  });

  it('throws on other failures', async () => {
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 500 }));
    await expect(fetchInsightDaily(7)).rejects.toThrow('HTTP 500');
  });
});
