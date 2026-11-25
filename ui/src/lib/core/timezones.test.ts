import { describe, expect, it } from 'vitest';
import { browserZone, clockIn, timeZones } from './timezones';

describe('timezones', () => {
  it('lists the zones sorted, with the current value and UTC included', () => {
    const zones = timeZones('Mars/Olympus');
    expect(zones).toContain('Mars/Olympus');
    expect(zones).toContain('UTC');
    expect([...zones].sort((a, b) => a.localeCompare(b))).toEqual(zones);
  });

  it('knows the browser zone', () => {
    expect(browserZone()).toBeTruthy();
  });

  it('formats the clock in a zone and refuses an unknown one', () => {
    const ms = Date.parse('2026-11-18T17:27:00Z');
    expect(clockIn(ms, 'Europe/Amsterdam', 'en')).toBe('18:27');
    expect(clockIn(ms, 'UTC', 'nl')).toBe('17:27');
    expect(clockIn(ms, 'Not/AZone', 'en')).toBeNull();
  });
});
