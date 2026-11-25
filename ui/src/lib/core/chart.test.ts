import { describe, expect, it } from 'vitest';
import {
  asPoints,
  axisFor,
  distributeHeights,
  layoutLabels,
  layoutMarkers,
  linearScale,
  mergeRuns,
  nearestIndex,
  nightByHours,
  nightIntervals,
  niceStep,
  niceTicks,
  panelLayout,
  runLengthSegments,
  runStats,
  segmentAt,
  stepCursor,
  sunTimes,
  timeTicks,
  unionTimes,
  valueAt,
  type Point,
} from './chart';

const MIN = 60_000;

describe('scales and ticks', () => {
  it('puts at least three time ticks across a span', () => {
    const day = 24 * 60 * MIN;
    const from = new Date(2026, 10, 4, 13).getTime();
    expect(timeTicks(from, from + 14 * day, 6).length).toBeGreaterThanOrEqual(6);
    expect(timeTicks(from, from + day, 6).length).toBeGreaterThanOrEqual(4);
    expect(timeTicks(from, from + 7 * day, 6).length).toBeGreaterThanOrEqual(3);
  });

  it('rounds steps to 1, 2 or 5 times a power of ten', () => {
    expect(niceStep(0.03)).toBe(0.05);
    expect(niceStep(0.2)).toBe(0.2);
    expect(niceStep(7)).toBe(10);
    expect(niceStep(1800)).toBe(2000);
    expect(niceStep(0)).toBe(1);
  });

  it('keeps whole-degree ticks by default and allows fine ones on request', () => {
    expect(niceTicks(0, 20, 5)).toEqual([0, 5, 10, 15, 20]);
    expect(niceTicks(21, 22, 5)).toEqual([21, 22]);
    expect(niceTicks(20.9, 21.7, 4, 1e-9)).toEqual([21, 21.2, 21.4, 21.6]);
    expect(niceTicks(0, 9000, 5)).toEqual([0, 2000, 4000, 6000, 8000]);
  });

  it('maps and inverts linearly', () => {
    const scale = linearScale(0, 10, 100, 200);
    expect(scale(5)).toBe(150);
    expect(scale.invert(175)).toBe(7.5);
    const flipped = linearScale(0, 10, 50, 0);
    expect(flipped(10)).toBe(0);
    expect(flipped.invert(25)).toBe(5);
  });

  it('pads and snaps axes, honours zero and fixed ends', () => {
    const water: Point[] = [
      [0, 24],
      [1, 48],
    ];
    expect(axisFor([water])).toEqual({ min: 20, max: 50 });
    expect(axisFor([water], { zero: true })).toEqual({ min: 0, max: 60 });
    expect(axisFor([water], { min: 0, max: 60 })).toEqual({ min: 0, max: 60 });
    expect(
      axisFor([
        [
          [0, 0],
          [1, 320],
        ],
      ])?.min,
    ).toBe(0);
    expect(axisFor([[]])).toBeNull();
    const flat = axisFor([[[0, 21.2]]]);
    expect(flat && flat.max > flat.min).toBe(true);
  });
});

describe('panel layout', () => {
  it('stacks panels with gaps', () => {
    expect(panelLayout([100, 60, 30], 10, 5)).toEqual([
      { top: 5, height: 100 },
      { top: 115, height: 60 },
      { top: 185, height: 30 },
    ]);
  });

  it('splits space by weight with a minimum', () => {
    expect(distributeHeights([2, 1, 1], 420, 10)).toEqual([200, 100, 100]);
    expect(distributeHeights([10, 1], 100, 0, 24)).toEqual([90, 24]);
    expect(distributeHeights([], 100, 0)).toEqual([]);
  });

  it('places labels on two rows and drops what does not fit', () => {
    const rows = layoutLabels(
      [
        { x: 100, width: 60 },
        { x: 120, width: 30 },
        { x: 130, width: 30 },
        { x: 300, width: 30 },
      ],
      2,
      4,
    );
    expect(rows).toEqual([0, 1, -1, 0]);
  });

  it('lays marker labels out left to right, right-aligns at the edge and drops overlaps', () => {
    const placed = layoutMarkers(
      [
        { x: 290, width: 40 },
        { x: 100, width: 60 },
        { x: 130, width: 30 },
        { x: 180, width: 30 },
      ],
      300,
    );
    expect(placed).toEqual([
      { label: true, align: 'end' },
      { label: true, align: 'start' },
      { label: false, align: 'start' },
      { label: true, align: 'start' },
    ]);
  });

  it('drops a right-aligned label that would run into the previous one', () => {
    const placed = layoutMarkers(
      [
        { x: 250, width: 40 },
        { x: 280, width: 40 },
      ],
      300,
    );
    expect(placed.map((p) => p.label)).toEqual([true, false]);
  });
});

describe('run-length segments', () => {
  const hz: Point[] = [
    [0, 0],
    [1 * MIN, 30],
    [2 * MIN, 32],
    [3 * MIN, 60],
    [4 * MIN, 0],
    [5 * MIN, 40],
  ];

  it('merges equal states and ends the last sample at endT', () => {
    const segments = runLengthSegments(hz, (v) => (v > 0 ? 'on' : null), { endT: 7 * MIN });
    expect(segments).toEqual([
      { from: 1 * MIN, to: 4 * MIN, state: 'on' },
      { from: 5 * MIN, to: 7 * MIN, state: 'on' },
    ]);
    expect(runStats(segments)).toEqual({ count: 2, totalMs: 5 * MIN, longestMs: 3 * MIN });
  });

  it('splits by intensity level and merges back without it', () => {
    const segments = runLengthSegments(hz, (v) => (v > 0 ? 'on' : null), {
      endT: 6 * MIN,
      level: (v) => v / 60,
      levels: 2,
    });
    expect(segments.map((s) => [s.from / MIN, s.to / MIN, s.level])).toEqual([
      [1, 2, 0.5],
      [2, 4, 1],
      [5, 6, 1],
    ]);
    expect(mergeRuns(segments)).toEqual([
      { from: 1 * MIN, to: 4 * MIN, state: 'on' },
      { from: 5 * MIN, to: 6 * MIN, state: 'on' },
    ]);
  });

  it('caps holds at the gap and keeps distinct states apart', () => {
    const valve: Point[] = [
      [0, 1],
      [60 * MIN, 1],
      [61 * MIN, 0],
    ];
    const segments = runLengthSegments(valve, (v) => (v === 1 ? 'dhw' : 'heat'), {
      gapMs: 10 * MIN,
      endT: 70 * MIN,
    });
    expect(segments).toEqual([
      { from: 0, to: 10 * MIN, state: 'dhw' },
      { from: 60 * MIN, to: 61 * MIN, state: 'dhw' },
      { from: 61 * MIN, to: 70 * MIN, state: 'heat' },
    ]);
    expect(runStats(segments, 'dhw').count).toBe(2);
  });

  it('finds the segment at a time, end inclusive', () => {
    const segments = [
      { from: 0, to: 10, state: 'a' },
      { from: 20, to: 30, state: 'b' },
    ];
    expect(segmentAt(segments, 5)?.state).toBe('a');
    expect(segmentAt(segments, 15)).toBeNull();
    expect(segmentAt(segments, 30)?.state).toBe('b');
    expect(segmentAt([], 1)).toBeNull();
  });
});

describe('crosshair lookup', () => {
  const points: Point[] = [
    [0, 1],
    [10, 2],
    [20, 3],
  ];

  it('finds the nearest sample, or the held one for steps', () => {
    expect(valueAt(points, 4)).toEqual([0, 1]);
    expect(valueAt(points, 6)).toEqual([10, 2]);
    expect(valueAt(points, 19, 'step')).toEqual([10, 2]);
    expect(valueAt(points, -5, 'step')).toBeNull();
    expect(valueAt(points, 50, 'nearest', 10)).toBeNull();
    expect(valueAt(points, 50, 'step')).toEqual([20, 3]);
    expect(valueAt([], 5)).toBeNull();
    expect(nearestIndex([0, 10, 20], 14)).toBe(1);
  });

  it('merges timestamps of several series', () => {
    expect(
      unionTimes([
        [
          [5, 0],
          [1, 0],
        ],
        [
          [3, 0],
          [5, 1],
        ],
      ]),
    ).toEqual([1, 3, 5]);
  });

  it('steps the cursor with the keyboard', () => {
    const times = Array.from({ length: 25 }, (_, i) => i * 10);
    expect(stepCursor(times, null, 'ArrowLeft', 0, 240)).toBe(240);
    expect(stepCursor(times, 100, 'ArrowLeft', 0, 240)).toBe(90);
    expect(stepCursor(times, 100, 'ArrowRight', 0, 240)).toBe(110);
    expect(stepCursor(times, 240, 'ArrowRight', 0, 240)).toBe(240);
    expect(stepCursor(times, 100, 'Home', 0, 240)).toBe(0);
    expect(stepCursor(times, 100, 'End', 0, 240)).toBe(240);
    expect(stepCursor(times, 100, 'PageUp', 0, 240)).toBe(120);
    expect(stepCursor(times, 100, 'ArrowLeft', 0, 240, true)).toBe(80);
    expect(stepCursor(times, 100, 'a', 0, 240)).toBeUndefined();
    expect(stepCursor([], null, 'ArrowRight', 0, 480)).toBe(480);
    expect(stepCursor([], 480, 'ArrowLeft', 0, 480)).toBe(470);
  });
});

describe('night shading', () => {
  it('computes sunrise and sunset for Utrecht in November', () => {
    const sun = sunTimes(Date.parse('2026-11-15T12:00:00Z'), 52.09, 5.12);
    if ('polar' in sun) throw new Error('unexpected polar day');
    expect(Math.abs(sun.rise - Date.parse('2026-11-15T07:01:00Z'))).toBeLessThan(10 * MIN);
    expect(Math.abs(sun.set - Date.parse('2026-11-15T15:46:00Z'))).toBeLessThan(10 * MIN);
  });

  it('reports polar night and midnight sun', () => {
    expect(sunTimes(Date.parse('2026-12-21T12:00:00Z'), 78, 15)).toEqual({ polar: 'night' });
    expect(sunTimes(Date.parse('2026-06-21T12:00:00Z'), 78, 15)).toEqual({ polar: 'day' });
  });

  it('clips nights to the window', () => {
    const from = Date.parse('2026-11-15T12:00:00Z');
    const to = Date.parse('2026-11-16T12:00:00Z');
    const nights = nightIntervals(from, to, 52.09, 5.12);
    expect(nights).toHaveLength(1);
    const night = nights[0] as { from: number; to: number };
    expect((night.to - night.from) / 3_600_000).toBeGreaterThan(14);
    expect((night.to - night.from) / 3_600_000).toBeLessThan(16.5);
    expect(nightByHours(from, to, 22, 7).every((n) => n.from >= from && n.to <= to)).toBe(true);
    expect(
      nightByHours(from, to, 22, 7).reduce((sum, n) => sum + n.to - n.from, 0) / 3_600_000,
    ).toBe(9);
  });

  it('turns constants into flat lines', () => {
    expect(asPoints(21.6, 0, 10)).toEqual([
      [0, 21.6],
      [10, 21.6],
    ]);
  });
});
