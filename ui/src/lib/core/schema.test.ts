import { describe, expect, it } from 'vitest';
import schema from '$mock/fixtures/schema.json';
import {
  changesIn,
  displayUnit,
  fieldsOf,
  fromDisplay,
  sectionOf,
  SECTIONS,
  toDisplay,
} from './schema';
import type { ConfigSchema, FieldDef } from './types';

const sch = schema as unknown as ConfigSchema;

describe('settings sections', () => {
  it('finds sections by id and nothing for the overview', () => {
    expect(sectionOf('room')?.groups).toContain('feedback');
    expect(sectionOf(undefined)).toBeUndefined();
    expect(sectionOf('nope')).toBeUndefined();
    expect(SECTIONS.map((s) => s.id)).toContain('versions');
  });

  it('counts draft changes per section', () => {
    const changes = { control_comfort_c: 22, control_feedback_kp: 1.5, control_curve: [] };
    expect(changesIn(sch, changes, sectionOf('room')?.groups ?? [])).toBe(2);
    expect(changesIn(sch, changes, sectionOf('curve')?.groups ?? [])).toBe(1);
    expect(changesIn(sch, changes, [])).toBe(0);
    expect(changesIn(null, changes, ['room'])).toBe(0);
  });

  it('lists fields of groups by tier in schema order', () => {
    expect(fieldsOf(sch, ['curve'], ['basic'])).toEqual([
      'control_outside_signal',
      'control_curve',
      'control_weather_compensation',
      'control_fixed_water_c',
    ]);
    expect(fieldsOf(sch, ['curve'], ['basic', 'advanced'])).toEqual([
      'control_outside_signal',
      'control_outside_max_age_s',
      'control_outside_plausible_min_c',
      'control_outside_plausible_max_c',
      'control_outside_max_deviation_k',
      'control_curve',
      'control_weather_compensation',
      'control_fixed_water_c',
      'control_outside_filter_s',
    ]);
  });
});

describe('house settings in the schema', () => {
  it('keeps the house facts as the only group of the House section', () => {
    expect(sectionOf('house')?.groups).toEqual(['house']);
    const changes = { house_occupants: 3, house_volume_m3: 400 };
    expect(changesIn(sch, changes, sectionOf('house')?.groups ?? [])).toBe(2);
  });

  it('shows a share as a percentage', () => {
    const def = { unit: 'ratio', display: '%' } as unknown as FieldDef;
    expect(displayUnit(def)).toBe('%');
    expect(toDisplay(def, 0.55)).toBe(55);
    expect(fromDisplay(def, 33.3)).toBe(0.333);
  });
});
