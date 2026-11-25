import { describe, expect, it } from 'vitest';
import type { InsightDaily, InsightDay } from '$lib/house/insight';
import type { History } from '$lib/core/types';
import { GLYPHS } from '$components/charts/glyphs';
import {
  buildLanes,
  foreignZone,
  insightToday,
  serviceMidnight,
  SIGNAL,
  todayStats,
  withDaily,
  yesterdaySoFar,
} from './model';

const labels = { compressor: 'C', defrost: 'D', dhw: 'W', quiet: 'Q', on: 'on' };
const iso = (ms: number) => new Date(ms).toISOString();

function history(series: Record<string, [number, number | null][]>): History {
  return {
    from: iso(0),
    to: iso(1),
    step: 60,
    series: Object.fromEntries(
      Object.entries(series).map(([id, points]) => [
        id,
        { unit: null, points: points.map(([t, v]) => [iso(t), v]) },
      ]),
    ),
  } as History;
}

describe('buildLanes', () => {
  it('builds four lanes with run-length segments', () => {
    const base = new Date(2026, 10, 15, 8).getTime();
    const h = history({
      [SIGNAL.frequency]: [
        [base, 0],
        [base + 60_000, 30],
        [base + 120_000, 30],
        [base + 180_000, 0],
      ],
      [SIGNAL.defrost]: [[base, 0]],
      [SIGNAL.valve]: [[base, 0]],
      [SIGNAL.quiet]: [
        [base, 1],
        [base + 60_000, 1],
      ],
    });
    const lanes = buildLanes(h, base + 240_000, labels);
    expect(lanes.map((l) => l.id)).toEqual(['compressor', 'defrost', 'dhw', 'quiet']);
    expect(lanes[0]?.segments).toHaveLength(1);
    expect(lanes[0]?.segments[0]).toMatchObject({ from: base + 60_000, to: base + 180_000 });
    expect(lanes[1]?.segments).toHaveLength(0);
    expect(lanes[3]?.segments).toHaveLength(1);
  });

  it('copes with a missing history', () => {
    expect(buildLanes(null, 1000, labels).every((lane) => lane.segments.length === 0)).toBe(true);
  });

  it('drops the hot-water lane while hot water is hidden, unless the pump made a run', () => {
    const base = new Date(2026, 10, 15, 8).getTime();
    const quiet = history({ [SIGNAL.valve]: [[base, 0]] });
    expect(buildLanes(quiet, base + 240_000, labels, false).map((l) => l.id)).toEqual([
      'compressor',
      'defrost',
      'quiet',
    ]);
    const run = history({
      [SIGNAL.valve]: [
        [base, 1],
        [base + 60_000, 1],
      ],
    });
    const lanes = buildLanes(run, base + 240_000, labels, false);
    const dhw = lanes.find((l) => l.id === 'dhw');
    expect(dhw?.segments).toHaveLength(1);
    expect(dhw?.icon).toBe(GLYPHS.gear);
  });
});

describe('todayStats', () => {
  it('integrates since local midnight only', () => {
    const now = new Date(2026, 10, 15, 2).getTime();
    const midnight = new Date(2026, 10, 15).getTime();
    const hour = 3_600_000;
    const h = history({
      [SIGNAL.electric]: [
        [midnight - hour, 5000],
        [midnight, 1000],
        [midnight + hour, 1000],
      ],
      [SIGNAL.heat]: [
        [midnight - hour, 5000],
        [midnight, 4000],
        [midnight + hour, 4000],
      ],
      [SIGNAL.frequency]: [
        [midnight, 0],
        [midnight + 600_000, 20],
        [midnight + 1_200_000, 0],
      ],
      [SIGNAL.defrost]: [[midnight, 0]],
    });
    const stats = todayStats(h, now);
    expect(stats?.energy.electricKwh).toBeCloseTo(2 / 3, 3);
    expect(stats?.energy.cop).toBeCloseTo(4, 1);
    expect(stats?.starts).toBe(1);
    expect(stats?.meanRunS).toBe(600);
    expect(stats?.longestRunS).toBe(600);
  });

  it('is null without history', () => {
    expect(todayStats(null, 0)).toBeNull();
  });
});

describe('today from insight/daily', () => {
  const day = (over: Partial<InsightDay> = {}): InsightDay =>
    ({
      date: '2026-11-18',
      from: '2026-11-17T23:00:00Z',
      to: '2026-11-18T23:00:00Z',
      hours: 24,
      partial: true,
      coverage: 0.97,
      electric_kwh: 4.8,
      heat_kwh: 19.1,
      cop: 3.98,
      compressor_starts: 3,
      run_s: 5400,
      defrosts: 1,
      ...over,
    }) as InsightDay;
  const daily = (timezone: string, days: InsightDay[]): InsightDaily => ({
    timezone,
    band_below_k: 0.5,
    room_signal: null,
    days,
  });
  const local = {
    energy: { electricKwh: 0.9, heatKwh: 3, cop: 3.3, coverage: 1 },
    starts: 1,
    defrosts: 0,
    meanRunS: 600,
    longestRunS: 900,
  };

  it('takes today from the service and keeps the runs from the history', () => {
    const today = insightToday(daily('Europe/Amsterdam', [day()]));
    expect(withDaily(local, today)).toEqual({
      energy: { electricKwh: 4.8, heatKwh: 19.1, cop: 3.98, coverage: 0.97 },
      starts: 3,
      defrosts: 1,
      meanRunS: 600,
      longestRunS: 900,
    });
  });

  it('falls back to the service mean only without runs in the history', () => {
    const today = insightToday(daily('Europe/Amsterdam', [day()]));
    const stats = withDaily({ ...local, meanRunS: null, longestRunS: null }, today);
    expect(stats?.meanRunS).toBe(1800);
  });

  it('keeps the history figures without a partial service day', () => {
    expect(insightToday(daily('UTC', [day({ partial: false })]))).toBeNull();
    expect(withDaily(local, null)).toBe(local);
  });

  it("starts today at the service's midnight", () => {
    expect(serviceMidnight(daily('Europe/Amsterdam', [day()]))).toBe(
      Date.parse('2026-11-17T23:00:00Z'),
    );
    expect(serviceMidnight(null)).toBeNull();
  });

  it('names the service time zone only when it differs from the browser', () => {
    expect(foreignZone(daily('Europe/Amsterdam', []), 'Europe/Amsterdam')).toBeNull();
    expect(foreignZone(daily('Europe/Berlin', []), 'Europe/Amsterdam')).toBeNull();
    expect(foreignZone(daily('UTC', []), 'Europe/Amsterdam')).toBe('UTC');
    expect(foreignZone(daily('America/New_York', []), 'Europe/Amsterdam')).toBe('America/New_York');
  });
});

describe('yesterdaySoFar', () => {
  const HOUR = 3_600_000;
  const flat = (watts: number, hours: number): [number, number][] =>
    Array.from({ length: hours * 12 + 1 }, (_, i) => [i * 300_000, watts]);

  it('adds up the electric energy of yesterday until this time', () => {
    const kwh = yesterdaySoFar(
      history({ [SIGNAL.electric]: flat(1000, 4), [SIGNAL.heat]: flat(3500, 4) }),
      0,
      4 * HOUR,
    );
    expect(kwh).toBeCloseTo(4, 1);
  });

  it('is null without history or with too little of the window covered', () => {
    expect(yesterdaySoFar(null, 0, HOUR)).toBeNull();
    expect(
      yesterdaySoFar(
        history({ [SIGNAL.electric]: flat(1000, 1), [SIGNAL.heat]: flat(1, 1) }),
        0,
        10 * HOUR,
      ),
    ).toBeNull();
  });
});
