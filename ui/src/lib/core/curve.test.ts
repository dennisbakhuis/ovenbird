import { describe, expect, it } from 'vitest';
import vectors from '$mock/fixtures/curve-vectors.json';
import {
  addPoint,
  cornerSamples,
  curveProblems,
  curveSensitivity,
  curveWater,
  densityBins,
  filterOutside,
  largestShift,
  removePoint,
  setOutside,
  setWater,
  type Curve,
} from './curve';

describe('curve mirrors the core HeatingCurve', () => {
  it.each(vectors.curves.map((c, i) => [i, c] as const))('water on vector curve %i', (_, c) => {
    for (const [outside, water] of c.samples)
      expect(curveWater(c.points as Curve, outside as number)).toBeCloseTo(water as number, 9);
    for (const [outside, slope] of c.sens)
      expect(curveSensitivity(c.points as Curve, outside as number)).toBeCloseTo(
        slope as number,
        9,
      );
  });

  it('filters the outside temperature like filter_outside', () => {
    let previous: number | null = null;
    let previousAt: number | null = null;
    for (const [at, sample, expected] of vectors.filter.steps as number[][]) {
      previous = filterOutside(
        previous,
        previousAt,
        sample as number,
        at as number,
        vectors.filter.tau_s,
      );
      previousAt = at as number;
      expect(previous).toBeCloseTo(expected as number, 9);
    }
  });
});

describe('curve edit operations keep the rules', () => {
  const base: Curve = [
    [-10, 39],
    [0, 34],
    [15, 25],
  ];

  it('holds water between neighbours', () => {
    expect(setWater(base, 1, 45)[1]?.[1]).toBe(39);
    expect(setWater(base, 1, 10)[1]?.[1]).toBe(25);
    expect(setWater(base, 1, 33.3)[1]?.[1]).toBe(33.5);
  });

  it('keeps outside strictly increasing', () => {
    expect(setOutside(base, 1, 50)[1]?.[0]).toBe(14);
    expect(setOutside(base, 1, -20)[1]?.[0]).toBe(-9);
  });

  it('adds and removes within 2..6 points and stays valid', () => {
    let curve = base;
    for (let i = 0; i < 10; i += 1) curve = addPoint(curve);
    expect(curve.length).toBe(6);
    expect(curveProblems(curve)).toEqual([]);
    for (let i = 0; i < 10; i += 1) curve = removePoint(curve, 0);
    expect(curve.length).toBe(2);
    expect(curveProblems(curve)).toEqual([]);
  });

  it('reports structural problems', () => {
    expect(curveProblems([[0, 30]])).toContain('too_few_points');
    expect(
      curveProblems([
        [0, 30],
        [0, 29],
      ]),
    ).toContain('outside_not_increasing');
    expect(
      curveProblems([
        [0, 30],
        [5, 31],
      ]),
    ).toContain('water_increases');
  });
});

describe('curve editor helpers', () => {
  const base: Curve = [
    [-10, 39],
    [0, 34],
    [15, 25],
  ];

  it('snaps water to whole degrees or to half degrees', () => {
    expect(setWater(base, 1, 34.4, undefined, 1)[1]?.[1]).toBe(34);
    expect(setWater(base, 1, 34.4, undefined, 0.5)[1]?.[1]).toBe(34.5);
  });

  it('bins samples per outside degree with a 10–90 % range', () => {
    const samples: [number, number][] = [
      [0.2, 30],
      [-0.3, 32],
      [0.1, 34],
      [5, 28],
      [Number.NaN, 30],
    ];
    const bins = densityBins(samples);
    expect(bins.map((b) => b.outside)).toEqual([0, 5]);
    expect(bins[0]).toMatchObject({ count: 3, median: 32 });
    expect(bins[0]?.low).toBeCloseTo(30.4, 9);
    expect(bins[0]?.high).toBeCloseTo(33.6, 9);
    expect(bins[1]).toMatchObject({ low: 28, high: 28, count: 1 });
  });

  it('samples both curves at every corner inside the range', () => {
    const other: Curve = [
      [-5, 38],
      [10, 27],
    ];
    expect(cornerSamples(base, other, -15, 20)).toEqual([-15, -10, -5, 0, 10, 15, 20]);
  });

  it('finds the largest shift between two curves', () => {
    const raised: Curve = [
      [-10, 39],
      [0, 36],
      [15, 25],
    ];
    expect(largestShift(base, raised)).toEqual({ at: 0, shift: 2 });
    expect(largestShift(base, base).shift).toBe(0);
  });
});
