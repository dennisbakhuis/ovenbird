import { describe, expect, it } from 'vitest';
import { copEstimate, runStats } from '$lib/pump/pumpStats';
import type { ForecastPoint } from '$lib/core/types';
import { canUseGeolocation, dayCards, roundCoordinate, skyKind } from './weather';

describe('weather helpers', () => {
  it('rounds coordinates to 0.01 degrees', () => {
    expect(roundCoordinate(52.0949)).toBe(52.09);
    expect(roundCoordinate(5.126)).toBe(5.13);
  });

  it('offers geolocation only in a secure context or ingress', () => {
    const nav = { geolocation: {} };
    expect(
      canUseGeolocation({ isSecureContext: false, location: { pathname: '/' }, navigator: nav }),
    ).toBe(false);
    expect(
      canUseGeolocation({ isSecureContext: true, location: { pathname: '/' }, navigator: nav }),
    ).toBe(true);
    expect(
      canUseGeolocation({
        isSecureContext: false,
        location: { pathname: '/api/hassio_ingress/abc/' },
        navigator: nav,
      }),
    ).toBe(true);
    expect(
      canUseGeolocation({ isSecureContext: true, location: { pathname: '/' }, navigator: {} }),
    ).toBe(false);
  });
});

describe('pump stats', () => {
  const at = (m: number) => new Date(m * 60_000).toISOString();
  it('counts starts, complete runs and defrosts', () => {
    const freq = [0, 30, 30, 0, 0, 40, 40, 40, 0, 35].map((v, i) => [at(i), v] as [string, number]);
    const defrost = [0, 0, 1, 1, 0, 0, 1, 0, 0, 0].map((v, i) => [at(i), v] as [string, number]);
    const s = runStats(freq, defrost);
    expect(s.starts).toBe(3);
    expect(s.runsS).toEqual([120, 180]);
    expect(s.defrosts).toBe(2);
  });
  it('estimates COP only with power', () => {
    expect(copEstimate(7600, 1900)).toBe(4);
    expect(copEstimate(7600, 0)).toBeNull();
  });
});

describe('dayCards', () => {
  const hourly = (start: string, count: number, make: (h: number) => ForecastPoint[1][]) =>
    Array.from({ length: count }, (_, h): ForecastPoint => {
      const at = new Date(new Date(start).getTime() + h * 3_600_000).toISOString();
      const [temp, radiation, cloud, wind] = make(h) as [number, number, number, number];
      return [at, temp, radiation, cloud, wind];
    });

  it('groups by local day with min, max, sun hours and wind', () => {
    const points = hourly('2026-11-16T00:00:00', 24, (h) => [
      h,
      h >= 10 && h < 14 ? 200 : 0,
      20,
      h % 5,
    ]);
    const [day] = dayCards(points, []);
    expect(day?.min).toBe(0);
    expect(day?.max).toBe(23);
    expect(day?.sunHours).toBe(4);
    expect(day?.peakRadiation).toBe(200);
    expect(day?.maxWind).toBe(4);
    expect(day?.sky).toBe('sunny');
    expect(day?.hours).toBe(24);
  });

  it('drops days with fewer than six hours and ignores nulls', () => {
    const short = hourly('2026-11-16T00:00:00', 4, () => [1, 0, 10, 1]);
    expect(dayCards(short, [])).toEqual([]);
    const withNulls = hourly('2026-11-17T00:00:00', 8, () => [2, 0, 90, 1]);
    withNulls[0] = [withNulls[0]![0], null, null, null, null];
    const [day] = dayCards(withNulls, []);
    expect(day?.min).toBe(2);
    expect(day?.sky).toBe('cloudy');
  });

  it('adds the curve water range of the same day and limits the count', () => {
    const points = hourly('2026-11-16T00:00:00', 24 * 5, () => [1, 0, 50, 2]);
    const curve: [string, number | null][] = [
      ['2026-11-16T10:00:00', 31.5],
      ['2026-11-16T12:00:00', 33.1],
      ['2026-11-16T13:00:00', null],
    ];
    const days = dayCards(points, curve);
    expect(days).toHaveLength(3);
    expect(days[0]?.curveMin).toBe(31.5);
    expect(days[0]?.curveMax).toBe(33.1);
    expect(days[1]?.curveMin).toBeNull();
  });

  it('classifies the sky from cloud cover', () => {
    expect(skyKind(null)).toBe('sunny');
    expect(skyKind(34)).toBe('sunny');
    expect(skyKind(50)).toBe('partly');
    expect(skyKind(75)).toBe('cloudy');
  });
});
