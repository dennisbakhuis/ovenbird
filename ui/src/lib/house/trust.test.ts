import { describe, expect, it } from 'vitest';
import { translate } from '$lib/i18n';
import type {
  AtBound,
  GateName,
  GateNeed,
  GateSource,
  HouseInsight,
  ModelGate,
  Revalidation,
  Validation,
} from './house';
import {
  boundRowOf,
  checkRows,
  constraintSentence,
  excitationProgress,
  failingGates,
  gateNeedText,
  gateReasons,
  gateRows,
  gatesPassing,
  ownerBound,
  progressShare,
  revalidationErrors,
  revalidationPassing,
  revalidationSentence,
  structuralBounds,
} from './trust';

const en = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
  translate('en', key, params);
const nl = (key: Parameters<typeof translate>[1], params?: Record<string, string | number>) =>
  translate('nl', key, params);
const fmt = (value: number, digits = 1) => value.toFixed(digits).replace(/\.0+$/, '');

function gate(ok: boolean, needed: GateNeed[] = [], source: GateSource = 'fitted'): ModelGate {
  return { ok, needed, message: ok ? null : 'service words', source };
}

function house(
  gates: Partial<Record<GateName, ModelGate>> = {},
  needed = { heating_days: 6, outside_span_k: 1.4 },
): HouseInsight {
  return {
    credible: gates.heat_loss?.ok ?? true,
    gates: {
      heat_loss: gate(true),
      dynamics: gate(true),
      sun: gate(true),
      ...gates,
    },
    ua: { w_per_k: 240, signature_w_per_k: 300 },
    credibility: { credible: true, needed },
  } as unknown as HouseInsight;
}

const NEED_CODES: GateNeed[] = [
  'no_signature',
  'more_heating_days',
  'more_outside_spread',
  'ua_interval_wide',
  'ua_disagrees',
  'ua_unstable',
  'no_dynamics_skill',
  'more_sunny_days',
  'no_sun_skill',
  'sun_response_off',
  'legacy_model',
];

describe('gateRows', () => {
  it('lists the three gates in a fixed order', () => {
    const rows = gateRows(house({ sun: gate(false, ['more_sunny_days']) }).gates);
    expect(rows.map((row) => [row.name, row.ok])).toEqual([
      ['heat_loss', true],
      ['dynamics', true],
      ['sun', false],
    ]);
    expect(gatesPassing(house({ sun: gate(false, ['more_sunny_days']) }).gates)).toBe(2);
  });

  it('is empty for a service without gates and flags a legacy model', () => {
    expect(gateRows(undefined)).toEqual([]);
    expect(gatesPassing(undefined)).toBe(0);
    const rows = gateRows(house({ sun: gate(false, ['legacy_model'], 'legacy') }).gates);
    expect(rows[2]).toMatchObject({ legacy: true, source: 'legacy' });
    expect(rows[0]?.legacy).toBe(false);
  });
});

describe('gate need texts', () => {
  it('translates every need code in both languages without leaking the code', () => {
    for (const code of NEED_CODES) {
      for (const tr of [en, nl]) {
        const text = gateNeedText(code, tr, fmt, house());
        expect(text.length, code).toBeGreaterThan(10);
        expect(text, code).not.toContain('houseGateNeed');
        expect(text, code).not.toContain(code);
      }
    }
  });

  it('names the amounts of the two weather codes when the model reports them', () => {
    expect(gateNeedText('more_heating_days', en, fmt, house())).toContain('6 more heating days');
    expect(gateNeedText('more_outside_spread', en, fmt, house())).toContain('1.4 K more spread');
    expect(gateNeedText('more_heating_days', nl, fmt, house())).toContain('6 stookdagen');
    const one = house({}, { heating_days: 1, outside_span_k: 0 });
    expect(gateNeedText('more_heating_days', en, fmt, one)).toContain('1 more heating day is');
    const none = house({}, { heating_days: 0, outside_span_k: 0 });
    expect(gateNeedText('more_heating_days', en, fmt, none)).toBe(
      'More heating days are needed: days that were cold enough for the heat pump to run.',
    );
  });

  it('says the legacy model is checked by the next run', () => {
    expect(gateNeedText('legacy_model', en, fmt)).toBe(
      'This model was made by an older version; the next run checks it.',
    );
    expect(gateNeedText('legacy_model', nl, fmt)).toContain('oudere versie');
  });

  it('never mentions a skill figure over a day as a reason', () => {
    for (const code of NEED_CODES)
      expect(gateNeedText(code, en, fmt, house())).not.toMatch(/24\s*h|24 hour/i);
  });
});

describe('gateReasons', () => {
  it('is empty for a gate that passes', () => {
    expect(gateReasons(gate(true), en, fmt)).toEqual([]);
    expect(gateReasons(undefined, en, fmt)).toEqual([]);
  });

  it('gives one sentence per code, in the order of the service', () => {
    const reasons = gateReasons(
      gate(false, ['ua_disagrees', 'more_heating_days']),
      en,
      fmt,
      house(),
    );
    expect(reasons).toHaveLength(2);
    expect(reasons[0]).toContain('disagree');
    expect(reasons[1]).toContain('6 more heating days');
  });

  it('falls back to the service message and then to a plain sentence', () => {
    expect(gateReasons(gate(false), en, fmt)).toEqual(['service words']);
    expect(gateReasons({ ...gate(false), message: null }, en, fmt)).toEqual([
      'There is not enough evidence yet.',
    ]);
  });
});

describe('checkRows', () => {
  it('reads value and limit of every check and skips what is not a check', () => {
    expect(
      checkRows({
        checks: {
          ua_stability: { ok: true, value: 0.05, limit: 0.15, folds: 2 },
          excitation: { ok: false },
          odd: 3,
          other: { value: 1 },
        },
      }),
    ).toEqual([
      { id: 'ua_stability', ok: true, value: 0.05, limit: 0.15 },
      { id: 'excitation', ok: false, value: null, limit: null },
    ]);
    expect(checkRows(undefined)).toEqual([]);
  });
});

describe('excitationProgress', () => {
  const excitation = {
    excited: false,
    heating_days: 14,
    outside_range_k: 8.6,
    rules: { heating_days: 20, outside_range_k: 10 },
  } as never;

  it('counts the way to the rules and drops what is done', () => {
    expect(excitationProgress(excitation)).toEqual([
      { kind: 'heating_days', have: 14, need: 20 },
      { kind: 'outside_range_k', have: 8.6, need: 10 },
    ]);
    expect(
      excitationProgress({ ...(excitation as object), heating_days: 25 } as never).map(
        (item) => item.kind,
      ),
    ).toEqual(['outside_range_k']);
  });

  it('is empty when excited or unknown', () => {
    expect(excitationProgress({ ...(excitation as object), excited: true } as never)).toEqual([]);
    expect(excitationProgress(null)).toEqual([]);
  });

  it('gives the share done, clamped', () => {
    expect(progressShare({ kind: 'heating_days', have: 14, need: 20 })).toBeCloseTo(0.7);
    expect(progressShare({ kind: 'heating_days', have: 30, need: 20 })).toBe(1);
  });
});

describe('revalidation', () => {
  const base = {
    model: 'm',
    at: '2026-11-27T10:00:00Z',
    source: 'revalidated',
    credible: true,
    reasons: [],
    skill: 0.2,
    room_rmse_k: 0.14,
    persistence_room_rmse_k: 0.2,
  } as unknown as Revalidation;

  it('says still good for a credible check', () => {
    expect(revalidationSentence(base, en, '27 Nov')).toBe(
      'Last checked against new data on 27 Nov: still good.',
    );
  });

  it('says why a failed check is no longer trusted, in our own words for a missing skill', () => {
    const bad = { ...base, credible: false, skill: -0.05 };
    expect(revalidationSentence(bad, en, '27 Nov')).toBe(
      'Last checked against new data on 27 Nov: no longer trusted because it no longer predicts the room better than "the room stays as it is".',
    );
    expect(revalidationSentence(bad, nl, '27 nov')).toContain('niet meer vertrouwd omdat');
  });

  it('falls back to the service reasons, then to a plain sentence', () => {
    const odd = { ...base, credible: false, skill: 0.1, reasons: ['too few days'] };
    expect(revalidationSentence(odd, en, 'x')).toContain('because too few days');
    expect(revalidationSentence({ ...odd, reasons: [] }, en, 'x')).toBe(
      'Last checked against new data on x: no longer trusted.',
    );
  });

  it('names the uses that are not trusted yet when the re-validation has gates', () => {
    const gates = (dynamics: boolean) => ({
      heat_loss: { ok: true },
      dynamics: { ok: dynamics },
      sun: { ok: true },
    });
    const partly = { ...base, gates: gates(false) } as unknown as Revalidation;
    expect(revalidationSentence(partly, en, '27 Nov')).toBe(
      'Last checked against new data on 27 Nov: not yet trusted for room dynamics.',
    );
    expect(revalidationSentence(partly, nl, '27 nov')).toContain('nog niet vertrouwd voor gedrag');
    expect(failingGates(partly)).toEqual(['dynamics']);
    expect(revalidationPassing(partly)).toBe(2);
    const all = { ...base, gates: gates(true) } as unknown as Revalidation;
    expect(revalidationSentence(all, en, 'x')).toContain('still good');
    expect(failingGates(all)).toEqual([]);
    expect(revalidationPassing(base)).toBeNull();
  });

  it('compares the room error with "no change"', () => {
    expect(revalidationErrors(base, en, (v, d = 1) => v.toFixed(d))).toBe(
      'Room error over 24 h: 0.14 K; "the room stays as it is" would give 0.20 K.',
    );
    expect(
      revalidationErrors({ ...base, room_rmse_k: null }, en, (v, d = 1) => v.toFixed(d)),
    ).toBeNull();
  });
});

describe('pins', () => {
  const validation = (cost: Validation['constraint_cost']) =>
    ({
      held_out_room_rmse_k: 0.31,
      challenger_room_rmse_k: 0.31,
      unconstrained_room_rmse_k: 0.24,
      constraint_cost: cost,
    }) as Validation;

  it('names both errors when the limits cost accuracy', () => {
    const text = constraintSentence(
      validation({ excess_k: 0.07, limit_k: 0.05, worse: true }),
      en,
      (v, d = 1) => v.toFixed(d),
    );
    expect(text).toBe(
      'With your limits the model is 0.31 K off, without them 0.24 K: a limit may be wrong.',
    );
    expect(
      constraintSentence(
        validation({ excess_k: 0.07, limit_k: 0.05, worse: true }),
        nl,
        (v, d = 1) => v.toFixed(d),
      ),
    ).toContain('grens kan verkeerd staan');
  });

  it('is silent when the limits cost nothing or there are none', () => {
    const f = (v: number, d = 1) => v.toFixed(d);
    expect(
      constraintSentence(validation({ excess_k: 0, limit_k: 0.05, worse: false }), en, f),
    ).toBeNull();
    expect(constraintSentence(validation(null), en, f)).toBeNull();
    expect(constraintSentence(undefined, en, f)).toBeNull();
  });

  const bounds: AtBound[] = [
    { parameter: 'h_air_out', value: 300, side: 'pinned', limit: 300, kind: 'owner' },
    { parameter: 'h_water_air', value: 5.1, side: 'lower', limit: 5, kind: 'structural' },
  ];

  it('maps learned parameters to the rows of the settings and splits the kinds', () => {
    expect(boundRowOf('h_air_out')).toBe('ua');
    expect(boundRowOf('time_constant_h')).toBe('tau');
    expect(boundRowOf('c_mass')).toBeNull();
    expect(ownerBound(bounds, 'ua')?.side).toBe('pinned');
    expect(ownerBound(bounds, 'tau')).toBeNull();
    expect(ownerBound(undefined, 'ua')).toBeNull();
    expect(structuralBounds(bounds).map((b) => b.parameter)).toEqual(['h_water_air']);
  });
});
