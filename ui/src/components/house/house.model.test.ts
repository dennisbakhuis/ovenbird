// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BalanceResult } from '$lib/house/balance';
import type { HouseBalance, HouseWhatIf } from '$lib/house/shapes';
import HouseSchematic from './HouseSchematic.svelte';
import WhatIfCard from './WhatIfCard.svelte';

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  navigate('#/house/what-if');
});

function balance(over: Partial<HouseBalance> = {}, flows: Partial<HouseBalance['flows']> = {}) {
  const data: HouseBalance = {
    at: '2026-11-27T12:00:00Z',
    source: 'model',
    credible: true,
    room_c: 21.2,
    outside_c: 5.7,
    sun_wm2: 150,
    flows: {
      heat_pump_w: 2400,
      loss_w: 2100,
      sun_w: 300,
      internal_w: 300,
      stove_active: false,
      storage_w: 900,
      ...flows,
    },
    ua_w_per_k: 240,
    notes: [],
    ...over,
  };
  return { kind: 'ready', data } satisfies BalanceResult;
}

function navigate(hash: string): void {
  history.replaceState(null, '', hash);
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

const svg = () => screen.getByTestId('house-schematic-svg');

describe('HouseSchematic', () => {
  it('draws the flows of the model and says them as the label of the picture', () => {
    render(HouseSchematic, { balance: balance() });
    expect(screen.getByTestId('house-balance-source').textContent?.trim()).toBe('Measured model');
    expect(svg().getAttribute('aria-label')).toBe(
      screen.getByTestId('house-balance-sentence').textContent,
    );
    expect(svg().getAttribute('data-storage')).toBe('storing');
    expect(screen.queryByTestId('house-balance-learning')).toBeNull();
  });

  it('says "still learning" for a model that is not credible yet', () => {
    render(HouseSchematic, { balance: balance({ credible: false }) });
    expect(screen.getByTestId('house-balance-learning')).toBeTruthy();
  });

  it('marks an estimate as one, not measured', () => {
    render(HouseSchematic, { balance: balance({ source: 'estimate', credible: false }) });
    expect(screen.getByTestId('house-balance-source').textContent?.trim()).toBe(
      'Estimate from your answers, not measured',
    );
  });

  it('makes the storage unknown while the wood stove burns', () => {
    render(HouseSchematic, {
      balance: balance({}, { stove_active: true, storage_w: null }),
    });
    expect(svg().getAttribute('data-storage')).toBe('unknown');
    expect(svg().textContent).toContain('stove');
    expect(screen.getByTestId('house-balance-sentence').textContent).toContain(
      'wood stove is burning',
    );
  });

  it('draws an unknown sun as unknown, never as zero', () => {
    render(HouseSchematic, {
      balance: balance({ sun_wm2: null }, { sun_w: null, storage_w: null }),
    });
    expect(svg().textContent).toContain('unknown');
    expect(svg().querySelectorAll('path.arrow-unknown').length).toBeGreaterThan(0);
    expect(screen.getByTestId('house-balance-sentence').textContent).toContain(
      "the sun's share is not known",
    );
  });

  it('shows the note of a defrost', () => {
    render(HouseSchematic, { balance: balance({ notes: ['defrost'] }, { heat_pump_w: -300 }) });
    expect(screen.getByTestId('house-balance-note-defrost')).toBeTruthy();
  });

  it('asks for the facts when there is nothing to draw', async () => {
    const onfacts = vi.fn();
    render(HouseSchematic, { balance: { kind: 'no_model' }, onfacts });
    expect(screen.getByTestId('house-schematic-hint').textContent).toContain('Fill in a few facts');
    await fireEvent.click(screen.getByTestId('house-schematic-facts'));
    expect(onfacts).toHaveBeenCalled();
    expect(screen.queryByTestId('house-schematic-svg')).toBeNull();
  });
});

function whatif(over: Partial<HouseWhatIf> = {}): HouseWhatIf {
  return {
    source: 'model',
    model: 'house-1',
    credible: true,
    inputs: { outside_c: 0, comfort_c: 21, sun_wm2: 0, stove_w: 0 },
    heat_demand_w: 4730,
    free_heat_w: 320,
    loss_w: 5050,
    loop_mean_c: 32.5,
    supply_c: 35,
    curve_c: 34,
    max_supply_c: 40,
    limited_by: [],
    balance_outside_c: 19.7,
    drift: { hours: 8, step_s: 900, room_c: Array.from({ length: 33 }, (_, i) => 21 - i * 0.08) },
    time_constant_h: 52.6,
    ...over,
  };
}

function stubFetch(answer: () => HouseWhatIf) {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      calls.push(String(path));
      return { ok: true, status: 200, json: async () => answer() };
    }),
  );
  return calls;
}

describe('WhatIfCard', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    navigate('#/house/what-if');
  });

  it('fetches once at first and 300 ms after the last change, keeping the last answer', async () => {
    const calls = stubFetch(() => whatif());
    render(WhatIfCard, {});
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(1);
    expect(screen.getByTestId('whatif-demand').textContent).toContain('4.7');

    const dec = screen.getByTestId('whatif-outside-dec');
    await fireEvent.click(dec);
    await vi.advanceTimersByTimeAsync(200);
    await fireEvent.click(dec);
    await vi.advanceTimersByTimeAsync(299);
    expect(calls).toHaveLength(1);
    expect(screen.getByTestId('whatif-demand')).toBeTruthy();
    await vi.advanceTimersByTimeAsync(1);
    expect(calls).toHaveLength(2);
    expect(calls[1]).toContain('outside_c=-2');
    expect(window.location.hash).toContain('outside=-2');
  });

  it('says what the curve gives against what the model needs', async () => {
    stubFetch(() => whatif());
    render(WhatIfCard, {});
    await vi.advanceTimersByTimeAsync(0);
    const text = screen.getByTestId('whatif-water').textContent ?? '';
    expect(text).toContain('Your heating curve gives 34 °C');
    expect(text).toContain('the model needs 35 °C');
    expect(screen.getByTestId('whatif-drift').getAttribute('aria-label')).toContain('8 hours');
  });

  it('says when the maximum supply limits the answer', async () => {
    stubFetch(() => whatif({ limited_by: ['max_supply'], supply_c: 40 }));
    render(WhatIfCard, {});
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByTestId('whatif-capped').textContent).toContain('maximum supply of 40 °C');
  });

  it('says that no heating is needed', async () => {
    stubFetch(() => whatif({ limited_by: ['no_heat_needed'], heat_demand_w: 0 }));
    render(WhatIfCard, {});
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByTestId('whatif-none').textContent).toContain('No heating is needed');
    expect(screen.queryByTestId('whatif-demand')).toBeNull();
  });

  it('marks an estimate and a model that is still learning', async () => {
    stubFetch(() => whatif({ source: 'estimate', model: null, credible: false }));
    render(WhatIfCard, {});
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByTestId('whatif-source').textContent?.trim()).toBe(
      'Estimate from your answers, not measured.',
    );
  });

  it('reads the inputs from the URL query', async () => {
    navigate('#/house/what-if?outside=-5&stove=5000');
    const calls = stubFetch(() => whatif());
    render(WhatIfCard, {});
    await vi.advanceTimersByTimeAsync(0);
    expect(calls[0]).toContain('outside_c=-5');
    expect(calls[0]).toContain('stove_w=5000');
  });
});
