import { describe, expect, it } from 'vitest';
import type { ConfigDoc, HaTestResult, SignalCandidate } from '$lib/core/types';
import { haHost, haSignals, haUrlProblem, haVerdict, sameDeviceFirst } from './ha';

const candidate = (signal: string, device?: string): SignalCandidate => ({
  signal,
  name: null,
  unit: null,
  value: null,
  held_s: null,
  source: 'ha',
  pump_mirror: false,
  ...(device ? { device_id: device } : {}),
});

const field = (value: unknown) => ({
  value,
  source: 'store' as const,
  locked: false,
  stored: value,
  default: null,
});

const result = (over: Partial<HaTestResult>): HaTestResult => ({
  ok: false,
  url: 'http://ha:8123',
  reachable: true,
  auth_ok: true,
  ha_version: '2026.11.1',
  latency_ms: 12,
  temperature_unit: '°C',
  metric: true,
  entities: [],
  error: null,
  error_code: null,
  ...over,
});

describe('haUrlProblem', () => {
  it.each([
    ['', null],
    ['http://192.0.2.10:8123', null],
    ['https://ha.example.org/prefix', null],
    ['wss://ha.example.org/api/websocket', null],
    ['ftp://ha', 'scheme'],
    ['ha.local:8123', 'scheme'],
    ['homeassistant', 'scheme'],
    ['http://me:pw@ha:8123', 'credentials'],
    ['http://ha:8123/?x=1', 'query'],
    ['http://ha:8123/#top', 'query'],
  ])('%s', (url, problem) => {
    expect(haUrlProblem(url)).toBe(problem);
  });
});

describe('haSignals', () => {
  it('collects the ha/ signals of every signal field once', () => {
    const config = {
      fields: {
        control_room_signal: field('ha/climate.living#current_temperature'),
        control_room_liveness_signals: field(['ha/sensor.hum', 'room_temperature']),
        control_room_crosscheck_signal: field('main/Room_Thermostat_Temp'),
        control_stove_reference_signal: field('ha/sensor.hum'),
      },
    } as unknown as ConfigDoc;
    expect(haSignals(config)).toEqual(['ha/climate.living#current_temperature', 'ha/sensor.hum']);
    expect(haSignals(null)).toEqual([]);
  });
});

describe('sameDeviceFirst', () => {
  const room = [candidate('ha/sensor.t', 'dev1'), candidate('ha/sensor.u')];
  const liveness = [
    candidate('ha/sensor.a', 'dev2'),
    candidate('ha/sensor.b', 'dev1'),
    candidate('ha/sensor.t', 'dev1'),
    candidate('ha/sensor.c'),
  ];

  it('puts the room sensor device first', () => {
    expect(sameDeviceFirst(liveness, room, 'ha/sensor.t').map((c) => c.signal)).toEqual([
      'ha/sensor.b',
      'ha/sensor.a',
      'ha/sensor.t',
      'ha/sensor.c',
    ]);
  });

  it('keeps the order without device facts', () => {
    expect(sameDeviceFirst(liveness, room, 'ha/sensor.u')).toBe(liveness);
    expect(sameDeviceFirst(liveness, room, null)).toBe(liveness);
  });
});

describe('haVerdict', () => {
  it('tells success, entity problems and failures apart', () => {
    expect(haVerdict(result({ ok: true }))).toBe('ok');
    expect(haVerdict(result({}))).toBe('entities');
    expect(haVerdict(result({ auth_ok: false, error_code: 'auth_failed', error: 'x' }))).toBe(
      'failed',
    );
    expect(haVerdict(result({ reachable: false, error_code: 'unreachable', error: 'x' }))).toBe(
      'failed',
    );
  });
});

describe('haHost', () => {
  it('shows host and port', () => {
    expect(haHost('http://192.0.2.10:8123')).toBe('192.0.2.10:8123');
    expect(haHost('https://ha.example.org/x')).toBe('ha.example.org');
    expect(haHost(null)).toBeNull();
    expect(haHost('not a url')).toBe('not a url');
  });
});
