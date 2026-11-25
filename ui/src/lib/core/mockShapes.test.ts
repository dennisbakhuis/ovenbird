import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { initialConfigState, preview, signals } from '$mock/config';
import { initialPumpState, pumpSettings, writeSetting } from '$mock/pump';
import { makeWeather } from '$mock/weather';
import { ApiError, pumpRefusal, writePumpSetting } from './api';
import { vi } from 'vitest';

const real = (name: string): Record<string, unknown> =>
  JSON.parse(
    readFileSync(new URL(`../../../mock/fixtures/real/${name}.json`, import.meta.url), 'utf8'),
  );

const kind = (value: unknown) =>
  value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;

/**
 * Differences between a mock value and a recorded real one: key sets, JSON types (null matches
 * anything) and the shape of the first array element. Value-dependent keys are skipped.
 */
function diff(mock: unknown, actual: unknown, path = '$', skip: readonly string[] = []): string[] {
  if (mock === null || actual === null) return [];
  if (kind(mock) !== kind(actual)) return [`${path}: ${kind(mock)} vs ${kind(actual)}`];
  if (Array.isArray(mock) && Array.isArray(actual)) {
    if (mock.length === 0 || actual.length === 0) return [];
    return diff(mock[0], actual[0], `${path}[0]`, skip);
  }
  if (typeof mock === 'object' && typeof actual === 'object') {
    const a = mock as Record<string, unknown>;
    const b = actual as Record<string, unknown>;
    const out: string[] = [];
    for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
      const here = `${path}.${key}`;
      if (skip.includes(here)) continue;
      if (!(key in a)) out.push(`${here}: missing in the mock`);
      else if (!(key in b)) out.push(`${here}: not in the real response`);
      else out.push(...diff(a[key], b[key], here, skip));
    }
    return out;
  }
  return [];
}

const NOW = Date.parse('2026-11-15T12:00:00Z');
const CURVE = {
  points: [
    [-10, 45],
    [15, 25],
  ],
};

describe('mocks match the recorded real responses', () => {
  it('weather while off', () => {
    const mock = makeWeather(NOW, 24, 48, {
      enabled: false,
      source: 'ha_zone_home',
      latitude: null,
      longitude: null,
      curve: CURVE as never,
    });
    expect(diff(mock, real('weather-off'))).toEqual([]);
    expect(mock).toEqual(real('weather-off'));
  });

  it('weather while on', () => {
    const mock = makeWeather(NOW, 24, 48, {
      enabled: true,
      source: 'manual',
      latitude: 52.09,
      longitude: 5.12,
      curve: CURVE.points as never,
    });
    expect(diff(mock, real('weather-on'))).toEqual([]);
  });

  it('pump settings: every row, in the real order', () => {
    const mock = pumpSettings(initialPumpState(NOW), NOW, false);
    const actual = real('pump-settings') as unknown as typeof mock;
    expect(mock.settings.map((s) => s.id)).toEqual(actual.settings.map((s) => s.id));
    expect(mock.settings.map((s) => [s.id, s.signal, s.access, s.owner, s.unit])).toEqual(
      actual.settings.map((s) => [s.id, s.signal, s.access, s.owner, s.unit]),
    );
    const write = (list: typeof mock.settings) => list.filter((s) => s.access === 'write');
    expect(diff(write(mock.settings)[0], write(actual.settings)[0])).toEqual([]);
    const read = (list: typeof mock.settings) => list.find((s) => s.id === 'heating_mode');
    expect(diff(read(mock.settings), read(actual.settings))).toEqual([]);
    expect(diff({ ...mock, settings: [] }, { ...actual, settings: [] })).toEqual([]);
  });

  it('pump settings while paused and while a write is in flight', () => {
    const paused = pumpSettings(initialPumpState(NOW), NOW, true);
    expect(paused.refusals).toEqual(
      (real('pump-settings-paused') as { refusals: string[] }).refusals,
    );
    const state = initialPumpState(NOW);
    writeSetting(state, 'heat_delta', { value: 4, expect: 5, comment: 'test' }, NOW, false);
    const after = pumpSettings(state, NOW, false);
    const recorded = real('pump-settings-after-write') as unknown as typeof after;
    expect(after.refusals).toEqual(recorded.refusals);
    expect(after.writable).toBe(false);
    expect(diff(after.settings[0], recorded.settings[0])).toEqual([]);
  });

  it('pump write: 202 and refusals', () => {
    const state = initialPumpState(NOW);
    const accepted = writeSetting(
      state,
      'heat_delta',
      { value: 4, expect: 5, comment: 'test' },
      NOW,
      false,
    );
    const recorded = real('pump-write-accepted') as { status: number };
    expect(accepted.status).toBe(recorded.status);
    expect(diff(accepted.body, recorded, '$', ['$.status'])).toEqual([]);
    const body = accepted.body as { command: { kind: string; attempt: number; detail: string } };
    expect(body.command.kind).toBe('heat_delta');
    expect(body.command.attempt).toBe(0);
    expect(body.command.detail).toMatch(/^operator: admin from .*: heat_delta 5 → 4 \(test\)$/);

    const refused: [string, Record<string, unknown>, boolean, string][] = [
      ['pump-write-refused-out-of-range', { value: 11, expect: 5 }, false, 'heat_delta'],
      ['pump-write-refused-value-changed', { value: 4, expect: 6 }, false, 'heat_delta'],
      ['pump-write-refused-unknown', { value: 4, expect: 5 }, false, 'max_pump_duty'],
      ['pump-write-refused-not-publishing', { value: 4, expect: 5 }, true, 'heat_delta'],
    ];
    for (const [name, payload, paused, id] of refused) {
      const result = writeSetting(initialPumpState(NOW), id, payload, NOW, paused);
      const expected = real(name) as { status: number; detail: { code: string } };
      expect(result.status, name).toBe(expected.status);
      expect(diff(result.body, { detail: expected.detail }), name).toEqual([]);
      expect((result.body as { detail: { code: string } }).detail.code, name).toBe(
        expected.detail.code,
      );
    }
    const second = writeSetting(state, 'heat_delta', { value: 3, expect: 5 }, NOW, false);
    expect(second.status).toBe(409);
    expect((second.body as { detail: { code: string } }).detail.code).toBe('in_flight');
  });

  it('config signals', () => {
    const actual = real('config-signals') as unknown as typeof signals;
    expect(diff(signals, actual)).toEqual([]);
    for (const list of ['room', 'liveness', 'crosscheck'] as const)
      expect(diff(signals[list][0], actual[list][0], list)).toEqual([]);
  });

  it('config preview, valid and invalid', () => {
    const state = initialConfigState(NOW);
    const valid = preview(state, { control_comfort_c: 21.4 }, 24, NOW);
    const actual = real('config-preview');
    const skip = [
      '$.now.current',
      '$.now.candidate',
      '$.open_loop_run.from',
      '$.open_loop_run.to',
      '$.open_loop_run.summary.ladder',
      '$.open_loop_run.summary.binding',
    ];
    expect(diff(valid, actual, '$', skip)).toEqual([]);
    const recorded = (actual['now'] as { current: unknown }).current;
    expect(diff(valid.now?.current, recorded, '$', ['$.controller_state'])).toEqual([]);
    const invalid = preview(state, { control_comfort_c: 99 }, 24, NOW);
    expect(invalid.valid).toBe(false);
    expect('open_loop_run' in invalid).toBe(false);
    expect('now' in invalid).toBe(false);
    expect(Object.keys(invalid)).toEqual(Object.keys(real('config-preview-invalid')));
  });
});

describe('structured refusals', () => {
  it('are read from detail', async () => {
    const recorded = real('pump-write-refused-out-of-range') as { status: number; detail: unknown };
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(new Response(JSON.stringify({ detail: recorded.detail }), { status: 422 })),
      ),
    );
    const error = await writePumpSetting('heat_delta', { value: 11, expect: 5 }).catch(
      (e: unknown) => e,
    );
    vi.unstubAllGlobals();
    expect(error).toBeInstanceOf(ApiError);
    expect(pumpRefusal(error)).toEqual(recorded.detail);
    expect((error as ApiError).code).toBe('out_of_range');
    expect(pumpRefusal(new ApiError('x', 404, { detail: 'Not Found' }))).toBeNull();
    expect(pumpRefusal(new Error('x'))).toBeNull();
  });
});
