import { describe, expect, it } from 'vitest';
import { deiceModeOf, pumpStateKind, pumpStateOf } from './pumpState';
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
    expect(state).toEqual({ kind: 'dhw', frequencyHz: 38, quiet: true, deice: null });
  });
  it('carries the deice mode of a running defrost only', () => {
    const defrosting = {
      ...snapshot({ defrost_active: true, compressor_running: true }, 86, 0),
      defrost: {
        active: true,
        mode: 2,
        since: '2026-11-15T09:57:00Z',
        inlet_at_start_c: 25.5,
        outside_at_start_c: -1,
        max_s: 2100,
      },
    } as Snapshot;
    expect(pumpStateOf(defrosting)).toMatchObject({ kind: 'defrost', deice: 2 });
    expect(deiceModeOf(defrosting)).toBe(2);
    const ended = { ...defrosting, defrost: { ...defrosting.defrost, active: false } };
    expect(deiceModeOf(ended)).toBeNull();
    const unknown = { ...defrosting, defrost: { ...defrosting.defrost, mode: null } };
    expect(pumpStateOf(unknown).deice).toBeNull();
    const older = snapshot({ defrost_active: true }, 86, 0);
    expect(pumpStateOf(older)).toMatchObject({ kind: 'defrost', deice: null });
  });

  it('is unknown without a snapshot', () => {
    expect(pumpStateOf(null).kind).toBe('unknown');
  });
});
