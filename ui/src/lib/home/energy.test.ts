import { describe, expect, it } from 'vitest';
import type { Point } from '$lib/core/chart';
import { dayEnergy, integrateEnergy, startOfLocalDay } from './energy';

const H = 3_600_000;
const MIN = 60_000;

describe('integrateEnergy', () => {
  it('integrates a constant 1 kW over two hours', () => {
    const points: Point[] = [
      [0, 1000],
      [H, 1000],
      [2 * H, 1000],
    ];
    const result = integrateEnergy(points, 0, 2 * H, { maxGapMs: H });
    expect(result.kwh).toBeCloseTo(2, 6);
    expect(result.missingMs).toBe(0);
  });

  it('holds each sample until the next one (steps)', () => {
    const points: Point[] = [
      [0, 2000],
      [H, 0],
      [2 * H, 4000],
    ];
    const result = integrateEnergy(points, 0, 3 * H, { maxGapMs: 2 * H });
    expect(result.kwh).toBeCloseTo(2 + 0 + 4, 6);
  });

  it('does not bridge gaps longer than the limit', () => {
    const points: Point[] = [
      [0, 1000],
      [3 * H, 1000],
    ];
    const result = integrateEnergy(points, 0, 4 * H, { maxGapMs: 30 * MIN });
    expect(result.kwh).toBeCloseTo(0.5 + 0.5, 6);
    expect(result.missingMs).toBe(3 * H);
  });

  it('counts only the part inside a partial window', () => {
    const points: Point[] = [
      [-H, 1000],
      [H, 1000],
    ];
    const result = integrateEnergy(points, 0, 90 * MIN, { maxGapMs: 3 * H });
    expect(result.kwh).toBeCloseTo(1.5, 6);
    expect(result.coveredMs).toBe(90 * MIN);
  });

  it('holds the last sample only up to the end of the window and the gap limit', () => {
    const points: Point[] = [[0, 1000]];
    expect(integrateEnergy(points, 0, 10 * MIN, { maxGapMs: H }).kwh).toBeCloseTo(1 / 6, 6);
    expect(integrateEnergy(points, 0, 5 * H, { maxGapMs: H }).kwh).toBeCloseTo(1, 6);
  });

  it('ignores non-finite samples, sorts input and clamps negative power', () => {
    const points: Point[] = [
      [H, -500],
      [0, 1000],
      [2 * H, Number.NaN],
    ];
    expect(integrateEnergy(points, 0, 2 * H, { maxGapMs: 2 * H }).kwh).toBeCloseTo(1, 6);
  });

  it('is zero without samples and reports the window as missing', () => {
    const result = integrateEnergy([], 0, H);
    expect(result.kwh).toBe(0);
    expect(result.missingMs).toBe(H);
  });
});

describe('dayEnergy', () => {
  it('derives COP from the energy totals and coverage from the shorter series', () => {
    const electric: Point[] = [[0, 1000]];
    const heat: Point[] = [[0, 4000]];
    const result = dayEnergy(electric, heat, 0, 15 * MIN, { maxGapMs: H });
    expect(result.electricKwh).toBeCloseTo(0.25, 6);
    expect(result.heatKwh).toBeCloseTo(1, 6);
    expect(result.cop).toBeCloseTo(4, 6);
    expect(result.coverage).toBe(1);
  });

  it('has no COP without electric energy', () => {
    expect(dayEnergy([], [[0, 4000]], 0, H).cop).toBeNull();
  });
});

describe('startOfLocalDay', () => {
  it('returns local midnight', () => {
    const noon = new Date(2026, 10, 15, 12, 30).getTime();
    expect(startOfLocalDay(noon)).toBe(new Date(2026, 10, 15).getTime());
  });
});
