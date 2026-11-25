import { describe, expect, it } from 'vitest';
import { makeDivergence } from '$mock/shadow';
import {
  customWindow,
  dayHours,
  differenceBand,
  direction,
  divergenceStep,
  seriesPoints,
  writerSegments,
  type Divergence,
  type DivergenceSeries,
} from './shadow';

const series: DivergenceSeries = {
  at: [
    '2026-11-18T10:00:00Z',
    '2026-11-18T10:05:00Z',
    '2026-11-18T10:10:00Z',
    '2026-11-18T10:15:00Z',
    '2026-11-18T10:20:00Z',
  ],
  ovenbird: [31, 31, null, 30, 30],
  pump: [33, 31, 32, 30, null],
  diff: [-2, 0, null, 0, null],
  max_abs: [2, 0, null, 0, null],
  writer: ['other', 'other', 'other', 'ovenbird', null],
  mode: ['shadow', 'shadow', null, 'auto', 'auto'],
};

describe('shadow helpers', () => {
  it('picks the finest step with at most 1,500 points', () => {
    expect(divergenceStep(0, 24 * 3_600_000)).toBe(60);
    expect(divergenceStep(0, 7 * 86_400_000)).toBe(900);
    expect(divergenceStep(0, 31 * 86_400_000)).toBe(3600);
  });

  it('checks a custom window', () => {
    expect(customWindow('', '2026-11-18T10:00')).toEqual({ problem: 'invalid' });
    expect(customWindow('2026-11-18T10:00', '2026-11-18T09:00')).toEqual({ problem: 'order' });
    expect(customWindow('2026-10-01T00:00', '2026-11-18T00:00')).toEqual({ problem: 'too_long' });
    const ok = customWindow('2026-11-17T10:00', '2026-11-18T10:00');
    expect('from' in ok && ok.to - ok.from).toBe(86_400_000);
  });

  it('leaves missing values out of the lines and the band', () => {
    expect(seriesPoints(series, 'ovenbird').map(([, v]) => v)).toEqual([31, 31, 30, 30]);
    expect(seriesPoints(series, 'pump')).toHaveLength(4);
    const band = differenceBand(series);
    expect(band.upper.map(([, v]) => v)).toEqual([33, 31, 30]);
    expect(band.lower.map(([, v]) => v)).toEqual([31, 31, 30]);
  });

  it('merges writer runs and marks steps without both values as gaps', () => {
    const segments = writerSegments(series, 300);
    expect(segments.map((s) => s.state)).toEqual(['other', 'gap', 'ovenbird', 'gap']);
    expect(segments[0]?.to).toBe(Date.parse('2026-11-18T10:10:00Z'));
  });

  it('says which way ovenbird leans', () => {
    expect(direction(-0.4)).toBe('cooler');
    expect(direction(0.4)).toBe('warmer');
    expect(direction(0.01)).toBe('level');
    expect(direction(null)).toBe('level');
  });

  it('measures the hours of a day row', () => {
    expect(dayHours({ from: '2026-11-17T23:00:00Z', to: '2026-11-18T05:30:00Z' })).toBe(6.5);
  });
});

describe('mock divergence', () => {
  const now = Date.parse('2026-11-18T15:00:00Z');
  const day = (scenario = {}) =>
    makeDivergence(now - 86_400_000, now, 60, 1, now, scenario) as Divergence;

  it('summarises like the service and is deterministic', () => {
    const a = day();
    expect(a).toEqual(day());
    const s = a.summary;
    expect(s.minutes).toBe(1440);
    expect(s.compared_minutes + s.gap_minutes).toBe(s.minutes);
    expect(s.episodes).toBe(a.episodes_total);
    expect(a.series.at).toHaveLength(1440);
    expect(a.days.reduce((sum, d) => sum + d.minutes, 0)).toBe(1440);
    const starts = a.episodes.map((ep) => Date.parse(ep.start));
    expect([...starts].sort((x, y) => x - y)).toEqual(starts);
  });

  it('runs the pump 2 K above ovenbird in shadow mode now, as an open episode', () => {
    const shadow = day({ mode: 'shadow' });
    const last = shadow.episodes[shadow.episodes.length - 1];
    expect(last?.ended_by).toBe('open');
    expect(last?.max_abs_k).toBeGreaterThanOrEqual(2);
    expect(shadow.series.diff[shadow.series.diff.length - 1]).toBe(-2);
    expect(shadow.series.writer[shadow.series.writer.length - 1]).toBe('other');
  });

  it('has episodes, gaps and minutes written by ovenbird over two weeks', () => {
    const weeks = makeDivergence(now - 14 * 86_400_000, now, 900, 1, now, {}) as Divergence;
    expect(weeks.summary.episodes).toBeGreaterThan(2);
    expect(weeks.summary.gap_minutes).toBeGreaterThan(0);
    expect(weeks.series.writer).toContain('ovenbird');
    expect(weeks.series.writer).toContain('other');
    expect(weeks.days.length).toBeGreaterThanOrEqual(14);
  });
});
