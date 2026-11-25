import { describe, expect, it } from 'vitest';
import { makeDecisions, makeSeries } from '$mock/decisions';
import codes from '$mock/fixtures/codes.json';
import { BAND_TERMS, reasonCategory, seriesFromDecisions, stackSeries } from './series';

const NOW = Date.parse('2026-11-15T12:00:00Z');
const HOUR = 3_600_000;

describe('stackSeries', () => {
  const series = makeSeries(NOW - 6 * HOUR, NOW, 0, NOW);
  const stacked = stackSeries(series);

  it('stacks positive terms above and negative terms below the curve', () => {
    expect(stacked.points.length).toBeGreaterThan(300);
    for (const point of stacked.points) {
      for (const name of BAND_TERMS) {
        const band = point.bands[name];
        expect(band.hi).toBeGreaterThanOrEqual(band.lo - 1e-9);
        expect(band.hi >= point.curve - 1e-9 || band.lo <= point.curve + 1e-9).toBe(true);
      }
    }
  });

  it('keeps curve + terms + safety delta equal to the pre-round value', () => {
    const index = new Map(series.at.map((at, i) => [Date.parse(at), i]));
    for (const point of stacked.points) {
      const i = index.get(point.t) as number;
      const sum =
        point.curve +
        (series.room_feedback[i] ?? 0) +
        (series.plan[i] ?? 0) +
        (series.start_ramp[i] ?? 0) +
        (series.cycling_floor[i] ?? 0) +
        (series.stove?.[i] ?? 0) +
        (series.other[i] ?? 0) +
        (series.safety_delta[i] ?? 0);
      expect(sum).toBeCloseTo(point.preRound ?? Number.NaN, 6);
    }
  });

  it('stacks bands without overlap on the same side', () => {
    for (const point of stacked.points) {
      const upward = BAND_TERMS.map((name) => point.bands[name]).filter(
        (band) => band.hi > point.curve + 1e-9 && band.lo >= point.curve - 1e-9,
      );
      const sorted = [...upward].sort((a, b) => a.lo - b.lo);
      for (let i = 1; i < sorted.length; i += 1) {
        expect((sorted[i] as { lo: number }).lo).toBeGreaterThanOrEqual(
          (sorted[i - 1] as { hi: number }).hi - 1e-9,
        );
      }
    }
  });

  it('marks config version changes', () => {
    const wide = stackSeries(makeSeries(NOW - 24 * HOUR, NOW, 300, NOW));
    expect(wide.markers.length).toBe(1);
    expect(wide.markers[0]?.kind).toBe('config');
    expect(wide.markers[0]?.label).toBe('v12');
  });

  it('builds contiguous reason segments, including hold and refuse ticks', () => {
    const reasons = stacked.reasons.map((segment) => segment.reason);
    expect(reasons).toContain('inputs_missing');
    expect(reasons).toContain('heishamon_dead');
    for (let i = 1; i < stacked.reasons.length; i += 1) {
      const previous = stacked.reasons[i - 1];
      const current = stacked.reasons[i];
      expect(current?.from).toBe(previous?.to);
      expect(current?.reason).not.toBe(previous?.reason);
    }
  });

  it('has no curve gap points for hold and refuse ticks', () => {
    const missing = series.curve.filter((value) => value === null).length;
    expect(missing).toBeGreaterThan(0);
    expect(stacked.points.length).toBe(series.at.length - missing);
  });
});

describe('seriesFromDecisions', () => {
  it('produces the same columns as the server series for the same ticks', () => {
    const decisions = makeDecisions(NOW - HOUR, NOW, 500, NOW);
    const derived = seriesFromDecisions(decisions, 'a', 'b');
    const server = makeSeries(NOW - HOUR, NOW, 0, NOW);
    expect(derived.at).toEqual(server.at);
    expect(derived.curve).toEqual(server.curve);
    expect(derived.room_feedback).toEqual(server.room_feedback);
    expect(derived.safety_delta).toEqual(server.safety_delta);
    expect(derived.other).toEqual(server.other);
    expect(derived.reason).toEqual(server.reason);
    expect(derived.setpoint).toEqual(server.setpoint);
  });
});

describe('reasonCategory', () => {
  it('classifies every reason code', () => {
    for (const reason of codes.reason) {
      expect(['normal', 'limited', 'frozen', 'stopped', 'manual']).toContain(
        reasonCategory(reason),
      );
    }
    expect(reasonCategory('safety_clamp')).toBe('limited');
    expect(reasonCategory('heishamon_dead')).toBe('stopped');
    expect(reasonCategory('defrost_freeze')).toBe('frozen');
    expect(reasonCategory('override')).toBe('manual');
  });
});
