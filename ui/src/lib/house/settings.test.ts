import { describe, expect, it } from 'vitest';
import type { ConfigDoc } from '$lib/core/types';
import { FACT_FIELDS, anyFactSet } from './settings';

const doc = (fields: Record<string, unknown>) =>
  ({
    fields: Object.fromEntries(Object.entries(fields).map(([id, value]) => [id, { value }])),
  }) as unknown as ConfigDoc;

describe('anyFactSet', () => {
  it('is false without a config or with every fact unset', () => {
    expect(anyFactSet(null)).toBe(false);
    expect(anyFactSet(doc({ house_occupants: null, house_floor_area_m2: undefined }))).toBe(false);
  });

  it('is true as soon as one fact is set', () => {
    expect(anyFactSet(doc({ house_occupants: 3 }))).toBe(true);
    expect(anyFactSet(doc({ house_build_period: '1975_1991' }))).toBe(true);
  });

  it('covers the six facts the owner answers', () => {
    expect([...FACT_FIELDS].sort()).toEqual([
      'house_build_period',
      'house_floor_area_m2',
      'house_occupants',
      'house_volume_m3',
      'house_window_area_m2',
      'house_window_orientation',
    ]);
  });
});
