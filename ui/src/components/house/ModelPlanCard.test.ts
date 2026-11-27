// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import { cfg } from '$lib/core/cfg.svelte';
import { draft } from '$lib/core/draft.svelte';
import type { ConfigDoc, ConfigSchema, FieldDef } from '$lib/core/types';
import type { HouseControl, PlanEvaluation } from '$lib/house/shapes';
import ModelPlanCard from './ModelPlanCard.svelte';
import StatusLine from './StatusLine.svelte';

globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

const BASE = Date.parse('2026-11-20T00:00:00');
const STEP = 900_000;

const numeric = (min: number, max: number): FieldDef =>
  ({
    editable: true,
    env: 'X',
    exclusive_max: false,
    exclusive_min: false,
    group: 'model_plan',
    max,
    min,
    nullable: false,
    preset_default: false,
    soft_max: null,
    soft_min: null,
    step: 0.1,
    tier: 'advanced',
    type: 'number',
    unit: 'K',
    display: null,
  }) as unknown as FieldDef;

const sch = (() => {
  const base = schema as unknown as ConfigSchema;
  return {
    ...base,
    fields: {
      ...base.fields,
      control_model_use: {
        ...numeric(0, 0),
        type: 'enum',
        options: ['off', 'shadow', 'on'],
        tier: 'basic',
        unit: null,
        step: null,
      },
      control_model_max_setback_k: numeric(0, 1),
      control_model_max_preheat_k: numeric(0, 0.5),
      control_model_horizon_h: { ...numeric(1, 12), unit: 'h' },
      control_model_max_rmse_k: numeric(0.1, 2),
    },
  } as unknown as ConfigSchema;
})();

const doc = (() => {
  const base = config as unknown as ConfigDoc;
  const field = (value: unknown) => ({
    default: value,
    locked: false,
    source: 'default',
    stored: null,
    value,
  });
  return {
    ...base,
    fields: {
      ...base.fields,
      control_model_use: field('off'),
      control_model_max_setback_k: field(0.5),
      control_model_max_preheat_k: field(0.3),
      control_model_horizon_h: field(6),
      control_model_max_rmse_k: field(0.4),
    },
  } as unknown as ConfigDoc;
})();

function evaluation(over: Partial<PlanEvaluation> = {}): PlanEvaluation {
  return {
    at: new Date(BASE + 96 * 3 * STEP).toISOString(),
    status: 'issued',
    offset_k: -0.3,
    applied: false,
    reason: 'plan_setback',
    valid_until: new Date(BASE + 96 * 3 * STEP + 3_600_000).toISOString(),
    rise_k: 0.6,
    rise_at: new Date(BASE + 96 * 3 * STEP + 3 * 3_600_000).toISOString(),
    fall_k: 0.1,
    fall_at: new Date(BASE + 96 * 3 * STEP + 5 * 3_600_000).toISOString(),
    solar_k: 0.6,
    outside_k: -0.1,
    ...over,
  };
}

function control(over: Partial<HouseControl> = {}, applied: 0 | 1 = 0): HouseControl {
  const points: HouseControl['history']['points'] = [];
  for (let i = 0; i < 96 * 7; i += 1) {
    const hour = (i % 96) / 4;
    const offset = hour >= 9 && hour < 13 ? -0.3 : i % 96 === 5 ? null : 0;
    points.push([
      new Date(BASE + i * STEP).toISOString(),
      offset,
      offset === null ? null : applied,
    ]);
  }
  return {
    use: 'shadow',
    verdict: { ok: true, blocks: [] },
    model: 'house-20261119',
    model_rmse_k: 0.21,
    bounds: { max_setback_k: 0.5, max_preheat_k: 0.3, horizon_h: 6, max_rmse_k: 0.4 },
    now: evaluation(),
    history: {
      step_s: 900,
      from: new Date(BASE).toISOString(),
      to: new Date(BASE + 7 * 86_400_000).toISOString(),
      points,
    },
    ...over,
  };
}

const show = (value: HouseControl) =>
  render(ModelPlanCard, { control: value, schema: sch, config: doc });

beforeEach(() => {
  draft.changes = {};
  cfg.validation = null;
});
afterEach(cleanup);

describe('ModelPlanCard', () => {
  it('explains the off switch and offers the three positions', () => {
    show(control({ use: 'off', now: null }));
    expect(screen.getByTestId('house-control-pill').textContent).toContain('Off');
    expect(screen.getByTestId('house-control-meaning').textContent).toContain('ignores the model');
    expect(screen.getByTestId('house-control-shift').textContent).toContain('not running');
    expect(screen.getByTestId('house-control-use-on')).toBeTruthy();
    expect(screen.getByTestId('house-control-locked').textContent).toContain('locked');
  });

  it('shows a shadow shift as "would", with the expected effect and the bounds', () => {
    show(control());
    expect(screen.getByTestId('house-control-pill').textContent).toContain(
      'Shadow (computes only)',
    );
    expect(screen.getByTestId('house-control-shift').textContent).toMatch(
      /^Would lower the room target by 0\.3 K until \d/,
    );
    expect(screen.getByTestId('house-control-effect').textContent).toContain(
      'the sun is expected to warm the room by about 0.6 °C',
    );
    expect(screen.getByTestId('house-control-bounds').textContent).toBe(
      'At most 0.5 K down and 0.3 K up, looking 6 hours ahead.',
    );
    expect(screen.getByTestId('house-control-ready')).toBeTruthy();
  });

  it('says there is no shift inside the dead zone', () => {
    show(
      control({
        now: evaluation({ status: 'inside_dead_zone', offset_k: 0, rise_k: 0.2, fall_k: 0.1 }),
      }),
    );
    expect(screen.getByTestId('house-control-shift').textContent).toBe(
      'No shift now: the expected change stays within the dead zone.',
    );
  });

  it('lists the blocks, most important first, with the model error filled in', () => {
    show(
      control({
        verdict: { ok: false, blocks: ['stove_tail', 'model_error_high', 'model_not_credible'] },
        model_rmse_k: 0.62,
      }),
    );
    const items = screen.getAllByTestId(/^house-control-block-/).map((el) => el.textContent);
    expect(items).toEqual([
      'The model is not trusted yet.',
      'The model’s room error (0.62 K) is above the limit of 0.4 K.',
      'A wood stove was burning in the last 12 hours.',
    ]);
    expect(screen.queryByTestId('house-control-ready')).toBeNull();
  });

  it('shows an applied shift as "lowers" when on', () => {
    show(control({ use: 'on', now: evaluation({ applied: true }) }, 1));
    expect(screen.getByTestId('house-control-pill').textContent?.trim()).toBe('On');
    expect(screen.getByTestId('house-control-shift').textContent).toMatch(
      /^Lowers the room target by 0\.3 K until/,
    );
    expect(screen.getByTestId('house-control-summary').textContent).toContain(
      'the model lowered the room target on 7 days, by at most 0.3 K',
    );
  });

  it('summarises the chart in a sentence that is also its text alternative', () => {
    show(control());
    const summary = screen.getByTestId('house-control-summary').textContent ?? '';
    expect(summary).toBe(
      'In the last 7 days the model would have lowered the room target on 7 days, by at most 0.3 K.',
    );
    expect(
      document.querySelector('[data-testid="house-control-history"] [role="img"]'),
    ).toBeTruthy();
    expect(screen.getByRole('button', { name: /table/i })).toBeTruthy();
  });

  it('shows only the sentence, no chart, when nothing was ever computed', () => {
    const points = control().history.points.map(([at]) => [at, null, null] as [string, null, null]);
    show(control({ use: 'off', now: null, history: { ...control().history, points } }));
    expect(document.querySelector('[data-testid="house-control-history"] [role="img"]')).toBeNull();
    expect(screen.getByTestId('house-control-summary').textContent).toContain('did not evaluate');
  });

  it('puts a choice into the shared draft and does not apply it', async () => {
    show(control({ use: 'off', now: null }));
    await fireEvent.click(screen.getByTestId('house-control-use-shadow'));
    expect(draft.changes['control_model_use']).toBe('shadow');
    expect(screen.getByTestId('house-control-use-shadow').getAttribute('aria-pressed')).toBe(
      'true',
    );
    expect(screen.getByTestId('house-control-pill').textContent).toContain('Off');
  });

  it('shows the server refusal of on in words', async () => {
    cfg.validation = {
      valid: false,
      errors: [
        {
          field: 'control_model_use',
          code: 'model_use_on_locked',
          message: 'locked',
          params: {},
        },
      ],
      warnings: [],
      effective: {},
    } as unknown as typeof cfg.validation;
    show(control({ use: 'off', now: null }));
    expect(screen.getByTestId('house-control-error').textContent).toContain('locked for now');
  });

  it('keeps the four numeric settings in a collapsed block bound to the draft', async () => {
    show(control());
    const details = screen.getByTestId('house-control-advanced');
    expect(details.hasAttribute('open')).toBe(false);
    (details as HTMLDetailsElement).open = true;
    await fireEvent(details, new Event('toggle'));
    const input = screen.getByLabelText('Largest shift down') as HTMLInputElement;
    await fireEvent.input(input, { target: { value: '0.4' } });
    expect(draft.changes['control_model_max_setback_k']).toBe(0.4);
  });

  it('carries the honest note', () => {
    show(control());
    expect(screen.getByTestId('house-control-note').textContent).toContain(
      'the room sensor still decides',
    );
  });
});

describe('StatusLine controller use', () => {
  const house = {
    model: 'house-1',
    credibility: { credible: true },
    champion: null,
    learner: null,
  } as never;

  it('names the use and links to the card', async () => {
    let opened = 0;
    render(StatusLine, { house, use: 'shadow', onuse: () => (opened += 1) });
    expect(screen.getByTestId('house-status-use').textContent).toContain('Controller use: Shadow');
    await fireEvent.click(screen.getByTestId('house-status-use-link'));
    expect(opened).toBe(1);
  });

  it('says nothing about it without the endpoint', () => {
    render(StatusLine, { house });
    expect(screen.queryByTestId('house-status-use')).toBeNull();
  });
});
