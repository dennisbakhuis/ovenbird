import { describe, expect, it } from 'vitest';
import { backoffDelay, wsUrl } from './backoff';
import { computeDomain, linePath, niceTicks, numericPoints } from './chart';
import { roomTrust, roomView, statusLine } from './derive';
import { effectiveAge, formatAge, formatSignalValue } from './format';
import { detectLanguage, dictionaries, translate } from '$lib/i18n';
import { parseMessage } from './live.svelte';
import { parseRoute } from './location';
import { initialState, makeControl, makeDecision } from '$mock/decisions';
import { health, makeSnapshot } from '$mock/fixtures';

const kw = (w: number) => (w / 1000).toFixed(1);

describe('format', () => {
  it('formats ages', () => {
    expect(formatAge(null)).toBe('–');
    expect(formatAge(12.4)).toBe('12 s');
    expect(formatAge(300)).toBe('5 min');
    expect(formatAge(7300)).toBe('2 h');
    expect(formatAge(200000)).toBe('2 d');
  });

  it('extends age by time since receipt', () => {
    expect(effectiveAge(10, 1000, 6000)).toBe(15);
    expect(effectiveAge(10, 6000, 1000)).toBe(10);
  });

  it('formats signal values', () => {
    const base = {
      unit: null,
      label: null,
      age: 1,
      held: null,
      max_age: 330,
      alive_by: null,
      fresh: true,
      source: 'heishamon' as const,
      retained: false,
      reason: null,
    };
    expect(formatSignalValue({ ...base, value: 3, unit: '°C' }, 'en')).toBe('3 °C');
    expect(formatSignalValue({ ...base, value: 0, label: 'Heat' })).toBe('Heat (0)');
    expect(formatSignalValue({ ...base, value: null })).toBe('–');
  });
});

describe('i18n', () => {
  it('has the same keys in all languages', () => {
    expect(Object.keys(dictionaries.nl).sort()).toEqual(Object.keys(dictionaries.en).sort());
  });

  it('detects language', () => {
    expect(detectLanguage(['de-DE', 'nl-NL'])).toBe('nl');
    expect(detectLanguage(['fr'])).toBe('en');
  });

  it('substitutes params', () => {
    expect(translate('en', 'statusRunningHeat', { kw: '8.4' })).toBe(
      'Compressor running — 8.4 kW heat',
    );
  });
});

describe('backoff and urls', () => {
  it('grows and caps', () => {
    const full = () => 1;
    expect(backoffDelay(0, full)).toBe(1000);
    expect(backoffDelay(3, full)).toBe(8000);
    expect(backoffDelay(20, full)).toBe(30000);
    expect(backoffDelay(0, () => 0)).toBe(500);
  });

  it('derives the ws url keeping the path prefix', () => {
    expect(
      wsUrl({ protocol: 'https:', host: 'h.local', pathname: '/api/hassio_ingress/abc/' }),
    ).toBe('wss://h.local/api/hassio_ingress/abc/api/v1/ws');
    expect(wsUrl({ protocol: 'http:', host: 'x:8080', pathname: '/index.html' })).toBe(
      'ws://x:8080/api/v1/ws',
    );
  });
});

describe('derive', () => {
  const snapshot = makeSnapshot(Date.parse('2026-11-14T18:00:00Z'));

  it('takes the room from the control status, not from signal names', () => {
    const control = makeControl(Date.parse('2026-11-14T18:00:00Z'), initialState());
    const view = roomView(snapshot, control, null);
    expect(view.signal).toBe('ha/sensor.living_room_temperature');
    expect(view.value).toBe(
      snapshot.signals['ha/sensor.living_room_temperature']?.value ?? Number.NaN,
    );
  });

  it('uses the configured room signal even when it is an MQTT input id', () => {
    const decision = makeDecision(Date.parse('2026-11-14T18:00:00Z'), Date.now());
    const control = makeControl(0, initialState());
    if (control.room) control.room.signal = 'room_temperature';
    const view = roomView(snapshot, control, decision);
    expect(view.signal).toBe('room_temperature');
    expect(view.value).toBe(control.room?.value);
    expect(view.target).toBe(21.0);
  });

  it('falls back to the room input of the decision when the status has no room', () => {
    const decision = makeDecision(Date.parse('2026-11-14T18:00:00Z'), Date.now());
    const control = makeControl(0, initialState());
    control.room = null;
    const view = roomView(snapshot, control, decision);
    expect(view.signal).toBeNull();
    expect(view.value).toBe(decision.record.inputs_used.find((i) => i.source === 'room')?.value);
    expect(roomView(null, null, null).value).toBeNull();
  });

  it('builds the status line', () => {
    expect(statusLine(snapshot, kw)).toEqual({ key: 'statusRunningHeat', params: { kw: '8.4' } });
    const defrost = structuredClone(snapshot);
    defrost.derived['defrost_active'] = { value: true, reason: null };
    expect(statusLine(defrost, kw).key).toBe('statusDefrost');
    const idle = structuredClone(snapshot);
    idle.derived['compressor_running'] = { value: false, reason: null };
    expect(statusLine(idle, kw).key).toBe('statusIdle');
    const unknown = structuredClone(snapshot);
    unknown.derived['compressor_running'] = { value: null, reason: 'stale' };
    expect(statusLine(unknown, kw).key).toBe('statusUnknown');
    const offline = structuredClone(snapshot);
    offline.heishamon.alive = false;
    expect(statusLine(offline, kw).key).toBe('statusOffline');
    expect(statusLine(null, kw).key).toBe('statusUnknown');
  });
});

describe('chart helpers', () => {
  it('keeps numeric points only', () => {
    expect(
      numericPoints([
        ['2026-11-14T00:00:00Z', 1],
        ['2026-11-14T00:01:00Z', null],
        ['bad', 2],
      ]),
    ).toEqual([[Date.parse('2026-11-14T00:00:00Z'), 1]]);
  });

  it('computes a padded domain and null when empty', () => {
    expect(
      computeDomain(
        [
          [
            [0, 2.5],
            [10, 7.2],
          ],
        ],
        0,
        10,
      ),
    ).toEqual({ tMin: 0, tMax: 10, vMin: 1, vMax: 9 });
    expect(computeDomain([], 0, 10)).toBeNull();
  });

  it('breaks lines at gaps', () => {
    const domain = { tMin: 0, tMax: 100, vMin: 0, vMax: 10 };
    const path = linePath(
      [
        [0, 0],
        [10, 5],
        [90, 10],
      ],
      domain,
      100,
      100,
      20,
    );
    expect(path.match(/M/g)).toHaveLength(2);
  });

  it('produces ticks', () => {
    expect(niceTicks(0, 20, 5)).toEqual([0, 5, 10, 15, 20]);
  });
});

describe('protocol parsing', () => {
  it('parses server messages', () => {
    expect(parseMessage(JSON.stringify({ type: 'health', data: health }))?.type).toBe('health');
    expect(parseMessage('nope')).toBeNull();
    expect(parseMessage(JSON.stringify({ type: 'other', data: {} }))).toBeNull();
    expect(parseMessage(5)).toBeNull();
  });

  it('parses routes', () => {
    expect(parseRoute('#/signals')).toBe('system');
    expect(parseRoute('#/health?x=1')).toBe('system');
    expect(parseRoute('#/nope')).toBe('home');
    expect(parseRoute('')).toBe('home');
  });
});

describe('roomTrust', () => {
  const control = (authority: number | null, plausible: boolean | null = null) => {
    const base = makeControl(0, initialState());
    return { ...base, room: base.room ? { ...base.room, authority, plausible } : null };
  };

  it('follows the cooling authority of the latest decision', () => {
    expect(roomTrust(control(1), null).trust).toBe('ok');
    expect(roomTrust(control(0.45), null)).toEqual({ trust: 'reduced', authority: 0.45 });
    expect(roomTrust(control(0), null).trust).toBe('untrusted');
    expect(roomTrust(control(null), null).trust).toBe('ok');
  });

  it('does not trust a value the cross-check disagrees with', () => {
    expect(roomTrust(control(1, false), null).trust).toBe('implausible');
  });
});
