import { describe, expect, it } from 'vitest';
import { groupCommands, holdsTable, pairJournal } from './commandGroups';
import type { AlarmEvent, CommandEvent } from '$lib/core/types';

const cmd = (at: string, kind: string, value: number, status: string): CommandEvent => ({
  at,
  kind,
  value,
  status,
  attempt: 1,
  detail: status,
  topic: 't',
  payload: String(value),
});

describe('groupCommands', () => {
  const oldestFirst = [
    cmd('2026-11-15T10:00:00Z', 'water_setpoint', 30, 'queued'),
    cmd('2026-11-15T10:00:01Z', 'water_setpoint', 30, 'sent'),
    cmd('2026-11-15T10:00:10Z', 'water_setpoint', 30, 'verified'),
    cmd('2026-11-15T10:30:00Z', 'max_pump_duty', 159, 'queued'),
    cmd('2026-11-15T11:00:00Z', 'water_setpoint', 31, 'queued'),
    cmd('2026-11-15T11:00:05Z', 'water_setpoint', 31, 'refused'),
  ];

  it('makes one group per command, newest first, with the latest status', () => {
    const groups = groupCommands(oldestFirst);
    expect(groups.map((g) => [g.kind, g.value, g.latest.status])).toEqual([
      ['water_setpoint', 31, 'refused'],
      ['max_pump_duty', 159, 'queued'],
      ['water_setpoint', 30, 'verified'],
    ]);
    expect(groups[2]?.steps.map((s) => s.status)).toEqual(['verified', 'sent', 'queued']);
    expect(groups[2]?.durationS).toBe(10);
    expect(groups[1]?.durationS).toBeNull();
  });

  it('does not depend on the input order, also with equal timestamps', () => {
    const groups = groupCommands([...oldestFirst].reverse());
    expect(groups.map((g) => g.latest.status)).toEqual(['refused', 'queued', 'verified']);
    const same = groupCommands([
      cmd('2026-11-15T10:00:00Z', 'a', 1, 'verified'),
      cmd('2026-11-15T10:00:00Z', 'a', 1, 'sent'),
      cmd('2026-11-15T10:00:00Z', 'a', 1, 'queued'),
    ]);
    expect(same).toHaveLength(1);
    expect(same[0]?.steps.map((s) => s.status)).toEqual(['verified', 'sent', 'queued']);
  });

  it('keeps recorded commands (from a converted capture) apart, one group each', () => {
    const groups = groupCommands([
      cmd('2026-11-15T10:00:00Z', 'water_setpoint', 30, 'recorded'),
      cmd('2026-11-15T10:10:00Z', 'water_setpoint', 30, 'recorded'),
    ]);
    expect(groups.map((g) => [g.value, g.latest.status, g.steps.length])).toEqual([
      [30, 'recorded', 1],
      [30, 'recorded', 1],
    ]);
  });

  it('starts a new group for a new queue of the same kind', () => {
    const groups = groupCommands([
      cmd('2026-11-15T10:00:00Z', 'a', 1, 'queued'),
      cmd('2026-11-15T10:01:00Z', 'a', 2, 'queued'),
      cmd('2026-11-15T10:01:05Z', 'a', 2, 'sent'),
    ]);
    expect(groups.map((g) => [g.value, g.latest.status])).toEqual([
      [2, 'sent'],
      [1, 'queued'],
    ]);
  });
});

describe('pairJournal', () => {
  const ev = (at: string, event: AlarmEvent['event'], code = 'command_hold'): AlarmEvent => ({
    at,
    code,
    severity: 'warning',
    event,
    message: '',
    detail: {},
  });

  it('pairs a start with its end and reports the duration', () => {
    const pairs = pairJournal([
      ev('2026-11-15T08:00:00Z', 'started'),
      ev('2026-11-15T09:30:00Z', 'expired'),
      ev('2026-11-15T12:00:00Z', 'started'),
    ]);
    expect(pairs).toHaveLength(2);
    expect(pairs[0]?.to).toBeNull();
    expect(pairs[1]?.durationS).toBe(5400);
    expect(pairs[1]?.endEvent).toBe('expired');
  });

  it('turns the hold history into CSV rows, oldest first', () => {
    const start = {
      ...ev('2026-11-15T12:00:00Z', 'started'),
      message: 'hold 1',
      detail: {
        reason: 'foreign writer',
        latched: false,
        setting: 'water_setpoint',
        seen_value: 31,
      },
    };
    const table = holdsTable(
      pairJournal([
        ev('2026-11-15T08:00:00Z', 'started'),
        ev('2026-11-15T09:30:00Z', 'expired'),
        start,
      ]),
    );
    expect(table.header[0]).toBe('from');
    expect(table.rows).toHaveLength(2);
    expect(table.rows[0]?.slice(0, 3)).toEqual([
      '2026-11-15T08:00:00Z',
      '2026-11-15T09:30:00Z',
      5400,
    ]);
    expect(table.rows[1]).toEqual([
      '2026-11-15T12:00:00Z',
      null,
      null,
      'foreign writer',
      'false',
      'water_setpoint',
      null,
      31,
      'hold 1',
    ]);
  });

  it('keeps an end without a start in the window as its own row', () => {
    const pairs = pairJournal([ev('2026-11-15T08:00:00Z', 'cleared', 'low_flow')]);
    expect(pairs).toHaveLength(1);
    expect(pairs[0]?.durationS).toBeNull();
  });
});

describe('pairJournal with envelope corrections', () => {
  it('shows a recognised envelope correction as a closed one-moment row', () => {
    const event: AlarmEvent = {
      at: '2026-11-18T10:00:00Z',
      code: 'envelope_correction',
      severity: 'info',
      event: 'recognised',
      message: 'envelope rule corrected 41 to 36',
      detail: { seen_value: 36, ovenbird_value: 41 },
    };
    const [pair] = pairJournal([event]);
    expect(pair?.endEvent).toBe('recognised');
    expect(pair?.to).toBe(event.at);
    expect(pair?.durationS).toBeNull();
  });
});
