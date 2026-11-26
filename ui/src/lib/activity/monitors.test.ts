import { describe, expect, it } from 'vitest';
import { alarmAction, monitorBar } from './monitors';

const monitor = {
  code: 'outlet_overshoot',
  severity: 'critical' as const,
  status: 'ok' as const,
  message: '',
  value: 30.8,
  since: null,
  limit: null,
  unit: null,
  direction: null,
};

describe('monitors', () => {
  it('has no bar without a limit and degrades silently', () => {
    expect(monitorBar(monitor)).toBeNull();
  });

  it('builds a bar when value and limit are known', () => {
    expect(monitorBar({ ...monitor, limit: 45, unit: '°C', direction: 'above' })).toEqual({
      value: 30.8,
      limit: 45,
      unit: '°C',
      direction: 'above',
    });
    expect(monitorBar({ ...monitor, value: 'x', limit: 45 })).toBeNull();
  });

  it('measures defrost_stuck by the time since it started', () => {
    const bar = monitorBar(
      {
        ...monitor,
        code: 'defrost_stuck',
        value: 1,
        since: '2026-11-15T12:00:00Z',
        limit: 1200,
        unit: 's',
      },
      Date.parse('2026-11-15T12:05:00Z'),
    );
    expect(bar?.value).toBe(300);
    expect(bar?.direction).toBe('above');
  });

  it('suggests where to look', () => {
    expect(alarmAction('foreign_writer')).toBe('holds');
    expect(alarmAction('room_sensor_silent')).toBe('room');
    expect(alarmAction('low_flow_defrost')).toBe('pump');
    expect(alarmAction('unknown_thing')).toBeNull();
  });
});
