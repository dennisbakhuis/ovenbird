import { outsideAt, roomAt, TARGET_C } from './decisions.ts';
import { pumpStateAt } from './fixtures.ts';

const MINUTE = 60_000;
const DAY = 86_400_000;
const BAND_BELOW_K = 0.5;

const round = (value: number, digits = 1) => Number(value.toFixed(digits));

function localMidnight(ms: number): number {
  const date = new Date(ms);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function nextMidnight(ms: number): number {
  const date = new Date(ms);
  date.setHours(24, 0, 0, 0);
  return date.getTime();
}

function dateKey(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

interface DayTotals {
  minutes: number;
  electricWh: number;
  heatWh: number;
  starts: number;
  runMinutes: number;
  defrosts: number;
  defrostMinutes: number;
  dhwRuns: number;
  dhwMinutes: number;
  outsideSum: number;
  outsideMin: number;
  roomSum: number;
  roomMin: number;
  belowKMinutes: number;
}

const cache = new Map<string, DayTotals>();

/**
 * Integrate the mock pump model minute by minute over [from, to), the same samples the history
 * endpoint averages, so the daily figures agree with what the pages compute from `history`.
 */
function integrate(from: number, to: number): DayTotals {
  const totals: DayTotals = {
    minutes: 0,
    electricWh: 0,
    heatWh: 0,
    starts: 0,
    runMinutes: 0,
    defrosts: 0,
    defrostMinutes: 0,
    dhwRuns: 0,
    dhwMinutes: 0,
    outsideSum: 0,
    outsideMin: Infinity,
    roomSum: 0,
    roomMin: Infinity,
    belowKMinutes: 0,
  };
  let previous = pumpStateAt(from - MINUTE);
  for (let t = from; t < to; t += MINUTE) {
    const state = pumpStateAt(t);
    const outside = outsideAt(t);
    const room = roomAt(t);
    totals.minutes += 1;
    totals.electricWh += state.electricW / 60;
    totals.heatWh += state.heatW / 60;
    if (state.hz > 0) totals.runMinutes += 1;
    if (state.hz > 0 && previous.hz === 0) totals.starts += 1;
    if (state.phase === 'defrost') totals.defrostMinutes += 1;
    if (state.phase === 'defrost' && previous.phase !== 'defrost') totals.defrosts += 1;
    if (state.phase === 'dhw') totals.dhwMinutes += 1;
    if (state.phase === 'dhw' && previous.phase !== 'dhw') totals.dhwRuns += 1;
    totals.outsideSum += outside;
    totals.outsideMin = Math.min(totals.outsideMin, outside);
    totals.roomSum += room;
    totals.roomMin = Math.min(totals.roomMin, room);
    totals.belowKMinutes += Math.max(0, TARGET_C - BAND_BELOW_K - room);
    previous = state;
  }
  return totals;
}

function dayTotals(from: number, to: number, complete: boolean): DayTotals {
  if (!complete) return integrate(from, to);
  const key = `${from}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const totals = integrate(from, to);
  cache.set(key, totals);
  return totals;
}

const EMPTY = {
  electric_kwh: null,
  heat_kwh: null,
  cop: null,
  dhw_electric_kwh: null,
  dhw_heat_kwh: null,
  compressor_starts: null,
  run_s: null,
  defrosts: null,
  defrost_s: null,
  dhw_runs: null,
  dhw_s: null,
  outside_mean_c: null,
  outside_min_c: null,
  room_mean_c: null,
  room_min_c: null,
  below_comfort_kh: null,
  setpoint_mean_c: null,
  setpoint_changes: null,
  writes: null,
};

/**
 * `GET api/v1/insight/daily` fixture: `days` local days ending today (partial), integrated from
 * the same pump model as `history` (so today agrees with the Home tiles), with one day without
 * data, one day with low coverage and a pump that does not report hot-water power separately.
 */
export function makeInsightDaily(days: number, now: number) {
  const today = localMidnight(now);
  const out = [];
  for (let back = days - 1; back >= 0; back--) {
    const from = localMidnight(today - back * DAY + 12 * 3_600_000);
    const end = nextMidnight(from);
    const partial = back === 0;
    const to = partial ? Math.floor(now / MINUTE) * MINUTE + MINUTE : end;
    const hours = (to - from) / 3_600_000;
    const empty = back === 11 && days > 12;
    const lowCoverage = back === 15 && days > 16;
    const coverage = empty ? null : lowCoverage ? 0.62 : 0.99;
    const base = {
      date: dateKey(from + 12 * 3_600_000),
      from: new Date(from).toISOString(),
      to: new Date(end).toISOString(),
      hours: round(hours, 2),
      partial,
      coverage,
      comfort_c: TARGET_C,
    };
    if (empty) {
      out.push({ ...base, ...EMPTY });
      continue;
    }
    const totals = dayTotals(from, to, !partial);
    const share = lowCoverage ? 0.62 : 1;
    const electric = (totals.electricWh / 1000) * share;
    const heat = (totals.heatWh / 1000) * share;
    const writes = Math.round(totals.starts * 3 * share);
    out.push({
      ...base,
      electric_kwh: round(electric, 2),
      heat_kwh: round(heat, 2),
      cop: electric > 0 ? round(heat / electric, 2) : null,
      dhw_electric_kwh: null,
      dhw_heat_kwh: null,
      compressor_starts: Math.round(totals.starts * share),
      run_s: Math.round(totals.runMinutes * 60 * share),
      defrosts: Math.round(totals.defrosts * share),
      defrost_s: Math.round(totals.defrostMinutes * 60 * share),
      dhw_runs: totals.dhwRuns,
      dhw_s: totals.dhwMinutes * 60,
      outside_mean_c: round(totals.outsideSum / totals.minutes),
      outside_min_c: round(totals.outsideMin),
      room_mean_c: round(totals.roomSum / totals.minutes),
      room_min_c: round(totals.roomMin),
      below_comfort_kh: round(totals.belowKMinutes / 60, 2),
      setpoint_mean_c: round(30 + (8 - totals.outsideSum / totals.minutes) * 0.6),
      setpoint_changes: writes,
      writes,
    });
  }
  return {
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    band_below_k: BAND_BELOW_K,
    room_signal: 'ha/sensor.living_room_temperature',
    days: out,
  };
}
