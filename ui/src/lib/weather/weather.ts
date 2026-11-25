import type { ForecastPoint, WeatherPoint, WeatherResponse } from '$lib/core/types';

export interface GeoEnvironment {
  isSecureContext?: boolean;
  location?: { pathname: string };
  navigator?: { geolocation?: unknown };
}

/**
 * Round a coordinate to 0.01° (about 1 km) before it is stored or sent anywhere.
 */
export function roundCoordinate(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Whether the "Use my location" button may be offered: a secure context (https or localhost) or
 * the Home Assistant ingress path, and a geolocation API in the browser.
 */
export function canUseGeolocation(env: GeoEnvironment): boolean {
  if (!env.navigator?.geolocation) return false;
  const ingress = /\/api\/hassio_ingress\//.test(env.location?.pathname ?? '');
  return env.isSecureContext === true || ingress;
}

/**
 * Convert ISO-time/value pairs to (ms, value) chart points.
 */
export function toPoints(points: WeatherPoint[] | undefined): [number, number][] {
  return (points ?? []).flatMap(([at, value]): [number, number][] =>
    value === null ? [] : [[Date.parse(at), value]],
  );
}

/**
 * One column of a forecast point (1 temperature, 2 radiation, 3 cloud, 4 wind) as chart points.
 */
export function forecastColumn(points: ForecastPoint[] | undefined, column: 1 | 2 | 3 | 4) {
  return (points ?? []).flatMap((p): [number, number][] => {
    const value = p[column];
    return value === null ? [] : [[Date.parse(p[0]), value]];
  });
}

/**
 * Lowest and highest forecast temperature, or null without a forecast.
 */
export function forecastRange(points: ForecastPoint[] | undefined): [number, number] | null {
  const temps = (points ?? []).flatMap((p) => (p[1] === null ? [] : [p[1]]));
  if (temps.length === 0) return null;
  return [Math.min(...temps), Math.max(...temps)];
}

/**
 * The forecast points of a weather response, empty while the forecast is off.
 */
export function forecastOf(weather: WeatherResponse): ForecastPoint[] {
  return weather.enabled ? weather.forecast.points : [];
}

export type SkyKind = 'sunny' | 'partly' | 'cloudy';

export interface DayCard {
  start: number;
  min: number | null;
  max: number | null;
  meanCloud: number | null;
  sunHours: number;
  peakRadiation: number | null;
  maxWind: number | null;
  curveMin: number | null;
  curveMax: number | null;
  sky: SkyKind;
  hours: number;
}

const SUNNY_RADIATION_WM2 = 120;
const MIN_DAY_HOURS = 6;

function localDayStart(ms: number): number {
  const date = new Date(ms);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

/**
 * Sky category from mean cloud cover (percent): below 35 sunny, below 75 partly cloudy.
 */
export function skyKind(meanCloud: number | null): SkyKind {
  if (meanCloud === null || meanCloud < 35) return 'sunny';
  return meanCloud < 75 ? 'partly' : 'cloudy';
}

const finite = (values: (number | null)[]): number[] =>
  values.filter((v): v is number => v !== null);

const extreme = (values: number[], pick: (...v: number[]) => number): number | null =>
  values.length === 0 ? null : pick(...values);

/**
 * Group hourly forecast points by local calendar day into cards (min/max, cloud, sun hours, wind,
 * curve water range). Days with fewer than six forecast hours are dropped; at most `limit` days.
 */
export function dayCards(
  forecast: ForecastPoint[] | undefined,
  curve: WeatherPoint[] | undefined,
  limit = 3,
): DayCard[] {
  const byDay = new Map<number, ForecastPoint[]>();
  for (const point of forecast ?? []) {
    const day = localDayStart(Date.parse(point[0]));
    byDay.set(day, [...(byDay.get(day) ?? []), point]);
  }
  const curveByDay = new Map<number, number[]>();
  for (const [at, value] of curve ?? []) {
    if (value === null) continue;
    const day = localDayStart(Date.parse(at));
    curveByDay.set(day, [...(curveByDay.get(day) ?? []), value]);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a - b)
    .filter(([, points]) => points.length >= MIN_DAY_HOURS)
    .slice(0, limit)
    .map(([start, points]) => {
      const temps = finite(points.map((p) => p[1]));
      const radiation = finite(points.map((p) => p[2]));
      const clouds = finite(points.map((p) => p[3]));
      const winds = finite(points.map((p) => p[4]));
      const curveValues = curveByDay.get(start) ?? [];
      const meanCloud =
        clouds.length === 0 ? null : clouds.reduce((a, b) => a + b, 0) / clouds.length;
      return {
        start,
        min: extreme(temps, Math.min),
        max: extreme(temps, Math.max),
        meanCloud,
        sunHours: radiation.filter((r) => r >= SUNNY_RADIATION_WM2).length,
        peakRadiation: extreme(radiation, Math.max),
        maxWind: extreme(winds, Math.max),
        curveMin: extreme(curveValues, Math.min),
        curveMax: extreme(curveValues, Math.max),
        sky: skyKind(meanCloud),
        hours: points.length,
      };
    });
}

/**
 * Whether an enabled weather response has nothing to show yet (first fetch still pending).
 */
export function isStarting(weather: WeatherResponse): boolean {
  return (
    weather.enabled &&
    weather.issued === null &&
    weather.forecast.points.length === 0 &&
    weather.measured.points.length === 0
  );
}
