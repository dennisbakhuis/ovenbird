import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '$lib/core/api';
import {
  coverageCells,
  customPeriod,
  identityState,
  inPeriod,
  presetPeriod,
  replayBand,
  replayBody,
  seriesPoints,
  topShares,
  type ReplayCoverage,
  type ReplayJob,
  type ReplaySeries,
} from './replay';
import { ReplayRun } from './run.svelte';

const DAY = 86_400_000;
const NOW = Date.parse('2026-11-20T12:00:00Z');

function coverage(days: [number, number][]): ReplayCoverage {
  return {
    from: '2026-11-18T00:00:00Z',
    to: '2026-11-20T12:00:00Z',
    timezone: 'UTC',
    interval_s: 60,
    retention_days: 30,
    max_days: 31,
    oldest: null,
    newest: null,
    versions: [],
    days: days.map(([decisions, expected], index) => {
      const from = Date.parse('2026-11-18T00:00:00Z') + index * DAY;
      return {
        date: new Date(from).toISOString().slice(0, 10),
        from: new Date(from).toISOString(),
        to: new Date(from + DAY).toISOString(),
        decisions,
        expected,
        first: null,
        last: null,
      };
    }),
  };
}

function job(state: ReplayJob['state'], progress = 0.5, id = 'a1'): ReplayJob {
  return {
    id,
    state,
    phase: state === 'running' ? 'replay' : state,
    progress,
    from: '2026-11-19T00:00:00Z',
    to: '2026-11-20T00:00:00Z',
    config: { kind: 'active', version: 12 },
    started_at: '2026-11-20T12:00:00Z',
    finished_at: null,
    error: null,
    result: null,
  };
}

describe('replay periods', () => {
  it('ends a preset now and keeps it within the longest period', () => {
    expect(presetPeriod('7d', NOW, 31)).toEqual({ from: NOW - 7 * DAY, to: NOW });
    expect(presetPeriod('30d', NOW, 10)).toEqual({ from: NOW - 10 * DAY, to: NOW });
  });

  it('checks a custom period', () => {
    expect(customPeriod('', '2026-11-20T00:00', 31)).toEqual({ problem: 'invalid' });
    expect(customPeriod('2026-11-20T00:00', '2026-11-19T00:00', 31)).toEqual({
      problem: 'order',
    });
    expect(customPeriod('2026-09-01T00:00', '2026-11-19T00:00', 31)).toEqual({
      problem: 'too_long',
    });
    const ok = customPeriod('2026-11-18T00:00', '2026-11-19T00:00', 31);
    expect('from' in ok && ok.to - ok.from).toBe(DAY);
  });

  it('builds the request body for each configuration', () => {
    const period = { from: NOW - 30 * DAY, to: NOW };
    expect(replayBody(period, { kind: 'active' })).toEqual({
      from: new Date(period.from).toISOString(),
      to: new Date(NOW).toISOString(),
      config: 'active',
      step: 3600,
    });
    expect(replayBody({ from: NOW - DAY, to: NOW }, { kind: 'version', version: 9 })).toMatchObject(
      { config: 'version', version: 9, step: 60 },
    );
    const draft = replayBody(period, { kind: 'draft', changes: { control_comfort_c: 21.6 } });
    expect(draft.changes).toEqual({ control_comfort_c: 21.6 });
    expect(replayBody(period, { kind: 'draft' }).changes).toEqual({});
  });
});

describe('replay coverage', () => {
  it('grades each day by its stored share', () => {
    const cells = coverageCells(
      coverage([
        [0, 1440],
        [700, 1440],
        [1438, 1440],
      ]),
    );
    expect(cells.map((cell) => cell.level)).toEqual(['none', 'part', 'full']);
    expect(cells[1]?.share).toBeCloseTo(700 / 1440);
  });

  it('knows which days a period touches', () => {
    const [first, second] = coverageCells(
      coverage([
        [1, 1440],
        [1, 1440],
      ]),
    );
    const period = { from: Date.parse('2026-11-19T06:00:00Z'), to: NOW };
    expect(inPeriod(first!, period)).toBe(false);
    expect(inPeriod(second!, period)).toBe(true);
    expect(inPeriod(second!, null)).toBe(false);
  });
});

describe('replay results', () => {
  const series: ReplaySeries = {
    at: ['2026-11-19T00:00:00Z', '2026-11-19T01:00:00Z', '2026-11-19T02:00:00Z'],
    recorded: [30, null, 31],
    replayed: [31, 32, null],
    pump: [30, 34, 31],
  };

  it('turns series columns into points and a band, leaving gaps out', () => {
    expect(seriesPoints(series, 'recorded')).toEqual([
      [Date.parse('2026-11-19T00:00:00Z'), 30],
      [Date.parse('2026-11-19T02:00:00Z'), 31],
    ]);
    const band = replayBand(series);
    expect(band.upper.map(([, v]) => v)).toEqual([30, 31, 31, 34, 34, 32]);
    expect(band.lower.map(([, v]) => v)).toEqual([30, 30, 30, 32, 32, 32]);
    expect(band.upper.at(-1)?.[0]).toBe(Date.parse('2026-11-19T02:00:00Z'));
  });

  it('orders shares and reads the identity check', () => {
    expect(topShares({ a: 0.1, b: 0.6, c: 0.3 }, 2)).toEqual([
      ['b', 0.6],
      ['c', 0.3],
    ]);
    const identity = { ok: true, ticks: 10, mismatches: 0, first_mismatch: null, unknown: 0 };
    expect(identityState({ ...identity, versions: [] })).toBe('exact');
    expect(identityState({ ...identity, ok: false, mismatches: 2, versions: [] })).toBe('differs');
    expect(identityState({ ...identity, ok: null, ticks: 0, versions: [] })).toBe('unchecked');
  });
});

describe('ReplayRun', () => {
  afterEach(() => vi.useRealTimers());

  it('polls a started job until it is done', async () => {
    vi.useFakeTimers();
    const answers = [job('running', 0.6), job('done', 1)];
    const poll = vi.fn(async () => answers.shift() as ReplayJob);
    const run = new ReplayRun({ start: async () => job('running', 0), poll });
    await run.start({ from: 'a', to: 'b', config: 'active' });
    expect(run.running).toBe(true);
    await vi.advanceTimersByTimeAsync(700);
    expect(run.job?.progress).toBe(0.6);
    await vi.advanceTimersByTimeAsync(700);
    expect(run.job?.state).toBe('done');
    expect(run.running).toBe(false);
    await vi.advanceTimersByTimeAsync(2000);
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it('stops polling while paused and resumes', async () => {
    vi.useFakeTimers();
    const poll = vi.fn(async () => job('running', 0.7));
    const run = new ReplayRun({ start: async () => job('running', 0), poll });
    await run.start({ from: 'a', to: 'b', config: 'active' });
    run.pause();
    await vi.advanceTimersByTimeAsync(2000);
    expect(poll).not.toHaveBeenCalled();
    run.resume();
    await vi.advanceTimersByTimeAsync(700);
    expect(poll).toHaveBeenCalledTimes(1);
    run.pause();
  });

  it('names a refusal and an expired job', async () => {
    vi.useFakeTimers();
    const refused = new ReplayRun({
      start: async () => {
        throw new ApiError('api/v1/replay', 400, { detail: 'the draft does not validate: x' });
      },
    });
    await refused.start({ from: 'a', to: 'b', config: 'draft' });
    expect(refused.problem).toBe('invalid');
    expect(refused.detail).toBe('the draft does not validate: x');

    const forbidden = new ReplayRun({
      start: async () => {
        throw new ApiError('api/v1/replay', 403);
      },
    });
    await forbidden.start({ from: 'a', to: 'b', config: 'active' });
    expect(forbidden.problem).toBe('forbidden');

    const expired = new ReplayRun({
      start: async () => job('running', 0),
      poll: async () => {
        throw new ApiError('api/v1/replay/a1', 404);
      },
    });
    await expired.start({ from: 'a', to: 'b', config: 'active' });
    await vi.advanceTimersByTimeAsync(700);
    expect(expired.problem).toBe('expired');
    expect(expired.job).toBeNull();
  });

  it('cancels the running job', async () => {
    vi.useFakeTimers();
    const cancel = vi.fn(async () => job('cancelled', 0.3));
    const run = new ReplayRun({ start: async () => job('running', 0), cancel });
    await run.start({ from: 'a', to: 'b', config: 'active' });
    await run.cancel();
    expect(cancel).toHaveBeenCalledWith('a1');
    expect(run.job?.state).toBe('cancelled');
    expect(run.running).toBe(false);
  });

  it('cancels a job asked to stop while it was still being started', async () => {
    vi.useFakeTimers();
    let started: (value: ReturnType<typeof job>) => void = () => undefined;
    const cancel = vi.fn(async () => job('cancelled', 0.1));
    const run = new ReplayRun({
      start: () => new Promise((resolve) => (started = resolve)),
      cancel,
    });
    const starting = run.start({ from: 'a', to: 'b', config: 'active' });
    expect(run.running).toBe(true);
    await run.cancel();
    expect(cancel).not.toHaveBeenCalled();
    started(job('running', 0));
    await starting;
    expect(cancel).toHaveBeenCalledWith('a1');
    expect(run.job?.state).toBe('cancelled');
  });
});
