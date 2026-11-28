import { describe, expect, it } from 'vitest';
import {
  awayProblem,
  awayUntil,
  defaultAwayEnd,
  localDate,
  nearestHours,
  nearestOffset,
  secondsLeft,
  signedOffset,
} from './manual';

describe('boost choices', () => {
  it('opens on the choice closest to the service default', () => {
    expect(nearestOffset(1)).toBe(1);
    expect(nearestOffset(0.5)).toBe(0.5);
    expect(nearestOffset(2)).toBe(1.5);
    expect(nearestOffset(null)).toBe(1);
    expect(nearestHours(7200)).toBe(2);
    expect(nearestHours(43_200)).toBe(4);
    expect(nearestHours(900)).toBe(1);
  });

  it('writes the offset with its sign', () => {
    expect(signedOffset(0.5, 'en')).toBe('+0.5');
    expect(signedOffset(-1, 'en')).toBe('−1');
    expect(signedOffset(1.5, 'nl')).toBe('+1,5');
  });

  it('counts the seconds left on the service clock', () => {
    const now = Date.parse('2026-12-01T10:00:00Z');
    expect(secondsLeft('2026-12-01T11:30:00Z', now)).toBe(5400);
    expect(secondsLeft('2026-12-01T09:00:00Z', now)).toBe(0);
    expect(secondsLeft(null, now)).toBeNull();
  });
});

describe('away form', () => {
  it('starts on the evening of the day after tomorrow', () => {
    const now = new Date(2026, 11, 1, 10, 0).getTime();
    expect(defaultAwayEnd(now)).toEqual({ date: '2026-12-03', time: '18:00' });
    expect(localDate(now)).toBe('2026-12-01');
  });

  it('turns a local date and time into an ISO moment', () => {
    expect(awayUntil('2026-12-03', '18:00')).toBe(new Date(2026, 11, 3, 18, 0).toISOString());
    expect(awayUntil('', '18:00')).toBeNull();
    expect(awayUntil('2026-12-03', '')).toBeNull();
  });

  it('refuses an end inside the lead or past 60 days', () => {
    const now = Date.parse('2026-12-01T10:00:00Z');
    const lead = 6 * 3600;
    expect(awayProblem(now + 5 * 3600_000, now, lead)).toBe('too_soon');
    expect(awayProblem(now + 7 * 3600_000, now, lead)).toBeNull();
    expect(awayProblem(now + 61 * 86_400_000, now, lead)).toBe('too_far');
  });
});
