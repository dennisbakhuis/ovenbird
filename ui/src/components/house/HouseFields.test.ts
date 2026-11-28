// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import config from '$mock/fixtures/config.json';
import schema from '$mock/fixtures/schema.json';
import { draft } from '$lib/core/draft.svelte';
import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
import HouseFields from './HouseFields.svelte';

const doc = config as unknown as ConfigDoc;
const sch = schema as unknown as ConfigSchema;

beforeEach(() => {
  draft.changes = {};
});
afterEach(cleanup);

describe('HouseFields', () => {
  it('shows the basic facts and keeps the advanced ones behind More', () => {
    render(HouseFields, { schema: sch, config: doc });
    expect(screen.getByTestId('field-house_build_period')).toBeTruthy();
    expect(screen.getByTestId('field-house_occupants')).toBeTruthy();
    expect(screen.queryByTestId('field-house_volume_m3')).toBeNull();
    expect(screen.getByTestId('advanced-house')).toBeTruthy();
  });

  it('shows every fact when flat and puts an edit into the shared draft', async () => {
    render(HouseFields, { schema: sch, config: doc, flat: true });
    expect(screen.getByTestId('field-house_volume_m3')).toBeTruthy();
    expect(screen.getByTestId('field-house_floor_area_m2')).toBeTruthy();
    const volume = screen.getByLabelText('Heated volume') as HTMLInputElement;
    await fireEvent.input(volume, { target: { value: '400' } });
    expect(draft.changes['house_volume_m3']).toBe(400);
    expect(draft.count).toBe(1);
  });

  it('picks an enum and puts it into the shared draft, and unsets it again', async () => {
    render(HouseFields, { schema: sch, config: doc });
    const select = screen.getByLabelText('Build period') as HTMLSelectElement;
    await fireEvent.change(select, { target: { value: '1975_1991' } });
    expect(draft.changes['house_build_period']).toBe('1975_1991');
    await fireEvent.change(select, { target: { value: '' } });
    expect(draft.has('house_build_period')).toBe(false);
  });
});
