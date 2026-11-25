import { afterEach, describe, expect, it, vi } from 'vitest';
import { translate } from '$lib/i18n';
import {
  bandLimits,
  bandPosition,
  curveDiffers,
  fetchHouse,
  learningNeeds,
  needsText,
  signatureHeat,
  type Credibility,
  type ScoreBand,
} from './house';

const BANDS: ScoreBand[] = [
  { band: 'A', below_w_per_m2: 30 },
  { band: 'B', below_w_per_m2: 45 },
  { band: 'C', below_w_per_m2: 60 },
  { band: 'D', below_w_per_m2: 80 },
  { band: 'E', below_w_per_m2: 100 },
  { band: 'F', below_w_per_m2: 125 },
  { band: 'G', below_w_per_m2: null },
];

function credibility(needed: Credibility['needed'], credible = false): Credibility {
  return {
    credible,
    days: 38,
    heating_days: 37,
    cold_days: 6,
    outside_span_k: 13.4,
    rules: {
      heating_days: 30,
      heating_day_w: 300,
      cold_days: 10,
      cold_day_below_c: 5,
      outside_span_k: 10,
    },
    needed,
    reasons: [],
    low_confidence: false,
    message: null,
  };
}

const en = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
  translate('en', key, params);
const nl = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
  translate('nl', key, params);
const fmt = (value: number, digits = 1) => value.toFixed(digits).replace(/\.0+$/, '');

describe('bandPosition', () => {
  it('places a value inside its band on an even scale', () => {
    expect(bandPosition(0, BANDS)).toBe(0);
    expect(bandPosition(15, BANDS)).toBeCloseTo(0.5 / 7);
    expect(bandPosition(48.1, BANDS)).toBeCloseTo((2 + 3.1 / 15) / 7);
    expect(bandPosition(125, BANDS)).toBeCloseTo(6 / 7);
    expect(bandPosition(500, BANDS)).toBe(1);
  });
});

describe('bandLimits', () => {
  it('labels every band with its W/m² limits', () => {
    const limits = bandLimits(BANDS, (value) => String(value));
    expect(limits['A']).toBe('<\u202f30');
    expect(limits['C']).toBe('45–60');
    expect(limits['G']).toBe('≥\u202f125');
  });
});

describe('learning needs', () => {
  it('lists only what is missing, in order', () => {
    expect(
      learningNeeds(credibility({ heating_days: 0, cold_days: 4, outside_span_k: 0 })),
    ).toEqual([{ kind: 'cold_days', amount: 4 }]);
    expect(
      learningNeeds(credibility({ heating_days: 2.2, cold_days: 1, outside_span_k: 1.25 })),
    ).toEqual([
      { kind: 'heating_days', amount: 3 },
      { kind: 'cold_days', amount: 1 },
      { kind: 'outside_span_k', amount: 1.3 },
    ]);
    expect(
      learningNeeds(credibility({ heating_days: 0, cold_days: 0, outside_span_k: 0 }, true)),
    ).toEqual([]);
  });

  it('builds the sentence from the numbers in both languages', () => {
    const c = credibility({ heating_days: 0, cold_days: 4, outside_span_k: 0 });
    expect(needsText(learningNeeds(c), c, en, fmt)).toBe(
      'Still learning: 4 more cold days (daily mean below 5 °C) needed.',
    );
    expect(needsText(learningNeeds(c), c, nl, fmt)).toBe(
      'Nog aan het leren: nog 4 koude dagen (daggemiddelde onder 5 °C) nodig.',
    );
    const one = credibility({ heating_days: 1, cold_days: 1, outside_span_k: 2 });
    expect(needsText(learningNeeds(one), one, en, fmt)).toBe(
      'Still learning: 1 more heating day, 1 more cold day (daily mean below 5 °C), 2 K more spread in outside temperature needed.',
    );
    expect(needsText([], c, en, fmt)).toBe('Still learning: not enough data for a score yet.');
  });
});

describe('signature and curve helpers', () => {
  it('draws the fit as zero above the balance temperature', () => {
    const fit = {
      h_w_per_k: 240,
      h_interval_90: null,
      gains_w: null,
      solar_m2: null,
      balance_c: 16.5,
      balance_interval_90: null,
      rmse_w: null,
      mean_indoor_c: null,
      mean_ghi_w_m2: null,
    };
    expect(signatureHeat(fit, 6.5)).toBe(2400);
    expect(signatureHeat(fit, 20)).toBe(0);
    expect(signatureHeat(null, 0)).toBeNull();
  });

  it('compares curves within 0.05 K', () => {
    const a: [number, number][] = [
      [-10, 39],
      [15, 25],
    ];
    expect(
      curveDiffers(a, [
        [-10, 39.01],
        [15, 25],
      ]),
    ).toBe(false);
    expect(
      curveDiffers(a, [
        [-10, 40],
        [15, 25],
      ]),
    ).toBe(true);
    expect(curveDiffers(a, null)).toBe(true);
  });
});

describe('fetchHouse', () => {
  afterEach(() => vi.unstubAllGlobals());

  const respond = (status: number, body: unknown) =>
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(body), { status })),
    );

  it('tells a learning model from a missing endpoint', async () => {
    respond(404, { state: 'learning', missing: ['9 more days'] });
    expect(await fetchHouse()).toEqual({
      kind: 'learning',
      data: { state: 'learning', missing: ['9 more days'] },
    });
    respond(404, { state: 'not_run', missing: [] });
    expect((await fetchHouse()).kind).toBe('learning');
    respond(404, { detail: 'Not Found' });
    expect(await fetchHouse()).toEqual({ kind: 'missing' });
    respond(200, { state: 'ready', model: 'house-1' });
    expect((await fetchHouse()).kind).toBe('ready');
    respond(200, { state: 'not_run', missing: [] });
    expect(await fetchHouse()).toEqual({
      kind: 'learning',
      data: { state: 'not_run', missing: [] },
    });
    respond(200, { state: 'learning', last_run: null });
    expect((await fetchHouse()).kind).toBe('learning');
    respond(500, {});
    await expect(fetchHouse()).rejects.toThrow();
  });
});
