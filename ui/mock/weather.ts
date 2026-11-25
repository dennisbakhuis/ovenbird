import { curveWater, filterOutside, type Curve } from '../src/lib/core/curve.ts';
import type { ForecastPoint, WeatherPoint, WeatherResponse } from '../src/lib/core/types';
import { outsideAt } from './decisions.ts';

const HOUR = 3_600_000;
const iso = (ms: number) => new Date(ms).toISOString();
const round1 = (v: number) => Math.round(v * 10) / 10;

const cloudAt = (ms: number) => Math.round(55 + 40 * Math.sin(ms / (7 * HOUR)));

function radiationAt(ms: number): number {
  const hour = new Date(ms).getUTCHours() + new Date(ms).getUTCMinutes() / 60;
  const sun = Math.max(0, Math.sin(((hour - 6) / 12) * Math.PI));
  return Math.round(sun * 420 * (1 - cloudAt(ms) / 130));
}

const forecastTemp = (ms: number) => round1(outsideAt(ms) + 0.5 + 0.4 * Math.sin(ms / (5 * HOUR)));

export interface WeatherOptions {
  enabled: boolean;
  source: string;
  latitude: number | null;
  longitude: number | null;
  curve: Curve;
}

/**
 * Weather fixture: integer outside readings, their filtered value, an hourly forecast with
 * radiation, cloud and wind, last day's 24 h-lead forecast, error statistics and the curve outlook.
 */
export function makeWeather(
  now: number,
  backH: number,
  aheadH: number,
  options: WeatherOptions,
): WeatherResponse {
  if (!options.enabled)
    return {
      enabled: false,
      provider: 'open-meteo',
      reason: 'weather_enabled is off',
      location:
        options.latitude === null || options.longitude === null
          ? null
          : { latitude: options.latitude, longitude: options.longitude, source: options.source },
    };
  const stepMs = 900_000;
  const start = Math.floor((now - backH * HOUR) / stepMs) * stepMs;
  const measured: WeatherPoint[] = [];
  const filtered: WeatherPoint[] = [];
  let previous: number | null = null;
  let previousAt: number | null = null;
  for (let t = start; t <= now; t += stepMs) {
    const reading = Math.round(outsideAt(t));
    previous = filterOutside(previous, previousAt, reading, t / 1000, 3600);
    previousAt = t / 1000;
    measured.push([iso(t), reading]);
    filtered.push([iso(t), round1(previous)]);
  }
  const firstHour = Math.ceil(now / HOUR) * HOUR;
  const forecast: ForecastPoint[] = [];
  for (let t = firstHour; t <= now + aheadH * HOUR; t += HOUR) {
    forecast.push([
      iso(t),
      forecastTemp(t),
      radiationAt(t),
      Math.max(0, Math.min(100, cloudAt(t))),
      round1(3 + 2 * Math.sin(t / (9 * HOUR))),
    ]);
  }
  const past: WeatherPoint[] = [];
  for (let t = Math.floor((now - backH * HOUR) / HOUR) * HOUR; t <= now; t += HOUR) {
    past.push([iso(t), round1(forecastTemp(t) + 0.3 * Math.cos(t / (3 * HOUR)))]);
  }
  const outlook: WeatherPoint[] = [];
  let state: number | null = filtered[filtered.length - 1]?.[1] ?? null;
  let stateAt = now / 1000;
  for (const [at, temp] of forecast) {
    const t = Date.parse(at);
    if (temp === null) continue;
    state = filterOutside(state, stateAt, temp, t / 1000, 3600);
    stateAt = t / 1000;
    outlook.push([at, round1(curveWater(options.curve, state))]);
  }
  const lastFiltered = filtered[filtered.length - 1]?.[1] ?? null;
  return {
    enabled: true,
    provider: 'open-meteo',
    issued: iso(now - 20 * 60_000),
    age: 1200.0,
    stale: false,
    location:
      options.latitude === null || options.longitude === null
        ? { latitude: 52.09, longitude: 5.12, source: 'ha_zone_home' }
        : { latitude: options.latitude, longitude: options.longitude, source: options.source },
    now: {
      measured_c: measured[measured.length - 1]?.[1] ?? null,
      filtered_c: lastFiltered,
      forecast_c: forecastTemp(now),
      curve_c: lastFiltered === null ? null : round1(curveWater(options.curve, lastFiltered)),
    },
    measured: { step: 900, points: measured },
    filtered: { step: 900, points: filtered },
    forecast: { step: 3600, points: forecast },
    forecast_past: { lead_h: 24, points: past },
    error: { lead_h: [6, 24], bias_k: [0.3, 0.8], mae_k: [0.9, 1.4], n: [160, 140] },
    curve_outlook: { points: outlook },
  };
}
