// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import { STORAGE_PREFIX } from '$lib/core/brand';
import { draft } from '$lib/core/draft.svelte';
import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
import type { HouseInsight } from '$lib/house/house';
import type { HouseSeries } from '$lib/house/shapes';
import HouseInputCard from './HouseInputCard.svelte';
import PredictionChart from './PredictionChart.svelte';
import GateDetails from './GateDetails.svelte';
import GateReasons from './GateReasons.svelte';
import SunGateLine from './SunGateLine.svelte';
import TrustNote from './TrustNote.svelte';

const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

beforeEach(() => {
  draft.changes = {};
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

function house(over: Record<string, unknown> = {}): HouseInsight {
  return {
    credible: false,
    gates: undefined,
    ua: { w_per_k: 300, interval_90: [300, 300], signature_w_per_k: 236 },
    time_constant_h: { value: 52, interval_90: [48, 56] },
    solar_aperture_m2: { value: 6, interval_90: [5, 7] },
    internal_gains_w: { value: 318, interval_90: [262, 381] },
    credibility: {
      credible: false,
      needed: { heating_days: 6, outside_span_k: 1.4 },
    },
    excitation: {
      excited: false,
      heating_days: 14,
      outside_range_k: 8.6,
      rules: { heating_days: 20, outside_range_k: 10 },
    },
    at_bound: [],
    validation: null,
    ...over,
  } as unknown as HouseInsight;
}

function gate(ok: boolean, needed: string[] = [], source = 'fitted') {
  return { ok, needed, message: ok ? null : 'service words', source };
}

function gated(gates: Record<string, ReturnType<typeof gate>>, over: Record<string, unknown> = {}) {
  return house({
    gates: { heat_loss: gate(true), dynamics: gate(true), sun: gate(true), ...gates },
    ...over,
  });
}

describe('TrustNote', () => {
  it('shows three rows, each with what it guards', () => {
    render(TrustNote, { house: gated({}) });
    for (const name of ['heat_loss', 'dynamics', 'sun']) {
      expect(screen.getByTestId(`house-gate-${name}`).getAttribute('data-ok')).toBe('true');
      expect(screen.getByTestId(`house-gate-pill-${name}`).textContent?.trim()).toBe('Trusted');
    }
    expect(screen.getByTestId('house-trust').textContent).toContain(
      'What the model can be trusted for',
    );
    expect(screen.getByTestId('house-gate-heat_loss').textContent).toContain(
      'insulation score, the curve suggestion and What if',
    );
    expect(screen.getByTestId('house-gate-dynamics').textContent).toContain('cool-down prediction');
    expect(screen.getByTestId('house-gate-sun').textContent).toContain(
      'later version of the model plan',
    );
    expect(screen.queryByTestId('house-gate-reasons-heat_loss')).toBeNull();
  });

  it('gives the plain reasons of every gate that does not pass, and nothing for the others', () => {
    render(TrustNote, {
      house: gated({
        heat_loss: gate(false, ['more_heating_days', 'more_outside_spread']),
        dynamics: gate(false, ['no_dynamics_skill']),
      }),
    });
    expect(screen.getByTestId('house-gate-pill-heat_loss').textContent?.trim()).toBe('Not yet');
    expect(screen.getByTestId('house-gate-need-more_heating_days').textContent).toContain(
      '6 more heating days',
    );
    expect(screen.getByTestId('house-gate-need-more_outside_spread').textContent).toContain(
      '1.4 K more spread',
    );
    expect(screen.getByTestId('house-gate-need-no_dynamics_skill').textContent).toContain(
      '"the room stays as it is"',
    );
    expect(screen.queryByTestId('house-gate-reasons-sun')).toBeNull();
    expect(screen.queryByTestId('house-trust-progress')).toBeNull();
  });

  it('says a legacy model was made by an older version', () => {
    render(TrustNote, {
      house: gated({ sun: gate(false, ['legacy_model'], 'legacy') }),
    });
    expect(screen.getByTestId('house-gate-sun').getAttribute('data-source')).toBe('legacy');
    expect(screen.getByTestId('house-gate-need-legacy_model').textContent).toBe(
      'This model was made by an older version; the next run checks it.',
    );
  });

  it('lists how every check came out and keeps the 24 h skill as information', async () => {
    render(GateDetails, {
      house: gated(
        { dynamics: gate(false, ['no_dynamics_skill']) },
        {
          credibility: {
            credible: true,
            gates: {
              heat_loss: {
                ...gate(true),
                checks: { ua_stability: { ok: true, value: 0.05, limit: 0.15 } },
              },
              dynamics: {
                ...gate(false, ['no_dynamics_skill']),
                checks: { skill_6h: { ok: false, value: -0.04, limit: 0 } },
                diagnostics: { skill_24h: -0.2, note: 'x' },
              },
              sun: { ...gate(true), checks: {} },
            },
            needed: { heating_days: 0, outside_span_k: 0 },
          },
        },
      ),
    });
    const details = screen.getByTestId('house-gate-details') as HTMLDetailsElement;
    details.open = true;
    await fireEvent(details, new Event('toggle'));
    const row = screen.getByTestId('house-check-ua_stability');
    expect(row.textContent).toContain('Heat loss steady between training periods');
    expect(row.textContent).toContain('passes');
    expect(row.textContent).toContain('0.05, limit 0.15');
    expect(screen.getByTestId('house-check-skill_6h').getAttribute('data-ok')).toBe('false');
    expect(screen.getByTestId('house-skill24').textContent).toContain('hard to out-predict');
  });

  it('is silent for a service without gates', () => {
    render(TrustNote, { house: house({ gates: undefined }) });
    expect(screen.queryByTestId('house-trust')).toBeNull();
  });
});

describe('GateReasons', () => {
  it('adds the progress display to the heat-loss gate while heating weather is missing', () => {
    render(GateReasons, {
      house: gated({ heat_loss: gate(false, ['more_heating_days']) }),
      gate: 'heat_loss',
      progress: true,
    });
    const bar = screen.getByTestId('house-trust-bar-heating_days');
    expect(bar.getAttribute('role')).toBe('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBe('14');
    expect(bar.getAttribute('aria-valuemax')).toBe('20');
    expect(screen.getByTestId('house-trust-progress').textContent).toContain(
      'Spread of outside temperature: 8.6 of 10 K',
    );
  });

  it('draws no progress for another reason or for another gate', () => {
    render(GateReasons, {
      house: gated({ heat_loss: gate(false, ['ua_disagrees']) }),
      gate: 'heat_loss',
      progress: true,
    });
    expect(screen.queryByTestId('house-trust-progress')).toBeNull();
    expect(screen.getByTestId('house-gate-need-ua_disagrees')).toBeTruthy();
  });
});

describe('SunGateLine', () => {
  it('says trusted for a passing sun gate', () => {
    render(SunGateLine, { house: gated({}) });
    expect(screen.getByTestId('house-sun-line-text').textContent?.trim()).toBe(
      'Sun response: trusted',
    );
  });

  it('says not yet with the first reason', () => {
    render(SunGateLine, { house: gated({ sun: gate(false, ['more_sunny_days']) }) });
    const text = screen.getByTestId('house-sun-line-text').textContent ?? '';
    expect(text).toContain('Sun response: not yet. More sunny days are needed');
    expect(text).not.toMatch(/\.\)$/);
  });
});

describe('HouseInputCard', () => {
  it('opens the facts only before a model exists and counts the facts set when collapsed', () => {
    const withFacts = {
      ...doc,
      fields: {
        ...doc.fields,
        house_occupants: { ...doc.fields['house_occupants'], value: 3 },
      },
    } as unknown as ConfigDoc;
    const { unmount } = render(HouseInputCard, { subset: 'facts', schema: sch, config: doc });
    const open = () => (screen.getByTestId('house-facts-input-details') as HTMLDetailsElement).open;
    expect(open()).toBe(true);
    unmount();
    render(HouseInputCard, { subset: 'facts', schema: sch, config: doc, house: house() });
    expect(open()).toBe(false);
    cleanup();
    render(HouseInputCard, {
      subset: 'facts',
      schema: sch,
      config: withFacts,
      house: house(),
    });
    expect(open()).toBe(false);
    expect(screen.getByTestId('house-facts-input').textContent).toContain('1 set');
  });

  it('says what the limits cost and lists values at the edge of the model neutrally', () => {
    localStorage.setItem(`${STORAGE_PREFIX}details.house-structural`, '1');
    draft.changes['house_ua_min_w_per_k'] = 300;
    const pinned = {
      ...doc,
      fields: {
        ...doc.fields,
        house_ua_min_w_per_k: { ...doc.fields['house_ua_min_w_per_k'], value: 300 },
        house_ua_max_w_per_k: { ...doc.fields['house_ua_max_w_per_k'], value: 300 },
      },
    } as unknown as ConfigDoc;
    render(HouseInputCard, {
      subset: 'bounds',
      schema: sch,
      config: pinned,
      house: house({
        validation: {
          held_out_room_rmse_k: 0.31,
          challenger_room_rmse_k: 0.31,
          unconstrained_room_rmse_k: 0.24,
          constraint_cost: { excess_k: 0.07, limit_k: 0.05, worse: true },
        },
        at_bound: [
          { parameter: 'h_air_out', value: 300, side: 'pinned', limit: 300, kind: 'owner' },
          { parameter: 'h_water_air', value: 5.1, side: 'lower', limit: 5, kind: 'structural' },
        ],
      }),
    });
    expect(screen.getByTestId('house-constraint-worse').textContent).toContain(
      'With your limits the model is 0.31 K off, without them 0.24 K: a limit may be wrong.',
    );
    const list = screen.getByTestId('house-structural-list').textContent ?? '';
    expect(list).toContain('Heat transfer, loop straight to room');
    expect(list).not.toContain('Heat loss to outside');
    expect(screen.getByTestId('bound-at-limit-ua').textContent).toContain('At your limit');
    expect(screen.queryByTestId('bound-at-limit-tau')).toBeNull();
  });

  it('shows no warning and no list without costs or structural values', () => {
    render(HouseInputCard, { subset: 'bounds', schema: sch, config: doc, house: house() });
    expect(screen.queryByTestId('house-constraint-worse')).toBeNull();
    expect(screen.queryByTestId('house-structural')).toBeNull();
  });
});

const NOW = Date.parse('2026-11-27T12:00:00Z');

function series(over: Partial<HouseSeries> = {}): HouseSeries {
  const points: HouseSeries['points'] = [];
  for (let i = 0; i <= 14 * 96; i += 1) {
    const at = NOW - 14 * 86_400_000 + i * 900_000;
    points.push([new Date(at).toISOString(), 21, i < 96 ? null : 20.7]);
  }
  return {
    model: 'house-1',
    step_s: 900,
    from: points[96]?.[0] ?? '',
    to: new Date(NOW).toISOString(),
    points,
    events: [
      {
        kind: 'stove',
        from: '2026-11-24T10:00:00Z',
        to: '2026-11-24T15:00:00Z',
        tail_to: '2026-11-25T03:00:00Z',
      },
      {
        kind: 'excluded_day',
        from: '2026-11-20T00:00:00Z',
        to: '2026-11-21T00:00:00Z',
        tail_to: '2026-11-21T00:00:00Z',
      },
    ],
    out_of_sample_from: '2026-11-21T00:00:00Z',
    rmse_k: 0.4,
    bias_k: -0.3,
    compared_points: 300,
    ...over,
  };
}

function stubSeries(body: HouseSeries): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
    ),
  );
}

describe('PredictionChart', () => {
  it('says the typical error in plain words, shades events and keeps them out of the largest', async () => {
    stubSeries(series());
    render(PredictionChart);
    await screen.findByTestId('house-pred-summary');
    const summary = screen.getByTestId('house-pred-summary').textContent ?? '';
    expect(summary).toContain(
      'On unseen days the model is typically 0.4 °C off, and on average 0.3 °C too cold.',
    );
    expect(summary).toContain('largest difference');
    const spans = screen.getAllByTestId('chart-span');
    expect(spans.some((span) => span.getAttribute('data-pattern') === 'hatch')).toBe(true);
    expect(spans.some((span) => span.getAttribute('data-pattern') === 'dots')).toBe(true);
    const legend = screen.getByTestId('house-pred-events').textContent ?? '';
    expect(legend).toContain('Wood stove: hatched');
    expect(legend).toContain('Day left out: dotted');
  });

  it('draws no legend line and no shading without events', async () => {
    stubSeries(series({ events: [] }));
    render(PredictionChart);
    await screen.findByTestId('house-pred-summary');
    expect(screen.queryByTestId('house-pred-events')).toBeNull();
    expect(screen.queryAllByTestId('chart-span')).toHaveLength(0);
  });

  it('falls back to the median sentence for a series without the error figures', async () => {
    stubSeries(series({ events: [], rmse_k: null, bias_k: null, out_of_sample_from: null }));
    render(PredictionChart);
    await screen.findByTestId('house-pred-summary');
    expect(screen.getByTestId('house-pred-summary').textContent).toContain(
      'the prediction was typically',
    );
  });
});
