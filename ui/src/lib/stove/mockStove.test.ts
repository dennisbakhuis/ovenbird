import { describe, expect, it } from 'vitest';
import { configDoc, initialConfigState } from '$mock/config';
import { inWindow, stoveMock, stoveStatus } from '$mock/plugin';
import { parseScenario, scenarioKey } from '$mock/scenario';

const cookie = (value: string) => `ovenbird_mock=${value}`;
const NOW = Date.parse('2026-11-18T19:00:00Z');
const doc = configDoc(initialConfigState(NOW), false);

describe('mock wood stove', () => {
  it('is enabled but idle by default and off with stove:disabled', () => {
    const idle = stoveStatus(stoveMock(parseScenario(cookie('')), null, NOW, doc), null, NOW);
    expect(idle).toMatchObject({ enabled: true, active: false });
    const off = stoveMock(parseScenario(cookie('stove:disabled')), null, NOW, doc);
    expect(off.enabled).toBe(false);
  });

  it('runs an automatic and a manual episode under stove:active and stove:manual', () => {
    const auto = stoveStatus(
      stoveMock(parseScenario(cookie('stove:active')), null, NOW, doc),
      null,
      NOW,
    );
    expect(auto).toMatchObject({ active: true, source: 'auto' });
    const manual = stoveStatus(
      stoveMock(parseScenario(cookie('stove:manual')), null, NOW, doc),
      null,
      NOW,
    );
    expect(manual).toMatchObject({ active: true, source: 'manual', trigger: 'manual' });
  });

  it('lets a manual request win and a stop leave the detection blocked', () => {
    const on = { on: true, untilMs: NOW + 2 * 3_600_000, atMs: NOW, actor: 'admin' };
    const started = stoveStatus(stoveMock(parseScenario(cookie('')), on, NOW, doc), on, NOW);
    expect(started).toMatchObject({ active: true, source: 'manual' });
    const stop = { on: false, untilMs: null, atMs: NOW, actor: 'admin' };
    const stopped = stoveStatus(
      stoveMock(parseScenario(cookie('stove:active')), stop, NOW, doc),
      stop,
      NOW,
    );
    expect(stopped).toMatchObject({ active: false, blocked: true });
  });

  it('keys requests per scenario cookie and filters events by window', () => {
    expect(scenarioKey(cookie('tag:abc.stove:active'))).toBe('tag:abc.stove:active');
    const events = [{ at: '2026-11-18T10:00:00Z' }, { at: '2026-11-10T10:00:00Z' }];
    const shown = inWindow({ events }, NOW - 24 * 3_600_000, NOW);
    expect(shown.events).toHaveLength(1);
  });
});
