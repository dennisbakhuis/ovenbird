import { describe, expect, it } from 'vitest';
import type { HouseSeries } from './shapes';
import { differences, lastDays } from './series';

const series: HouseSeries = {
  model: 'm',
  step_s: 900,
  from: '2026-11-13T00:00:00Z',
  to: '2026-11-27T00:00:00Z',
  points: [
    ['2026-11-13T00:00:00Z', 21, null],
    ['2026-11-22T00:00:00Z', 21, 21.1],
    ['2026-11-25T00:00:00Z', 21, 20.8],
    ['2026-11-26T00:00:00Z', null, 20.9],
    ['2026-11-27T00:00:00Z', 20.5, 20.9],
  ],
};

describe('lastDays', () => {
  it('cuts the last days before the end of the series', () => {
    expect(lastDays(series, 3)).toHaveLength(3);
    expect(lastDays(series, 7)).toHaveLength(4);
    expect(lastDays(series, 14)).toHaveLength(5);
  });
});

describe('differences', () => {
  it('takes the median and the largest where both values exist', () => {
    const found = differences(series.points);
    expect(found?.count).toBe(3);
    expect(found?.typicalK).toBeCloseTo(0.2, 5);
    expect(found?.largestK).toBeCloseTo(0.4, 5);
    expect(found?.largestAt).toBe('2026-11-27T00:00:00Z');
  });

  it('is null without a pair', () => {
    expect(differences([['2026-11-13T00:00:00Z', 21, null]])).toBeNull();
  });
});
