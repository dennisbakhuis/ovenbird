import { describe, expect, it } from 'vitest';
import {
  defaultStep,
  dhwAt,
  makeHistory,
  makeSnapshot,
  pumpStateAt,
  quietLevelAt,
} from '$mock/fixtures';
import { parseScenario, scenarioNow } from '$mock/scenario';

const HOUR = 3_600_000;
const now = new Date(2026, 10, 15, 14, 0).getTime();

describe('mock history', () => {
  it('serves 7 days of power, defrost, valve and quiet level at 15 min', () => {
    const ids = [
      'main/Heat_Power_Consumption',
      'main/Heat_Power_Production',
      'main/Defrosting_State',
      'main/ThreeWay_Valve_State',
      'main/Quiet_Mode_Level',
      'main/Compressor_Freq',
    ];
    const history = makeHistory(ids, now - 7 * 24 * HOUR, now, 900);
    expect(history.step).toBe(900);
    for (const id of ids) expect(history.series[id]?.points.length).toBe(7 * 96 + 1);
    const values = (id: string) => history.series[id]?.points.map(([, v]) => v as number) ?? [];
    expect(Math.max(...values('main/Defrosting_State'))).toBe(1);
    expect(Math.max(...values('main/ThreeWay_Valve_State'))).toBe(1);
    expect(new Set(values('main/Quiet_Mode_Level'))).toEqual(new Set([0, 2]));
    expect(Math.min(...values('main/Heat_Power_Consumption'))).toBeGreaterThanOrEqual(0);
  });

  it('aligns buckets to the step and picks the default step like the service', () => {
    const history = makeHistory(['main/Outside_Temp'], now - 3 * HOUR + 1234, now, 3600);
    const first = Date.parse(history.series['main/Outside_Temp']?.points[0]?.[0] ?? '');
    expect(first % (3600 * 1000)).toBe(0);
    expect(defaultStep(now - 24 * HOUR, now)).toBe(60);
    expect(defaultStep(now - 7 * 24 * HOUR, now)).toBe(900);
    expect(defaultStep(now - 90 * 24 * HOUR, now)).toBe(3600);
    expect(makeHistory(['nope'], now - HOUR, now, 60).series).toEqual({});
  });

  it('runs hot water in the morning and quiet mode at night', () => {
    expect(dhwAt(new Date(2026, 10, 15, 6, 45).getTime())).toBe(true);
    expect(dhwAt(new Date(2026, 10, 15, 12, 0).getTime())).toBe(false);
    expect(quietLevelAt(new Date(2026, 10, 15, 23, 0).getTime())).toBe(2);
    expect(quietLevelAt(new Date(2026, 10, 15, 12, 0).getTime())).toBe(0);
  });

  it('keeps power and temperatures coherent per phase', () => {
    const dhw = pumpStateAt(now, { phase: 'dhw' });
    expect(dhw.valve).toBe(1);
    const defrost = pumpStateAt(now, { phase: 'defrost' });
    expect(defrost.heatW).toBe(0);
    expect(defrost.inlet).toBeGreaterThan(defrost.outlet);
    const idle = pumpStateAt(now, { phase: 'idle' });
    expect(idle.hz).toBe(0);
    const heating = pumpStateAt(now, { phase: 'heating', quiet: true });
    expect(heating.hz).toBeLessThanOrEqual(32);
    expect(heating.heatW / heating.electricW).toBeGreaterThan(2.5);
  });
});

describe('mock scenarios', () => {
  it('parses the cookie', () => {
    expect(parseScenario('a=1; ovenbird_mock=pump:defrost.weather:stale.bogus:x')).toEqual({
      pump: 'defrost',
      weather: 'stale',
    });
    expect(parseScenario('ovenbird_mock=pump:boiling')).toEqual({});
    expect(parseScenario(undefined)).toEqual({});
  });

  it('shifts the service clock with the clock cookie', () => {
    const scenario = parseScenario('ovenbird_clock=90; ovenbird_mock=clock:behind');
    expect(scenario).toEqual({ clock: 'behind', shiftMin: 90 });
    expect(scenarioNow(scenario, 4 * 86_400_000)).toBe(-90 * 60_000);
    expect(parseScenario('ovenbird_clock=-5')).toEqual({});
    expect(parseScenario('ovenbird_clock=1441')).toEqual({});
    expect(scenarioNow(parseScenario('ovenbird_clock=0'), 1000)).toBe(1000);
  });

  it('forces the snapshot and recent history', () => {
    const snapshot = makeSnapshot(now, { pump: 'defrost', room: 'stale' });
    expect(snapshot.derived['defrost_active']?.value).toBe(true);
    expect(snapshot.signals['main/Defrosting_State']?.value).toBe(1);
    expect(snapshot.signals['ha/sensor.living_room_temperature']?.fresh).toBe(false);
    const history = makeHistory(['main/Defrosting_State'], now - HOUR, now, 60, {
      pump: 'defrost',
    });
    expect(history.series['main/Defrosting_State']?.points.at(-1)?.[1]).toBe(1);
    expect(makeSnapshot(now, { pump: 'dhw' }).derived['heat_delivered_w']?.value).toBeNull();
  });
});
