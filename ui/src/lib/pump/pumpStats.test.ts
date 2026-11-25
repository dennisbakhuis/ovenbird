import { describe, expect, it } from 'vitest';
import type { History } from '$lib/core/types';
import {
  copDots,
  copFit,
  daySegments,
  deltaSeries,
  dutyReading,
  humanizeLabel,
  runStats,
} from './pumpStats';

const T0 = Date.parse('2026-11-14T00:00:00Z');
const min = (n: number) => new Date(T0 + n * 60_000).toISOString();

function history(series: Record<string, [number, number][]>): History {
  return {
    from: min(0),
    to: min(120),
    step: 60,
    series: Object.fromEntries(
      Object.entries(series).map(([id, points]) => [
        id,
        { unit: null, points: points.map(([m, v]) => [min(m), v] as [string, number]) },
      ]),
    ),
  };
}

describe('daySegments', () => {
  it('builds compressor, defrost and hot water runs', () => {
    const h = history({
      'main/Compressor_Freq': [
        [0, 30],
        [10, 30],
        [20, 0],
        [40, 40],
        [60, 40],
        [80, 0],
      ],
      'main/Defrosting_State': [
        [0, 0],
        [50, 1],
        [55, 0],
        [80, 0],
      ],
      'main/ThreeWay_Valve_State': [
        [0, 0],
        [90, 1],
        [100, 0],
      ],
    });
    const segments = daySegments(h, T0 + 120 * 60_000);
    const on = (list: { from: number; to: number; state: string | null }[]) =>
      list
        .filter((s) => s.state === 'on')
        .map((s) => [(s.from - T0) / 60_000, (s.to - T0) / 60_000]);
    expect(on(segments.compressor)).toEqual([
      [0, 20],
      [40, 80],
    ]);
    expect(on(segments.defrost)).toEqual([[50, 55]]);
    expect(on(segments.dhw)).toEqual([[90, 100]]);
    expect(segments.quiet).toEqual([]);
  });
});

describe('deltaSeries', () => {
  it('subtracts at matching timestamps only', () => {
    expect(
      deltaSeries(
        [
          [1, 32],
          [2, 33],
        ],
        [
          [2, 28],
          [3, 27],
        ],
      ),
    ).toEqual([[2, 5]]);
  });
});

describe('dutyReading', () => {
  it('flags a duty above the maximum, as during a defrost', () => {
    expect(dutyReading(220, 159).above).toBe(true);
    expect(dutyReading(120, 159).above).toBe(false);
    expect(dutyReading(null, 159).above).toBe(false);
  });
});

describe('copDots and copFit', () => {
  it('drops idle hours and matches on timestamps', () => {
    const dots = copDots(
      [
        [1, 5],
        [2, 6],
        [3, 7],
      ],
      [
        [1, 2000],
        [2, 100],
        [3, 2000],
      ],
      [
        [1, 8000],
        [2, 0],
        [3, 9000],
      ],
    );
    expect(dots.map((d) => d.cop)).toEqual([4, 4.5]);
  });

  it('fits a rising line', () => {
    const dots = [0, 2, 4, 6, 8].map((outside, i) => ({ t: i, outside, cop: 3 + outside * 0.1 }));
    const fit = copFit(dots);
    expect(fit?.slope).toBeCloseTo(0.1);
    expect(fit?.intercept).toBeCloseTo(3);
  });

  it('refuses to fit too few or degenerate dots', () => {
    expect(copFit([{ t: 0, outside: 1, cop: 3 }])).toBeNull();
    const flat = [1, 2, 3, 4, 5].map((t) => ({ t, outside: 4, cop: 3 }));
    expect(copFit(flat)).toBeNull();
  });
});

describe('humanizeLabel', () => {
  it('turns catalogue ids into words', () => {
    expect(humanizeLabel('compensation_curve')).toBe('Compensation curve');
  });
});

describe('runStats (legacy)', () => {
  it('still counts starts from frequency points', () => {
    const stats = runStats(
      [
        [min(0), 0],
        [min(10), 30],
        [min(20), 0],
      ],
      [],
    );
    expect(stats.starts).toBe(1);
  });
});
