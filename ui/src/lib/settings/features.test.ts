import { describe, expect, it } from 'vitest';
import schemaJson from '$mock/fixtures/schema.json';
import { isClockTime } from '$lib/core/fieldFormat';
import type { ConfigSchema } from '$lib/core/types';
import { changedFeatureFields, FEATURES, featureFields, hasFeatureTags } from './features';

const schema = schemaJson as unknown as ConfigSchema;
const spec = (id: string) => FEATURES.find((f) => f.id === id)!;

describe('feature specs', () => {
  it('lists the thirteen features in the owner’s order, each with a switch in the schema', () => {
    expect(FEATURES.map((f) => f.id)).toEqual([
      'weather_compensation',
      'room_feedback',
      'slow_start',
      'minimum_run',
      'pump_duty',
      'quiet',
      'stove',
      'dayshift',
      'summer',
      'away',
      'boost',
      'starts_alarm',
      'house_basics',
    ]);
    for (const f of FEATURES) expect(schema.fields[f.switch]?.feature, f.id).toBe(f.id);
  });

  it('lists a feature’s settings by tier and leaves the switch and acknowledgement out', () => {
    const day = featureFields(schema, spec('dayshift'));
    expect(day.basic).toContain('control_dayshift_day_start');
    expect(day.advanced).toContain('control_dayshift_recovery_s');
    const all = [...day.basic, ...day.advanced, ...day.expert];
    expect(all).not.toContain('control_dayshift_use');
    expect(all).not.toContain('control_dayshift_experimental_ok');
  });

  it('gives only the day shift an acknowledgement, a basic setting of its own feature', () => {
    expect(FEATURES.filter((f) => f.ack).map((f) => f.id)).toEqual(['dayshift']);
    const ack = schema.fields['control_dayshift_experimental_ok'];
    expect(ack?.feature).toBe('dayshift');
    expect(ack?.tier).toBe('basic');
    expect(ack?.type).toBe('boolean');
  });

  it('shows the expert fields read-only and the editor-linked ones without settings', () => {
    const slow = featureFields(schema, spec('slow_start'));
    expect(slow.basic).toEqual([]);
    expect(slow.advanced).toEqual([]);
    expect([...slow.expert].sort()).toEqual([
      'control_ramp_below_outlet_k',
      'control_ramp_dwell_s',
    ]);
  });

  it('keeps the quiet windows with their own editor', () => {
    const quiet = featureFields(schema, spec('quiet'));
    expect([...quiet.basic, ...quiet.advanced]).not.toContain('control_quiet_windows');
    expect(quiet.basic).toContain('control_quiet_start_enabled');
  });

  it('counts draft changes in feature fields', () => {
    expect(hasFeatureTags(schema)).toBe(true);
    expect(
      changedFeatureFields(schema, { control_summer_enabled: true, control_comfort_c: 21 }),
    ).toBe(1);
    expect(changedFeatureFields(null, { a: 1 })).toBe(0);
  });
});

describe('isClockTime', () => {
  it('accepts HH:MM only', () => {
    expect(isClockTime('07:30')).toBe(true);
    expect(isClockTime('24:00')).toBe(false);
    expect(isClockTime('7:30')).toBe(false);
    expect(isClockTime(null)).toBe(false);
  });
});
