import { describe, expect, it } from 'vitest';
import { pumpStateKind, pumpStateOf } from './pumpState';
import type { Snapshot } from '$lib/core/types';

const base = { alive: true, defrost: false, dhw: false, running: false, pumpOn: true };

describe('pumpStateKind priority', () => {
  it('defrost beats hot water and running', () => {
    expect(pumpStateKind({ ...base, defrost: true, dhw: true, running: true })).toBe('defrost');
  });
  it('hot water beats running', () => {
    expect(pumpStateKind({ ...base, dhw: true, running: true })).toBe('dhw');
  });
  it('running beats idle', () => {
    expect(pumpStateKind({ ...base, running: true })).toBe('running');
  });
  it('idle when the pump is on without compressor', () => {
    expect(pumpStateKind(base)).toBe('idle');
  });
  it('off only when nothing else applies', () => {
    expect(pumpStateKind({ ...base, running: null, pumpOn: false })).toBe('off');
    expect(pumpStateKind({ ...base, running: true, pumpOn: false })).toBe('running');
  });
  it('offline wins over everything and no data is unknown', () => {
    expect(pumpStateKind({ ...base, alive: false, defrost: true })).toBe('offline');
    expect(
      pumpStateKind({ alive: true, defrost: null, dhw: null, running: null, pumpOn: null }),
    ).toBe('unknown');
  });
});

describe('pumpStateOf', () => {
  const signal = (value: number) => ({ value, unit: null, label: null, age: 1, fresh: true });
  const snapshot = (derived: Record<string, boolean>, hz: number, quiet: number): Snapshot =>
    ({
      at: '2026-11-15T10:00:00Z',
      heishamon: { alive: true, last_heartbeat_age: 1, lwt: 'Online' },
      links: {},
      signals: {
        'main/Compressor_Freq': signal(hz),
        'main/Quiet_Mode_Level': signal(quiet),
        'main/Heatpump_State': signal(1),
      },
      derived: Object.fromEntries(
        Object.entries(derived).map(([key, value]) => [key, { value, reason: null }]),
      ),
    }) as unknown as Snapshot;

  it('reads state, frequency and quiet from the snapshot', () => {
    const state = pumpStateOf(snapshot({ compressor_running: true, dhw_active: true }, 38, 2));
    expect(state).toEqual({ kind: 'dhw', frequencyHz: 38, quiet: true });
  });
  it('is unknown without a snapshot', () => {
    expect(pumpStateOf(null).kind).toBe('unknown');
  });
});
