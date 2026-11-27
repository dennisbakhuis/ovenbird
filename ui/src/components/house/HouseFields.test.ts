// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import { draft } from '$lib/core/draft.svelte';
import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
import type { HouseInsight } from '$lib/house/house';
import ExcludedDaysEditor from './ExcludedDaysEditor.svelte';
import HouseFields from './HouseFields.svelte';

const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;
const house = {
  ua: { w_per_k: 240.4, interval_90: [229.8, 251.3] },
  time_constant_h: { value: 88, interval_90: [70, 110] },
  solar_aperture_m2: { value: 4.2, interval_90: [3, 5.5] },
  internal_gains_w: { value: 310, interval_90: [250, 370] },
} as unknown as HouseInsight;

beforeEach(() => {
  draft.changes = {};
});
afterEach(cleanup);

describe('HouseFields', () => {
  it('shows the basic facts and keeps the advanced ones behind More', () => {
    render(HouseFields, { schema: sch, config: doc, subset: 'facts' });
    expect(screen.getByTestId('field-house_build_period')).toBeTruthy();
    expect(screen.getByTestId('field-house_occupants')).toBeTruthy();
    expect(screen.queryByTestId('field-house_volume_m3')).toBeNull();
    expect(screen.getByTestId('advanced-house')).toBeTruthy();
  });

  it('shows every fact when flat, the share in percent', async () => {
    render(HouseFields, { schema: sch, config: doc, subset: 'facts', flat: true });
    expect(screen.getByTestId('field-house_volume_m3')).toBeTruthy();
    const share = screen.getByLabelText('Share of floor heating') as HTMLInputElement;
    await fireEvent.input(share, { target: { value: '60' } });
    expect(draft.changes['house_floor_heating_share']).toBe(0.6);
    expect(draft.count).toBe(1);
  });

  it('picks an enum and puts it into the shared draft, and unsets it again', async () => {
    render(HouseFields, { schema: sch, config: doc, subset: 'facts' });
    const select = screen.getByLabelText('Build period') as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: '1975_1991' } });
    expect(draft.changes['house_build_period']).toBe('1975_1991');
    await fireEvent.change(select, { target: { value: '' } });
    expect(draft.has('house_build_period')).toBe(false);
  });

  it('shows the learned value and range next to each bound and explains pinning', async () => {
    render(HouseFields, { schema: sch, config: doc, subset: 'bounds', house, flat: true });
    expect(screen.getByTestId('bounds-explain').textContent).toContain('pin the value');
    expect(screen.getByTestId('bound-learned-ua').textContent).toContain('240');
    expect(screen.getByTestId('bound-learned-ua').textContent).toContain('90 % range 230–251');
    expect(screen.getByTestId('bound-learned-gain').textContent).toContain('250–370');
    const min = screen.getByLabelText('Heat loss, at least');
    const max = screen.getByLabelText('Heat loss, at most');
    await fireEvent.input(min, { target: { value: '250' } });
    expect(screen.queryByTestId('bound-pinned-ua')).toBeNull();
    await fireEvent.input(max, { target: { value: '250' } });
    expect(draft.changes['house_ua_min_w_per_k']).toBe(250);
    expect(draft.changes['house_ua_max_w_per_k']).toBe(250);
    expect(screen.getByTestId('bound-pinned-ua')).toBeTruthy();
  });

  it('says there is nothing learned before a model exists', () => {
    render(HouseFields, { schema: sch, config: doc, subset: 'bounds', flat: true });
    expect(screen.getByTestId('bound-learned-ua').textContent).toContain('no learned value');
  });

  it('lists the learning fields with the left-out days editor', async () => {
    render(HouseFields, { schema: sch, config: doc, subset: 'learning', flat: true });
    expect(screen.getByTestId('field-house_learn_fit_days')).toBeTruthy();
    expect(screen.getByTestId('excluded-days-editor')).toBeTruthy();
    await fireEvent.input(screen.getByTestId('excluded-day-input'), {
      target: { value: '2026-11-01' },
    });
    await fireEvent.click(screen.getByTestId('excluded-day-add'));
    expect(draft.changes['house_learn_excluded_days']).toEqual(['2026-11-01']);
  });
});

describe('ExcludedDaysEditor', () => {
  it('adds days sorted and removes one with its chip', async () => {
    let days: string[] = ['2026-11-10'];
    const view = render(ExcludedDaysEditor, { days, onchange: (next: string[]) => (days = next) });
    await fireEvent.input(screen.getByTestId('excluded-day-input'), {
      target: { value: '2026-11-02' },
    });
    await fireEvent.click(screen.getByTestId('excluded-day-add'));
    expect(days).toEqual(['2026-11-02', '2026-11-10']);
    await view.rerender({ days, onchange: (next: string[]) => (days = next) });
    expect(screen.getByTestId('excluded-chip-2026-11-02')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: /Take .*2 Nov 2026 back in/ }));
    expect(days).toEqual(['2026-11-10']);
  });

  it('refuses a day beyond tomorrow and disables adding without a date', async () => {
    const changes: string[][] = [];
    render(ExcludedDaysEditor, { days: [], onchange: (next: string[]) => changes.push(next) });
    expect((screen.getByTestId('excluded-day-add') as HTMLButtonElement).disabled).toBe(true);
    await fireEvent.input(screen.getByTestId('excluded-day-input'), {
      target: { value: '2999-01-01' },
    });
    await fireEvent.click(screen.getByTestId('excluded-day-add'));
    expect(changes).toEqual([]);
    expect(screen.getByText('A day cannot lie in the future.')).toBeTruthy();
  });

  it('stops adding at the limit', () => {
    const days = Array.from(
      { length: 60 },
      (_, i) => `2026-01-${String((i % 28) + 1).padStart(2, '0')}`,
    );
    render(ExcludedDaysEditor, { days: [...new Set(days)], onchange: () => {}, max: 28 });
    expect((screen.getByTestId('excluded-day-add') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('The list is full: take a day back in first.')).toBeTruthy();
  });
});
