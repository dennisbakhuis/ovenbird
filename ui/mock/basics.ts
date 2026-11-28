import type { Schemas } from '../src/lib/core/types';

type Basics = Schemas['InsightBasics'];
type Estimate = Schemas['LossEstimate'];
type Point = Schemas['HeatLossPoint'];

export type BasicsScenario = 'collecting' | 'provisional' | 'off';

const DAY = 86_400_000;
const COMFORT_C = 21;
const OUTSIDE_NOW_C = 2;
const NIGHT_C = -3;
const DESIGN_C = -10;
const SETPOINT_MIN_C = 25;
const SETPOINT_MAX_C = 45;
const FLOW_L_MIN = 20;

const round = (value: number, digits = 0) => Number(value.toFixed(digits));

function dateKey(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

interface Fit {
  h: number;
  g: number;
  hLow: number;
  hHigh: number;
  measuredMaxK: number;
}

function estimate(fit: Fit, outside: number, at: string | null, widen: number): Estimate {
  const deltaK = COMFORT_C - outside;
  const loss = fit.h * deltaK - fit.g;
  const spread = (fit.hHigh - fit.hLow) / 2 + widen * Math.max(deltaK - fit.measuredMaxK, 0);
  return {
    at,
    outside_c: outside,
    room_c: COMFORT_C,
    delta_k: deltaK,
    loss_w: round(loss),
    low_w: round(loss - spread * deltaK * 0.25),
    high_w: round(loss + spread * deltaK * 0.25),
    beyond_data: deltaK > fit.measuredMaxK,
  };
}

function points(now: number, count: number, minK: number, maxK: number, fit: Fit): Point[] {
  const balanceK = fit.g / fit.h;
  const noise = [60, -110, 90, -40, 130, -80, 20, -150, 100, -30, 70, -90];
  return Array.from({ length: count }, (_, i): Point => {
    const deltaK = round(minK + ((maxK - minK) * i) / Math.max(count - 1, 1), 1);
    const heat = fit.h * deltaK - fit.g + (noise[i % noise.length] ?? 0);
    const last = now - (count - i) * 2 * DAY;
    const nearBalance = deltaK < balanceK + 3;
    const outlier = i === Math.floor(count * 0.6) && count > 12;
    return {
      first_date: dateKey(last - DAY),
      last_date: dateKey(last),
      delta_k: deltaK,
      heat_w: round(outlier ? heat - 900 : nearBalance ? heat - 250 : heat),
      outside_c: round(COMFORT_C - deltaK, 1),
      room_c: COMFORT_C,
      use: outlier ? 'outlier' : nearBalance ? 'near_balance' : 'used',
    };
  });
}

function emitterTable(k: number, lossW: number | null) {
  const w = (FLOW_L_MIN / 60) * 1000 * 4.186;
  const heatAt = (supply: number, kk: number) => (kk * (supply - COMFORT_C)) / (1 + kk / (2 * w));
  const rows = [];
  for (let supply = SETPOINT_MIN_C; supply <= SETPOINT_MAX_C; supply += 5) {
    const heat = heatAt(supply, k);
    rows.push({
      supply_c: supply,
      mean_water_c: round(COMFORT_C + heat / k, 1),
      heat_w: round(heat),
      low_w: round(heatAt(supply, k * 0.95)),
      high_w: round(heatAt(supply, k * 1.05)),
      loss_now_w: lossW,
      margin_w: lossW === null ? null : round(heat - lossW),
    });
  }
  const balanceSupply =
    lossW === null ? null : round(COMFORT_C + (lossW * (1 + k / (2 * w))) / k, 1);
  return { rows, w, balanceSupply };
}

const BINS: [number, number, number, number][] = [
  [-4, 3920, 1330, 2],
  [-2, 3560, 1160, 5],
  [0, 3050, 900, 9],
  [2, 2580, 690, 12],
  [4, 2140, 520, 14],
  [6, 1700, 380, 10],
  [8, 1290, 290, 8],
  [10, 900, 200, 4],
  [12, 560, 140, 2],
];

function byWeather(scale = 1, count = BINS.length): Basics['by_weather'] {
  return BINS.slice(0, count).map(([from, heat, electric, days]) => ({
    from_c: from,
    to_c: from + 2,
    days: Math.max(Math.round(days * scale), 1),
    heat_w: heat,
    electric_w: electric,
    cop: round(heat / electric, 2),
    few_days: Math.round(days * scale) < 3,
  }));
}

/**
 * The mock `GET insight/basics`: a credible house by default, `provisional` with a wide band,
 * `collecting` without a figure and `off` with the feature switched off. Round, made-up numbers.
 */
export function makeBasics(now: number, scenario?: BasicsScenario): Basics {
  const computedAt = new Date(now - 20 * 60_000).toISOString();
  const base = {
    computed_at: computedAt,
    timezone: 'Europe/Amsterdam',
    room_signal: 'ha/sensor.living_room_temperature',
    design_outside_c: DESIGN_C,
  };
  if (scenario === 'off')
    return {
      ...base,
      enabled: false,
      computed_at: null,
      room_signal: null,
      heat_loss: null,
      loss_now: null,
      heat_pump: null,
      by_weather: null,
    };

  if (scenario === 'collecting')
    return {
      ...base,
      enabled: true,
      heat_loss: {
        status: 'collecting',
        reasons: ['too_few_days'],
        h_w_per_k: null,
        h_low_w_per_k: null,
        h_high_w_per_k: null,
        offset_w: null,
        balance_offset_k: null,
        balance_c: null,
        days_used: 6,
        points_used: 3,
        outlier_points: 0,
        near_balance_points: 0,
        span_k: null,
        outside_min_c: null,
        outside_max_c: null,
        room_mean_c: null,
        residual_w: null,
        first_date: null,
        last_date: null,
        excluded: { low_coverage: 2, stove: 3, no_heating: 1, away: 0 },
        points: [],
      },
      loss_now: null,
      heat_pump: {
        delivered: { now_w: 2900, now_reason: null, mean_24h_w: 2600, coverage_24h: 0.99 },
        emitter: {
          status: 'collecting',
          reasons: ['too_few_hours'],
          k_w_per_k: null,
          k_low_w_per_k: null,
          k_high_w_per_k: null,
          hours_used: 12,
          days_used: 2,
          span_k: null,
          flow_l_min: FLOW_L_MIN,
          room_c: COMFORT_C,
          setpoint_min_c: SETPOINT_MIN_C,
          setpoint_max_c: SETPOINT_MAX_C,
          table: [],
          balance_supply_c: null,
          balance_mean_water_c: null,
          balance_in_range: null,
        },
      },
      by_weather: byWeather(0.3, 4),
    };

  const provisional = scenario === 'provisional';
  const fit: Fit = provisional
    ? { h: 170, g: 500, hLow: 120, hHigh: 220, measuredMaxK: 17 }
    : { h: 180, g: 600, hLow: 172, hHigh: 188, measuredMaxK: 21 };
  const widen = provisional ? 6 : 2;
  const nowEstimate = estimate(fit, OUTSIDE_NOW_C, new Date(now).toISOString(), widen);
  const count = provisional ? 12 : 22;
  const k = provisional ? 380 : 400;
  const table = emitterTable(k, nowEstimate.loss_w);
  const balanceMean =
    table.balanceSupply === null ? null : round(COMFORT_C + nowEstimate.loss_w / k, 1);
  return {
    ...base,
    enabled: true,
    heat_loss: {
      status: provisional ? 'provisional' : 'credible',
      reasons: provisional ? ['few_days', 'narrow_span'] : [],
      h_w_per_k: fit.h,
      h_low_w_per_k: fit.hLow,
      h_high_w_per_k: fit.hHigh,
      offset_w: fit.g,
      balance_offset_k: round(fit.g / fit.h, 1),
      balance_c: round(COMFORT_C - fit.g / fit.h, 1),
      days_used: count * 2,
      points_used: count,
      outlier_points: provisional ? 0 : 1,
      near_balance_points: provisional ? 1 : 2,
      span_k: provisional ? 8 : 15.5,
      outside_min_c: round(COMFORT_C - fit.measuredMaxK, 1),
      outside_max_c: provisional ? 12 : 15.5,
      room_mean_c: COMFORT_C,
      residual_w: 80,
      first_date: dateKey(now - count * 2 * DAY),
      last_date: dateKey(now - DAY),
      excluded: provisional
        ? { low_coverage: 0, stove: 2, no_heating: 1, away: 0 }
        : { low_coverage: 1, stove: 4, no_heating: 3, away: 2 },
      points: points(now, count, provisional ? 9 : 5.5, fit.measuredMaxK, fit),
    },
    loss_now: {
      room_source: 'measured',
      outside_source: 'filtered',
      forecast_available: true,
      now: nowEstimate,
      night: estimate(fit, NIGHT_C, new Date(now + 6 * 3_600_000).toISOString(), widen),
      design: estimate(fit, DESIGN_C, null, widen),
    },
    heat_pump: {
      delivered: { now_w: 3100, now_reason: null, mean_24h_w: 2700, coverage_24h: 0.998 },
      emitter: {
        status: provisional ? 'provisional' : 'credible',
        reasons: provisional ? ['few_hours'] : [],
        k_w_per_k: k,
        k_low_w_per_k: round(k * 0.95),
        k_high_w_per_k: round(k * 1.05),
        hours_used: provisional ? 64 : 180,
        days_used: provisional ? 6 : 20,
        span_k: provisional ? 6 : 11,
        flow_l_min: FLOW_L_MIN,
        room_c: COMFORT_C,
        setpoint_min_c: SETPOINT_MIN_C,
        setpoint_max_c: SETPOINT_MAX_C,
        table: table.rows,
        balance_supply_c: table.balanceSupply,
        balance_mean_water_c: balanceMean,
        balance_in_range: true,
      },
    },
    by_weather: byWeather(provisional ? 0.5 : 1),
  };
}
