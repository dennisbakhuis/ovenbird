import { describe, expect, it } from 'vitest';
import type { HouseInsight } from './house';
import { differsByFactor, toldRows } from './told';

const house = (told: object | undefined) =>
  ({
    ua: { w_per_k: 240, interval_90: [230, 250] },
    solar_aperture_m2: { value: 6.2, interval_90: [5.4, 7.1] },
    internal_gains_w: { value: 318, interval_90: [262, 381] },
    provenance: { told },
  }) as unknown as HouseInsight;

describe('differsByFactor', () => {
  it('compares both ways around the factor 1.5', () => {
    expect(differsByFactor(340, 240)).toBe(false);
    expect(differsByFactor(400, 240)).toBe(true);
    expect(differsByFactor(100, 240)).toBe(true);
    expect(differsByFactor(240, 240)).toBe(false);
  });
});

describe('toldRows', () => {
  it('pairs what was told with what was measured and flags the big gaps', () => {
    const rows = toldRows(
      house({ ua_w_per_k: 340, solar_aperture_m2: 2.5, internal_gain_w: null }),
    );
    expect(rows.map((r) => [r.id, r.differs])).toEqual([
      ['ua', false],
      ['solar', true],
    ]);
    expect(rows[0]?.interval).toEqual([230, 250]);
  });

  it('is empty without told values', () => {
    expect(toldRows(house(undefined))).toEqual([]);
  });
});
