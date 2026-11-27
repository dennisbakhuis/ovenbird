import { afterEach, describe, expect, it, vi } from 'vitest';
import { translate } from '$lib/i18n';
import {
  effectSentence,
  fetchHouseControl,
  planLines,
  planSummarySentence,
  shiftSentence,
  sortBlocks,
  summarisePlan,
} from './plan';
import type { HouseControl, PlanEvaluation, PlanHistory } from './shapes';

const tr = (key: Parameters<typeof translate>[1], params?: Parameters<typeof translate>[2]) =>
  translate('en', key, params);
const trNl = (key: Parameters<typeof translate>[1], params?: Parameters<typeof translate>[2]) =>
  translate('nl', key, params);

const STEP = 900_000;
const BASE = Date.parse('2026-11-20T00:00:00');

function evaluation(over: Partial<PlanEvaluation> = {}): PlanEvaluation {
  return {
    at: new Date(BASE).toISOString(),
    status: 'issued',
    offset_k: -0.3,
    applied: false,
    reason: 'plan_setback',
    valid_until: new Date(BASE + 3_600_000).toISOString(),
    rise_k: 0.6,
    rise_at: new Date(BASE + 3 * 3_600_000).toISOString(),
    fall_k: 0,
    fall_at: null,
    solar_k: 0.6,
    outside_k: 0.1,
    ...over,
  };
}

function control(over: Partial<HouseControl> = {}): HouseControl {
  return {
    use: 'shadow',
    verdict: { ok: true, blocks: [] },
    model: 'house-1',
    model_rmse_k: 0.2,
    bounds: { max_setback_k: 0.5, max_preheat_k: 0.3, horizon_h: 6, max_rmse_k: 0.4 },
    now: evaluation(),
    history: { step_s: 900, from: '', to: '', points: [] },
    ...over,
  };
}

function history(points: [number, number | null, 0 | 1 | null][]): PlanHistory {
  return {
    step_s: 900,
    from: new Date(BASE).toISOString(),
    to: new Date(BASE + 7 * 86_400_000).toISOString(),
    points: points.map(([offset, k, applied]) => [
      new Date(BASE + offset * STEP).toISOString(),
      k,
      applied,
    ]),
  };
}

describe('sortBlocks', () => {
  it('puts what the owner can fix first and unknown codes last', () => {
    expect(sortBlocks(['stove_tail', 'mystery', 'model_not_credible', 'weather_off'])).toEqual([
      'weather_off',
      'model_not_credible',
      'stove_tail',
      'mystery',
    ]);
  });
});

describe('shiftSentence', () => {
  it('says what shadow would do and what on does', () => {
    expect(shiftSentence(control(), tr, 'en')).toMatch(
      /^Would lower the room target by 0\.3 K until/,
    );
    const on = control({ use: 'on', now: evaluation({ applied: true }) });
    expect(shiftSentence(on, tr, 'en')).toMatch(/^Lowers the room target by 0\.3 K until/);
    const up = control({ now: evaluation({ offset_k: 0.2, reason: 'plan_preheat' }) });
    expect(shiftSentence(up, tr, 'en')).toMatch(/^Would raise the room target by 0\.2 K/);
  });

  it('says so when on does not apply the shift', () => {
    const held = control({ use: 'on', now: evaluation({ applied: false }) });
    expect(shiftSentence(held, tr, 'en')).toContain('does not apply it');
  });

  it('names the end as the next evaluation without a valid-until time', () => {
    const open = control({ now: evaluation({ valid_until: null }) });
    expect(shiftSentence(open, tr, 'en')).toContain('until the next evaluation');
  });

  it('explains each reason for no shift', () => {
    const dead = control({ now: evaluation({ status: 'inside_dead_zone', offset_k: 0 }) });
    expect(shiftSentence(dead, tr, 'en')).toBe(
      'No shift now: the expected change stays within the dead zone.',
    );
    expect(shiftSentence(dead, trNl, 'nl')).toContain('dode band');
    for (const status of [
      'crossing_zero',
      'forecast_gap',
      'forecast_mismatch',
      'model_invalid',
      'planner_error',
    ] as const) {
      const text = shiftSentence(control({ now: evaluation({ status, offset_k: 0 }) }), tr, 'en');
      expect(text, status).toMatch(/^No shift now:/);
    }
  });

  it('treats a tiny issued shift as inside the dead zone', () => {
    const tiny = control({ now: evaluation({ offset_k: 0.01 }) });
    expect(shiftSentence(tiny, tr, 'en')).toContain('dead zone');
  });

  it('does not offer an old shift while a guard blocks', () => {
    const blocked = control({ verdict: { ok: false, blocks: ['stove_active'] } });
    expect(shiftSentence(blocked, tr, 'en')).toBe(
      'No shift now: the planner may not act, see below.',
    );
    expect(effectSentence(blocked, tr, 'en')).toBe('');
  });

  it('tells apart off and not evaluated yet', () => {
    expect(shiftSentence(control({ use: 'off', now: null }), tr, 'en')).toContain('not running');
    expect(shiftSentence(control({ now: null }), tr, 'en')).toContain('not evaluated yet');
  });
});

describe('effectSentence', () => {
  it('names the sun, the amount and the time of the warming', () => {
    const text = effectSentence(control(), tr, 'en');
    expect(text).toMatch(
      /^In the next 6 hours the sun is expected to warm the room by about 0\.6 °C, around /,
    );
  });

  it('adds the cooling and names the outside air as its cause', () => {
    const now = evaluation({
      rise_k: 0.4,
      fall_k: 0.7,
      fall_at: new Date(BASE + 5 * 3_600_000).toISOString(),
      solar_k: 0.4,
      outside_k: -0.7,
    });
    const text = effectSentence(control({ now }), tr, 'en');
    expect(text).toContain('Later the colder outside air is expected to cool it by about 0.7 °C');
  });

  it('calls the milder air the cause when it beats the sun', () => {
    const now = evaluation({ solar_k: 0.1, outside_k: 0.5 });
    expect(effectSentence(control({ now }), tr, 'en')).toContain('the milder outside air');
  });

  it('is calm when nothing notable is expected, and empty without an evaluation', () => {
    const calm = control({ now: evaluation({ rise_k: 0.02, fall_k: 0 }) });
    expect(effectSentence(calm, tr, 'en')).toBe(
      'No notable warming or cooling of the room is expected in the next 6 hours.',
    );
    expect(effectSentence(control({ now: null }), tr, 'en')).toBe('');
  });

  it('is Dutch in Dutch', () => {
    expect(effectSentence(control(), trNl, 'nl')).toContain('de zon');
  });
});

describe('summarisePlan', () => {
  it('counts quarters, days and the largest shifts, and skips gaps', () => {
    const day = 96;
    const summary = summarisePlan(
      history([
        [0, 0, 0],
        [1, -0.3, 0],
        [2, -0.4, 1],
        [day + 12, -0.2, 0],
        [day * 2 + 4, 0.3, 0],
        [day * 2 + 5, null, null],
        [day * 3, 0.02, 0],
      ]),
    );
    expect(summary.evaluated).toBe(6);
    expect(summary.shifted).toBe(4);
    expect(summary.applied).toBe(1);
    expect(summary.downDays).toBe(2);
    expect(summary.upDays).toBe(1);
    expect(summary.maxDownK).toBeCloseTo(0.4);
    expect(summary.maxUpK).toBeCloseTo(0.3);
  });

  it('is empty for a history that never computed', () => {
    const summary = summarisePlan(history([[0, null, null]]));
    expect(summary.evaluated).toBe(0);
  });
});

describe('planSummarySentence', () => {
  const sentence = (points: [number, number | null, 0 | 1 | null][], lang: 'en' | 'nl' = 'en') =>
    planSummarySentence(summarisePlan(history(points)), 7, lang === 'en' ? tr : trNl, lang);

  it('says nothing was computed', () => {
    expect(sentence([[0, null, null]])).toBe('In the last 7 days the planner did not evaluate.');
  });

  it('says the model would not have shifted anything', () => {
    expect(sentence([[0, 0, 0]])).toBe(
      'In the last 7 days the model would not have shifted the room target.',
    );
  });

  it('counts the days it would have lowered the target, with the largest shift', () => {
    const text = sentence([
      [0, -0.3, 0],
      [96, -0.4, 0],
      [192, -0.1, 0],
      [288, -0.2, 0],
    ]);
    expect(text).toBe(
      'In the last 7 days the model would have lowered the room target on 4 days, by at most 0.4 K.',
    );
  });

  it('adds raising as a second sentence and uses the singular', () => {
    const text = sentence([
      [0, -0.3, 0],
      [100, 0.2, 0],
    ]);
    expect(text).toBe(
      'In the last 7 days the model would have lowered the room target on 1 day, by at most 0.3 K. It would have raised it on 1 day, by at most 0.2 K.',
    );
  });

  it('speaks in the past tense once the shifts were applied, and says how much was applied', () => {
    const applied = sentence([
      [0, -0.3, 1],
      [1, -0.3, 1],
    ]);
    expect(applied).toBe(
      'In the last 7 days the model lowered the room target on 1 day, by at most 0.3 K.',
    );
    const mixed = sentence([
      [0, -0.3, 1],
      [1, -0.3, 1],
      [2, -0.3, 0],
    ]);
    expect(mixed).toContain('About 0.5 hours of the shifts were applied.');
  });

  it('is natural Dutch', () => {
    const text = sentence(
      [
        [0, -0.3, 0],
        [100, 0.2, 0],
      ],
      'nl',
    );
    expect(text).toContain(
      'zou het model het kamerdoel op 1 dag hebben verlaagd, met hooguit 0,3 K',
    );
  });
});

describe('planLines', () => {
  it('keeps computed points, repeats the applied ones and leaves gaps out', () => {
    const lines = planLines(
      history([
        [0, -0.3, 0],
        [1, null, null],
        [2, -0.2, 1],
      ]),
    );
    expect(lines.computed).toEqual([
      [BASE, -0.3],
      [BASE + 2 * STEP, -0.2],
    ]);
    expect(lines.applied).toEqual([[BASE + 2 * STEP, -0.2]]);
  });
});

describe('fetchHouseControl', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('reads the body', async () => {
    const body = control();
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify(body), { status: 200 }));
    expect((await fetchHouseControl())?.use).toBe('shadow');
  });

  it.each([404, 405])('is null on an older service (%s)', async (status) => {
    vi.stubGlobal('fetch', async () => new Response('{}', { status }));
    expect(await fetchHouseControl()).toBeNull();
  });

  it('throws on a server error', async () => {
    vi.stubGlobal('fetch', async () => new Response('{}', { status: 500 }));
    await expect(fetchHouseControl()).rejects.toThrow();
  });
});
