import type { HouseInsight, Interval } from './house';

export const DIFFERS_FACTOR = 1.5;

export type ToldId = 'ua' | 'solar' | 'gains';

export interface ToldRow {
  id: ToldId;
  told: number;
  measured: number;
  interval: Interval | null;
  differs: boolean;
  unit: string;
  digits: number;
}

/**
 * Whether two positive numbers differ by more than the factor in either direction.
 */
export function differsByFactor(a: number, b: number, factor = DIFFERS_FACTOR): boolean {
  if (a <= 0 || b <= 0) return a !== b;
  const ratio = a / b;
  return ratio > factor || ratio < 1 / factor;
}

/**
 * What the owner's answers imply next to what the model measured, for the heat loss, the solar
 * aperture and the net free heat; a row only where both numbers exist.
 */
export function toldRows(house: HouseInsight): ToldRow[] {
  const told = house.provenance.told;
  if (!told) return [];
  const candidates: [
    ToldId,
    number | null | undefined,
    number | undefined,
    Interval | null | undefined,
    string,
    number,
  ][] = [
    ['ua', told.ua_w_per_k, house.ua.w_per_k, house.ua.interval_90, 'W/K', 0],
    [
      'solar',
      told.solar_aperture_m2,
      house.solar_aperture_m2?.value,
      house.solar_aperture_m2?.interval_90,
      'm²',
      1,
    ],
    [
      'gains',
      told.internal_gain_w,
      house.internal_gains_w?.value,
      house.internal_gains_w?.interval_90,
      'W',
      0,
    ],
  ];
  const rows: ToldRow[] = [];
  for (const [id, toldValue, measured, interval, unit, digits] of candidates) {
    if (typeof toldValue !== 'number' || typeof measured !== 'number') continue;
    rows.push({
      id,
      told: toldValue,
      measured,
      interval: interval ?? null,
      differs: differsByFactor(toldValue, measured),
      unit,
      digits,
    });
  }
  return rows;
}
