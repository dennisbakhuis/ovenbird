import { describe, expect, it } from 'vitest';
import type { ConfigVersion } from '$lib/core/types';
import {
  addDay,
  anyFactSet,
  changedSinceRun,
  cleanDays,
  dayLabel,
  isPinned,
  latestDay,
  learnedOf,
  localDay,
  toggleDay,
} from './settings';
import type { ConfigDoc } from '$lib/core/types';
import type { HouseInsight } from './house';

const NOW = new Date(2026, 10, 27, 12, 0).getTime();

describe('cleanDays', () => {
  it('sorts, dedupes and drops what is not a date', () => {
    expect(cleanDays(['2026-02-01', 'x', '2026-01-01', '2026-02-01', 5])).toEqual([
      '2026-01-01',
      '2026-02-01',
    ]);
    expect(cleanDays(null)).toEqual([]);
  });
});

describe('addDay', () => {
  it('adds a day sorted and leaves a repeat alone', () => {
    const first = addDay(['2026-11-20'], '2026-11-01', NOW);
    expect(first).toEqual({ days: ['2026-11-01', '2026-11-20'], refusal: null });
    expect(addDay(first.days, '2026-11-01', NOW).days).toBe(first.days);
  });

  it('refuses a bad date, a day more than a day ahead and a full list', () => {
    expect(addDay([], '2026-13-45', NOW).refusal).toBe('invalid');
    expect(addDay([], 'tomorrow', NOW).refusal).toBe('invalid');
    expect(addDay([], localDay(NOW + 2 * 86_400_000), NOW).refusal).toBe('future');
    expect(addDay([], latestDay(NOW), NOW).refusal).toBeNull();
    expect(addDay(['2026-11-01'], '2026-11-02', NOW, 1).refusal).toBe('full');
  });
});

describe('toggleDay', () => {
  it('leaves a day out and takes it back in', () => {
    const out = toggleDay(['2026-11-01'], '2026-10-01');
    expect(out).toEqual(['2026-10-01', '2026-11-01']);
    expect(toggleDay(out, '2026-10-01')).toEqual(['2026-11-01']);
  });

  it('does not grow past the limit', () => {
    expect(toggleDay(['2026-11-01'], '2026-11-02', 1)).toEqual(['2026-11-01']);
  });
});

describe('isPinned', () => {
  it('needs both sides equal', () => {
    expect(isPinned(200, 200)).toBe(true);
    expect(isPinned(200, 210)).toBe(false);
    expect(isPinned(200, null)).toBe(false);
  });
});

describe('anyFactSet', () => {
  const doc = (value: unknown) =>
    ({ fields: { house_occupants: { value } } }) as unknown as ConfigDoc;
  it('is true once one fact has a value', () => {
    expect(anyFactSet(doc(3))).toBe(true);
    expect(anyFactSet(doc(0))).toBe(true);
    expect(anyFactSet(doc(null))).toBe(false);
    expect(anyFactSet(null)).toBe(false);
  });
});

describe('learnedOf', () => {
  const house = {
    ua: { w_per_k: 240, interval_90: [230, 250] },
    time_constant_h: { value: 90, interval_90: null },
    solar_aperture_m2: null,
    internal_gains_w: { value: 300, interval_90: [250, 350] },
  } as unknown as HouseInsight;
  it('reads each quantity with its range', () => {
    expect(learnedOf(house, 'ua')).toEqual({ value: 240, interval: [230, 250] });
    expect(learnedOf(house, 'tau')).toEqual({ value: 90, interval: null });
    expect(learnedOf(house, 'aperture')).toBeNull();
    expect(learnedOf(null, 'gain')).toBeNull();
  });
});

describe('changedSinceRun', () => {
  const version = (at: string, field: string): ConfigVersion =>
    ({
      version: 1,
      created_at: at,
      applied_at: at,
      actor: 'a',
      origin: 'ui',
      comment: null,
      changed: [{ field, from: null, to: 1 }],
    }) as ConfigVersion;

  it('counts a fit setting changed after the run', () => {
    const run = '2026-11-20T00:00:00Z';
    expect(changedSinceRun([version('2026-11-21T00:00:00Z', 'house_ua_min_w_per_k')], run)).toBe(
      true,
    );
    expect(changedSinceRun([version('2026-11-19T00:00:00Z', 'house_ua_min_w_per_k')], run)).toBe(
      false,
    );
    expect(changedSinceRun([version('2026-11-21T00:00:00Z', 'control_comfort_c')], run)).toBe(
      false,
    );
    expect(changedSinceRun([version('2026-11-21T00:00:00Z', 'house_learn_interval_h')], run)).toBe(
      false,
    );
    expect(changedSinceRun([], null)).toBe(false);
  });
});

describe('dayLabel', () => {
  it('writes a plain date in the language', () => {
    expect(dayLabel('2026-01-05', 'en')).toContain('2026');
    expect(dayLabel('oops', 'en')).toBe('oops');
  });
});
