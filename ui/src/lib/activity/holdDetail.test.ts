import { describe, expect, it } from 'vitest';
import { holdEnd, holdForensics, settingUnit } from './holdDetail';

const DETAIL = {
  setting: 'water_setpoint',
  signal: 'main/Z1_Water_Target_Temp',
  register: 'setcurves_target_high',
  ovenbird_value: 33,
  seen_value: 31,
  seen_since: '2026-11-18T19:42:00Z',
  pump_keeps: 31,
  hold_until: '2026-11-18T20:43:00Z',
  at_hold_end: 'write_again',
  controller_wants: 33,
};

describe('holdForensics', () => {
  it('reads the structured detail of a foreign-writer hold', () => {
    const facts = holdForensics(DETAIL);
    expect(facts).toMatchObject({
      setting: 'water_setpoint',
      register: 'setcurves_target_high',
      ovenbirdValue: 33,
      seenValue: 31,
      pumpKeeps: 31,
      atHoldEnd: 'write_again',
      correction: null,
    });
  });

  it('is null for an older service without forensics', () => {
    expect(holdForensics(null)).toBeNull();
    expect(holdForensics({})).toBeNull();
    expect(holdForensics({ reason: 'foreign_writer' })).toBeNull();
  });

  it('drops values of the wrong type and unknown end actions', () => {
    const facts = holdForensics({ ...DETAIL, ovenbird_value: '33', at_hold_end: 'explode' });
    expect(facts?.ovenbirdValue).toBeNull();
    expect(facts?.atHoldEnd).toBeNull();
  });
});

describe('settingUnit and holdEnd', () => {
  it('shows °C only for the water setpoint', () => {
    expect(settingUnit('water_setpoint')).toBe(' °C');
    expect(settingUnit('quiet_mode')).toBe('');
    expect(settingUnit(null)).toBe('');
  });

  it('lets a latched hold always wait for a release', () => {
    const facts = holdForensics(DETAIL);
    expect(facts && holdEnd(facts, false)).toBe('write_again');
    expect(facts && holdEnd(facts, true)).toBe('await_release');
  });
});
