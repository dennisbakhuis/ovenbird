import { describe, expect, it } from 'vitest';
import { dayshiftShown, phaseTone, plainReasons, shadowKind } from './dayshift';

describe('day shift helpers', () => {
  it('reads the direction of the offset', () => {
    expect(shadowKind({ offset_k: 0.25 })).toBe('up');
    expect(shadowKind({ offset_k: -0.5 })).toBe('down');
    expect(shadowKind({ offset_k: 0 })).toBe('none');
  });

  it('keeps guards out of the plain reasons', () => {
    expect(
      plainReasons({ reasons: ['outside_windows', 'forecast_stale'], guards: ['forecast_stale'] }),
    ).toEqual(['outside_windows']);
  });

  it('marks a blocked phase as a warning', () => {
    expect(phaseTone('blocked')).toBe('warn');
    expect(phaseTone('idle')).toBe('neutral');
  });

  it('is silent while switched off', () => {
    expect(dayshiftShown(null)).toBe(false);
    expect(dayshiftShown({ mode: 'off', configured: 'off' })).toBe(false);
    expect(dayshiftShown({ mode: 'shadow', configured: 'on' })).toBe(true);
  });
});
