import { describe, expect, it } from 'vitest';
import {
  freshness,
  humanizeId,
  isHotWaterSignal,
  isInternalSignal,
  proofAge,
  signalGroup,
  signalName,
} from './signalView';
import type { Signal } from './types';

const base: Signal = {
  value: 1,
  unit: null,
  label: null,
  age: 10,
  held: null,
  max_age: 330,
  alive_by: null,
  fresh: true,
  source: 'heishamon',
  retained: false,
  reason: null,
};

describe('signalView', () => {
  it('names signals for people, never by topic path', () => {
    const none = () => undefined;
    expect(signalName('room_temperature', 'climate_manager_capture/room_temp', none)).toBe(
      'Room temperature',
    );
    expect(signalName('ha/sensor.living_t', 'Living room', none)).toBe('Living room');
    expect(signalName('main/Room_Thermostat_Temp', null, none)).toBe('Room Thermostat Temp');
    const known = (key: string) => (key === 'sig_room_humidity' ? 'Room humidity' : undefined);
    expect(signalName('room_humidity', 'x/room_humidity', known)).toBe('Room humidity');
  });

  it('hides bridge bookkeeping', () => {
    expect(isInternalSignal('main/stats')).toBe(true);
    expect(isInternalSignal('stats')).toBe(true);
    expect(isInternalSignal('main/Outside_Temp')).toBe(false);
  });

  it('groups signals', () => {
    expect(signalGroup('main/Outside_Temp', base)).toBe('temperatures');
    expect(signalGroup('main/Pump_Flow', base)).toBe('pump');
    expect(signalGroup('main/Heat_Power_Consumption', base)).toBe('power');
    expect(signalGroup('main/Z1_Heat_Curve_Target_High_Temp', base)).toBe('settings');
    expect(signalGroup('main/Room_Thermostat_Temp', base)).toBe('room');
    expect(signalGroup('main/Room_Heater_State', base)).toBe('settings');
    expect(signalGroup('ha/sensor.x', { source: 'ha' })).toBe('room');
  });

  it('calls an on-change sensor held, not stale', () => {
    expect(freshness(base)).toBe('fresh');
    expect(freshness({ ...base, max_age: 86400, age: 10000 })).toBe('held');
    expect(freshness({ ...base, fresh: false, max_age: 86400 })).toBe('stale');
  });

  it('measures the proof of life from the alive_by signal', () => {
    const all = { beat: { ...base, age: 5 } };
    expect(proofAge({ ...base, age: 9000, alive_by: 'beat' }, all, 0, 0)).toBe(5);
    expect(proofAge({ ...base, age: 9000 }, all, 0, 2000)).toBe(9002);
  });

  it('humanizes ids', () => {
    expect(humanizeId('main/Heat_Power_Consumption')).toBe('Heat Power Consumption');
  });
});

describe('isHotWaterSignal', () => {
  it('picks the tank, its runs and its power, not the heating', () => {
    for (const id of [
      'main/DHW_Temp',
      'main/DHW_Target_Temp',
      'main/DHW_Installed',
      'main/Force_DHW_State',
      'main/DHW_Power_Production',
      'main/DHW_Power_Consumption',
      'main/Sterilization_State',
    ])
      expect(isHotWaterSignal(id), id).toBe(true);
    for (const id of [
      'main/ThreeWay_Valve_State',
      'main/Heat_Power_Production',
      'room_temperature',
    ])
      expect(isHotWaterSignal(id), id).toBe(false);
  });
});
