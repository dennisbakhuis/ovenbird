import { describe, expect, it } from 'vitest';
import {
  clockNow,
  dayOffset,
  formatDateTime,
  formatDay,
  setClock,
  formatAge,
  formatDuration,
  formatWithUnit,
  timeLocale,
  UNIT_SPACE,
} from './format';

describe('timeLocale', () => {
  it('uses Dutch with the browser region or nl-NL', () => {
    expect(timeLocale('nl', ['nl-BE', 'en'], 'Europe/Brussels')).toBe('nl-BE');
    expect(timeLocale('nl', ['en-US'], 'America/New_York')).toBe('nl-NL');
  });

  it('keeps an English region other than the US', () => {
    expect(timeLocale('en', ['en-AU'], 'Australia/Sydney')).toBe('en-AU');
    expect(timeLocale('en', ['nl-NL', 'en-GB'], 'Europe/Amsterdam')).toBe('en-GB');
  });

  it('uses 24-hour English outside the Americas', () => {
    expect(timeLocale('en', ['en-US', 'nl'], 'Europe/Amsterdam')).toBe('en-GB');
    expect(timeLocale('en', ['en'], 'Europe/London')).toBe('en-GB');
    expect(timeLocale('en', ['en-US'], 'America/Chicago')).toBe('en-US');
    expect(timeLocale('en', [], 'Pacific/Honolulu')).toBe('en-US');
  });

  it('passes full tags through', () => {
    expect(timeLocale('de-DE', ['en-US'], 'America/Chicago')).toBe('de-DE');
    expect(timeLocale(undefined)).toBeUndefined();
  });
});

describe('dates and times', () => {
  const now = new Date(2026, 10, 15, 14, 30).getTime();
  const at = (day: number, hour: number, minute = 0) =>
    new Date(2026, 10, day, hour, minute).toISOString();

  it('counts calendar days', () => {
    expect(dayOffset(Date.parse(at(15, 0, 1)), now)).toBe(0);
    expect(dayOffset(Date.parse(at(14, 23, 59)), now)).toBe(-1);
    expect(dayOffset(Date.parse(at(16, 6)), now)).toBe(1);
  });

  it('says today, yesterday and tomorrow in the UI language', () => {
    expect(formatDateTime(at(15, 14, 22), 'nl', now)).toBe('vandaag 14:22');
    expect(formatDateTime(at(14, 8, 18), 'nl', now)).toBe('gisteren 08:18');
    expect(formatDateTime(at(16, 6), 'nl', now)).toBe('morgen 06:00');
    expect(formatDateTime(at(15, 14, 22), 'en', now)).toMatch(/^today (14:22|2:22 PM)$/);
  });

  it('reads "today" against the clock set with setClock', () => {
    setClock(() => now);
    try {
      expect(clockNow()).toBe(now);
      expect(formatDateTime(at(15, 14, 22), 'nl')).toBe('vandaag 14:22');
    } finally {
      setClock(() => Date.now());
    }
  });

  it('falls back to day and month further away', () => {
    expect(formatDateTime(at(12, 9, 5), 'nl', now)).toMatch(/12 nov/);
    expect(formatDateTime(at(12, 9, 5), 'nl', now)).toMatch(/09:05/);
    expect(formatDateTime(null, 'nl')).toBe('–');
  });

  it('labels days', () => {
    expect(formatDay(at(15, 3), 'en', now)).toBe('Today');
    expect(formatDay(at(16, 3), 'nl', now)).toBe('Morgen');
    expect(formatDay(at(18, 3), 'en-GB', now)).toMatch(/Wed/);
  });
});

describe('values', () => {
  it('formats durations with two units at most', () => {
    expect(formatDuration(45)).toBe('45 s');
    expect(formatDuration(22 * 60)).toBe('22 min');
    expect(formatDuration(80 * 60)).toBe('1 h 20 min');
    expect(formatDuration(3 * 3600)).toBe('3 h');
    expect(formatDuration(51 * 3600)).toBe('2 d 3 h');
    expect(formatDuration(null)).toBe('–');
    expect(formatDuration(80 * 60, 'nl')).toBe('1 u 20 min');
    expect(formatDuration(51 * 3600, 'nl')).toBe('2 d 3 u');
    expect(formatAge(2 * 3600, 'nl')).toBe('2 u');
    expect(formatAge(2 * 3600, 'en')).toBe('2 h');
  });

  it('joins value and unit with a narrow space', () => {
    expect(formatWithUnit(21.24, '°C', 1, 'en')).toBe(`21.2${UNIT_SPACE}°C`);
    expect(formatWithUnit(4, null)).toBe('4');
    expect(formatWithUnit(Number.NaN, 'K')).toBe('–');
  });
});
