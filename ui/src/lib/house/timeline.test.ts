import { describe, expect, it } from 'vitest';
import { errorStats, fittedOn, leftOutPeriods, runErrors } from './timeline';

describe('errorStats', () => {
  it('averages the days that have an error and names the worst one', () => {
    const stats = errorStats([
      { date: '2026-11-01', room_rmse_24h_k: 0.1, origins: 9 },
      { date: '2026-11-02', room_rmse_24h_k: null, origins: 0 },
      { date: '2026-11-03', room_rmse_24h_k: 0.3, origins: 9 },
    ]);
    expect(stats).toMatchObject({ days: 2, min: 0.1, max: 0.3, worstDate: '2026-11-03' });
    expect(stats?.mean).toBeCloseTo(0.2);
  });

  it('is null without a single value', () => {
    expect(errorStats([])).toBeNull();
    expect(errorStats([{ date: '2026-11-01', room_rmse_24h_k: null, origins: 0 }])).toBeNull();
  });
});

describe('leftOutPeriods', () => {
  it('reads the learner event fields and keeps missing ones null', () => {
    const out = leftOutPeriods([
      {
        kind: 'stove',
        start_local: '2026-11-23T10:00+01:00',
        end_local: '2026-11-23T15:00+01:00',
        hours: 5,
        excluded_hours: 17,
        peak_k: 3.4,
        reason: 'wood stove',
      },
      { kind: 'stove_mode' },
      'junk',
      null,
    ]);
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ kind: 'stove', hours: 5, excludedHours: 17, peakK: 3.4 });
    expect(out[1]).toMatchObject({ kind: 'stove_mode', start: null, hours: null });
  });

  it('accepts no events', () => {
    expect(leftOutPeriods(undefined)).toEqual([]);
    expect(leftOutPeriods([])).toEqual([]);
  });
});

describe('fittedOn', () => {
  it('reads the provenance and tolerates any missing field', () => {
    expect(
      fittedOn({ data_from: 'a', data_to: 'b', fit_days: 40.7, step_s: 60, method: 'full_plant' }),
    ).toMatchObject({ from: 'a', to: 'b', fitDays: 40.7, stepS: 60, method: 'full_plant' });
    expect(fittedOn({ fallback_reason: null, seed: 0 })).toMatchObject({
      fallbackReason: null,
      method: null,
    });
    expect(fittedOn(undefined).from).toBeNull();
  });
});

describe('runErrors', () => {
  it('keeps the runs that have an error, in order', () => {
    expect(
      runErrors([
        { model: 'a', data_to: '', promoted: true, ua_w_per_k: 1, room_rmse_24h_k: 0.11 },
        { model: 'b', data_to: '', promoted: true, ua_w_per_k: 1, room_rmse_24h_k: null },
        { model: 'c', data_to: '', promoted: true, ua_w_per_k: 1, room_rmse_24h_k: 0.09 },
      ]),
    ).toEqual([0.11, 0.09]);
  });
});
