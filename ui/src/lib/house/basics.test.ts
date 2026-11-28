import { describe, expect, it, vi } from 'vitest';
import { makeBasics } from '$mock/basics';
import {
  basicsView,
  binItems,
  celsius,
  fetchBasics,
  fitLine,
  kw,
  nearestRow,
  shortDate,
  verdict,
  type EmitterRow,
} from './basics';

const NOW = Date.parse('2026-11-15T14:00:00');

describe('basics view', () => {
  it('maps the response to the page state', () => {
    expect(basicsView(makeBasics(NOW, 'off'))).toBe('disabled');
    expect(basicsView(makeBasics(NOW, 'collecting'))).toBe('collecting');
    expect(basicsView(makeBasics(NOW, 'provisional'))).toBe('provisional');
    expect(basicsView(makeBasics(NOW))).toBe('credible');
  });
});

describe('formatting', () => {
  it('gives kilowatts with one decimal and temperatures in the language', () => {
    expect(kw(2826, 'en')).toBe('2.8');
    expect(kw(2826, 'nl')).toBe('2,8');
    expect(kw(null, 'en')).toBe('–');
    expect(celsius(-3, 'en')).toContain('3 °C');
    expect(celsius(21.5, 'nl')).toBe('21,5 °C');
    expect(shortDate('2026-12-01', 'en')).toBe('1 Dec');
  });
});

describe('emitter table', () => {
  const rows = makeBasics(NOW).heat_pump?.emitter.table ?? [];

  it('starts the slider at the balancing supply temperature', () => {
    const balance = makeBasics(NOW).heat_pump?.emitter.balance_supply_c ?? null;
    const index = nearestRow(rows, balance);
    expect(rows[index]?.supply_c).toBe(30);
    expect(nearestRow(rows, null)).toBe(0);
    expect(nearestRow([], 30)).toBe(0);
  });

  it('calls a row a surplus, a shortfall or in balance', () => {
    const row = (margin: number | null) => ({ ...(rows[0] as EmitterRow), margin_w: margin });
    expect(verdict(row(400))).toBe('surplus');
    expect(verdict(row(-400))).toBe('shortfall');
    expect(verdict(row(20))).toBe('balanced');
    expect(verdict(row(null))).toBeNull();
    expect(verdict(rows[0] as EmitterRow)).toBe('shortfall');
    expect(verdict(rows[rows.length - 1] as EmitterRow)).toBe('surplus');
  });
});

describe('fit line', () => {
  it('runs from zero heat at the balance offset to the largest difference', () => {
    const fit = makeBasics(NOW).heat_loss;
    if (!fit) throw new Error('no fit');
    const line = fitLine(fit, 21);
    expect(line?.from[1]).toBeCloseTo(0, 6);
    expect(line?.from[0]).toBeCloseTo(600 / 180, 6);
    expect(line?.to).toEqual([21, (180 * 21 - 600) / 1000]);
  });

  it('gives no line without a slope', () => {
    const fit = makeBasics(NOW, 'collecting').heat_loss;
    if (!fit) throw new Error('no fit');
    expect(fitLine(fit, 10)).toBeNull();
  });
});

describe('weather bins', () => {
  it('mutes bins with few days and notes the range', () => {
    const bins = makeBasics(NOW).by_weather ?? [];
    const items = binItems(bins, (b) => b.heat_w / 1000, {
      color: 'red',
      lang: 'en',
      note: (b, from, to) => `${from}..${to} ${b.days}`,
    });
    expect(items).toHaveLength(bins.length);
    expect(items[0]?.color).toContain('color-mix');
    expect(items[3]?.color).toBe('red');
    expect(items[3]?.note).toBe('2..4 12');
  });
});

describe('fetchBasics', () => {
  it('answers missing on a 404 and throws on a 500', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 404 })),
    );
    expect(await fetchBasics()).toEqual({ kind: 'missing' });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{}', { status: 500 })),
    );
    await expect(fetchBasics()).rejects.toThrow();
    vi.unstubAllGlobals();
  });
});
