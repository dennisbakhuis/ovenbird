import { describe, expect, it } from 'vitest';
import { makeSeries } from '$mock/decisions';
import { buildEpisodes, episodeAt, episodeGroup, holdIntervals } from './episodes';
import type { AlarmEvent, DecisionSeries } from '$lib/core/types';

const T0 = Date.parse('2026-11-15T10:00:00Z');
const MIN = 60_000;

interface Tick {
  m: number;
  reason: string;
  setpoint?: number | null;
  binding?: string | null;
  ladder?: string;
  version?: number | null;
}

function series(ticks: Tick[], toMinute?: number, step = 0): DecisionSeries {
  const last = ticks[ticks.length - 1]?.m ?? 0;
  const column = <T>(pick: (tick: Tick) => T) => ticks.map(pick);
  return {
    from: new Date(T0).toISOString(),
    to: new Date(T0 + (toMinute ?? last) * MIN).toISOString(),
    step,
    at: column((tick) => new Date(T0 + tick.m * MIN).toISOString()),
    setpoint: column((tick) => (tick.setpoint === undefined ? 31 : tick.setpoint)),
    pre_round: column(() => 31),
    curve: column(() => 31),
    room_feedback: column(() => 0),
    plan: column(() => 0),
    start_ramp: column(() => 0),
    cycling_floor: column(() => 0),
    stove: column(() => 0),
    other: column(() => 0),
    safety_delta: column(() => 0),
    safety_low: column(() => 25),
    safety_high: column(() => 36),
    reason: column((tick) => tick.reason),
    binding: column((tick) => tick.binding ?? null),
    ladder: column((tick) => tick.ladder ?? 'schedule_curve_feedback'),
    config_version: column((tick) => (tick.version === undefined ? 12 : tick.version)),
  };
}

const run = (from: number, to: number, tick: Omit<Tick, 'm'>): Tick[] =>
  Array.from({ length: to - from + 1 }, (_, i) => ({ ...tick, m: from + i }));

describe('buildEpisodes', () => {
  it('merges thirty identical minutes into one episode', () => {
    const episodes = buildEpisodes(series(run(0, 29, { reason: 'room_feedback' })));
    expect(episodes).toHaveLength(1);
    const [episode] = episodes;
    expect(episode?.ticks).toBe(30);
    expect(episode?.from).toBe(T0);
    expect(episode?.ongoing).toBe(true);
    expect(episode?.setpointFirst).toBe(31);
    expect(episode?.changes).toBe(0);
  });

  it('keeps one episode across setpoint changes of the same reason and counts them', () => {
    const ticks = [
      ...run(0, 9, { reason: 'room_feedback', setpoint: 32 }),
      ...run(10, 19, { reason: 'room_feedback', setpoint: 31 }),
      ...run(20, 29, { reason: 'room_feedback', setpoint: 32 }),
    ];
    const [episode] = buildEpisodes(series(ticks));
    expect(episode?.setpointFirst).toBe(32);
    expect(episode?.setpointLast).toBe(32);
    expect(episode?.setpointMin).toBe(31);
    expect(episode?.changes).toBe(2);
    expect(episode?.steps.map(([, v]) => v)).toEqual([32, 31, 32]);
  });

  it('absorbs dead-band and wait-time ticks into the running episode', () => {
    const ticks = [
      ...run(0, 4, { reason: 'room_feedback' }),
      ...run(5, 9, { reason: 'deadband_hold', binding: 'rounding' }),
      ...run(10, 14, { reason: 'dwell_hold', binding: 'dwell' }),
      ...run(15, 19, { reason: 'room_feedback' }),
    ];
    const episodes = buildEpisodes(series(ticks));
    expect(episodes).toHaveLength(1);
    expect(episodes[0]?.reasons).toEqual(['room_feedback', 'deadband_hold', 'dwell_hold']);
    expect(episodes[0]?.bindings).toEqual(['rounding', 'dwell']);
  });

  it('starts an episode of its own for dead-band ticks with nothing before them', () => {
    const ticks = [
      ...run(0, 4, { reason: 'deadband_hold', binding: 'deadband' }),
      ...run(5, 9, { reason: 'defrost_freeze' }),
    ];
    const episodes = buildEpisodes(series(ticks));
    expect(episodes.map((e) => e.reason)).toEqual(['deadband_hold', 'defrost_freeze']);
    expect(episodes[0]?.to).toBe(episodes[1]?.from);
  });

  it('merges a compressor start (ramp and cycling protection) into one episode', () => {
    const ticks = [
      ...run(0, 4, { reason: 'start_ramp', setpoint: 28 }),
      { m: 5, reason: 'cycling_protect', binding: 'cycling_floor', setpoint: 29 },
      ...run(6, 7, { reason: 'deadband_hold', binding: 'rounding', setpoint: 29 }),
      ...run(8, 12, { reason: 'start_ramp', setpoint: 31 }),
      ...run(13, 20, { reason: 'room_feedback', setpoint: 31 }),
    ];
    const episodes = buildEpisodes(series(ticks));
    expect(episodes.map((e) => e.reason)).toEqual(['start_ramp', 'room_feedback']);
    expect(episodes[0]?.setpointFirst).toBe(28);
    expect(episodes[0]?.setpointLast).toBe(31);
    expect(episodes[0]?.category).toBe('limited');
    expect(episodes[0]?.to).toBe(T0 + 13 * MIN);
    expect(episodeGroup('cycling_protect')).toBe('start');
  });

  it('keeps a long dead band after a start as an episode of its own', () => {
    const ticks = [
      ...run(0, 9, { reason: 'start_ramp', setpoint: 30 }),
      ...run(10, 99, { reason: 'deadband_hold', binding: 'deadband', setpoint: 30 }),
      ...run(100, 110, { reason: 'room_feedback', setpoint: 30 }),
    ];
    const episodes = buildEpisodes(series(ticks));
    expect(episodes.map((e) => [e.group, e.ticks])).toEqual([
      ['start', 10],
      ['keep', 90],
      ['room_feedback', 11],
    ]);
  });

  it('splits on hold and refuse ticks and never absorbs into them', () => {
    const ticks = [
      ...run(0, 4, { reason: 'room_feedback' }),
      ...run(5, 7, { reason: 'inputs_missing', ladder: 'hold', setpoint: 31 }),
      ...run(8, 9, { reason: 'heishamon_dead', ladder: 'refuse', setpoint: null }),
      ...run(10, 11, { reason: 'deadband_hold', binding: 'deadband' }),
    ];
    const episodes = buildEpisodes(series(ticks));
    expect(episodes.map((e) => [e.reason, e.ladder])).toEqual([
      ['room_feedback', 'schedule_curve_feedback'],
      ['inputs_missing', 'hold'],
      ['heishamon_dead', 'refuse'],
      ['deadband_hold', 'schedule_curve_feedback'],
    ]);
    expect(episodes[1]?.category).toBe('stopped');
    expect(episodes[2]?.setpointFirst).toBeNull();
  });

  it('splits on a config version change and remembers the old version', () => {
    const ticks = [
      ...run(0, 9, { reason: 'room_feedback', version: 11 }),
      ...run(10, 19, { reason: 'room_feedback', version: 12 }),
    ];
    const episodes = buildEpisodes(series(ticks));
    expect(episodes).toHaveLength(2);
    expect(episodes[1]?.versionFrom).toBe(11);
    expect(episodes[1]?.configVersion).toBe(12);
    expect(episodes[0]?.versionFrom).toBeNull();
  });

  it('ignores missing versions when looking for a change', () => {
    const ticks = [
      ...run(0, 4, { reason: 'room_feedback', version: 12 }),
      ...run(5, 9, { reason: 'room_feedback', version: null }),
      ...run(10, 14, { reason: 'room_feedback', version: 12 }),
    ];
    expect(buildEpisodes(series(ticks))).toHaveLength(1);
  });

  it('turns a gap in the ticks into a gap entry between two episodes', () => {
    const ticks = [
      ...run(0, 9, { reason: 'room_feedback' }),
      ...run(40, 49, { reason: 'room_feedback' }),
    ];
    const episodes = buildEpisodes(series(ticks));
    expect(episodes.map((e) => e.kind)).toEqual(['decisions', 'gap', 'decisions']);
    expect(episodes[0]?.to).toBe(T0 + 10 * MIN);
    expect(episodes[1]?.from).toBe(T0 + 10 * MIN);
    expect(episodes[1]?.to).toBe(T0 + 40 * MIN);
  });

  it('keeps gaps up to the step of a thinned series inside one episode', () => {
    const ticks = [0, 5, 10, 15, 20].map((m) => ({ m, reason: 'room_feedback' }));
    expect(buildEpisodes(series(ticks, 20, 300))).toHaveLength(1);
  });

  it('marks the last episode as not ongoing when the ticks stopped long ago', () => {
    const episodes = buildEpisodes(series(run(0, 9, { reason: 'room_feedback' }), 60));
    expect(episodes[0]?.ongoing).toBe(false);
    expect(episodes[0]?.to).toBe(T0 + 10 * MIN);
  });

  it('adds command holds as entries of their own in time order', () => {
    const ticks = run(0, 29, { reason: 'room_feedback' });
    const episodes = buildEpisodes(series(ticks), {
      holds: [{ from: T0 + 10 * MIN, to: T0 + 20 * MIN, reason: 'foreign writer', ongoing: false }],
    });
    expect(episodes.map((e) => e.kind)).toEqual(['decisions', 'hold']);
    expect(episodes[1]?.holdReason).toBe('foreign writer');
    expect(episodeAt(episodes, T0 + 15 * MIN)?.kind).toBe('decisions');
  });

  it('merges a day of mock ticks into far fewer episodes that tile the window', () => {
    const now = Date.parse('2026-11-15T12:00:00Z');
    const day = makeSeries(now - 24 * 3_600_000, now, 0, now);
    const episodes = buildEpisodes(day);
    expect(episodes.length).toBeGreaterThan(10);
    expect(episodes.length).toBeLessThan(day.at.length / 10);
    for (let i = 1; i < episodes.length; i += 1) {
      expect(episodes[i]?.from).toBe(episodes[i - 1]?.to);
    }
    expect(episodes.reduce((sum, e) => sum + e.ticks, 0)).toBe(day.at.length);
  });
});

describe('holdIntervals', () => {
  const event = (minute: number, kind: AlarmEvent['event'], reason = 'foreign writer') =>
    ({
      at: new Date(T0 + minute * MIN).toISOString(),
      code: 'command_hold',
      severity: 'warning',
      event: kind,
      message: '',
      detail: { reason },
    }) as AlarmEvent;

  it('pairs started with expired or released and leaves the last one open', () => {
    const holds = holdIntervals(
      [
        event(50, 'started', 'verification failed'),
        event(0, 'started'),
        event(20, 'expired'),
        { ...event(30, 'raised'), code: 'foreign_writer' },
      ],
      T0 + 60 * MIN,
    );
    expect(holds).toEqual([
      { from: T0, to: T0 + 20 * MIN, reason: 'foreign writer', ongoing: false },
      { from: T0 + 50 * MIN, to: T0 + 60 * MIN, reason: 'verification failed', ongoing: true },
    ]);
  });
});
