import { buildRecord, curveWater, outsideAt, scenarioAt } from './decisions.ts';
import type { Scenario } from './scenario.ts';

const MINUTE = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;
const TIMEZONE = 'Europe/Amsterdam';
const SIGNAL = 'main/Z1_Water_Target_Temp';
const MAX_EPISODES = 500;
const CACHE_LIMIT = 120_000;
const OTHER_EVERY_MS = 30 * MINUTE;
const SHADOW_NOW_H = 3;
const OTHER_OFFSET_K = 0;

export interface Minute {
  ts: number;
  ovenbird: number | null;
  pump: number | null;
  mode: string | null;
  reason: string | null;
  writer: 'ovenbird' | 'other' | null;
}

interface Episode {
  start: number;
  end: number;
  maxAbs: number;
  maxDiff: number;
  atMax: Minute;
  first: Minute;
  endedBy: 'converged' | 'gap' | 'open';
}

/**
 * A minute as the live mock decisions have it: ovenbird's setpoint, the water target the pump
 * reports (the arbiter's `actual`), the mode and the reason.
 */
export interface LiveMinute {
  ovenbird: number | null;
  pump: number | null;
  mode: string;
  reason: string;
}

const decisions = new Map<number, { setpoint: number | null; reason: string }>();

function normalMinute(ms: number): number {
  let minute = Math.floor(ms / MINUTE) * MINUTE;
  for (let back = 0; back < 60; back += 1) {
    const index = Math.floor(minute / MINUTE);
    if (scenarioAt(((index % 360) + 360) % 360) === 'normal') return minute;
    minute -= MINUTE;
  }
  return minute;
}

/**
 * ovenbird's would-send value at a minute: the mock decision of the nearest preceding minute in
 * which the mock's 6-hour demonstration cycle runs its normal case (curve plus room correction),
 * so the comparison is not dominated by the cycle's staged ramps and clamps.
 */
function decisionAt(ms: number): { setpoint: number | null; reason: string } {
  const minute = normalMinute(ms);
  const cached = decisions.get(minute);
  if (cached) return cached;
  if (decisions.size > CACHE_LIMIT) decisions.clear();
  const { record } = buildRecord(minute, 'shadow');
  const value = { setpoint: record.setpoint, reason: record.reason };
  decisions.set(minute, value);
  return value;
}

const dayFormat = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});
const hourFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: TIMEZONE,
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

function localDate(ms: number): string {
  return dayFormat.format(ms);
}

function localMinuteOfDay(ms: number): number {
  const [h = '0', m = '0'] = hourFormat.format(ms).split(':');
  return Number(h) * 60 + Number(m);
}

function dayNumber(ms: number): number {
  return Math.floor(Date.parse(`${localDate(ms)}T00:00:00Z`) / DAY);
}

/**
 * The other controller's baseline the pump runs on: the same heating curve, as
 * whole degrees written every 30 minutes, with a three-hour night reduction of 3 K every third
 * night (23:00 to 02:00).
 */
function otherControllerAt(ms: number): number {
  const written = Math.floor(ms / OTHER_EVERY_MS) * OTHER_EVERY_MS;
  const base = Math.round(curveWater(outsideAt(written)) + OTHER_OFFSET_K);
  const minute = localMinuteOfDay(ms);
  const night = minute >= 23 * 60 || minute < 2 * 60;
  const nightDay = dayNumber(minute < 2 * 60 ? ms - DAY : ms);
  return night && nightDay % 3 === 0 ? base - 3 : base;
}

/**
 * Whether the minute has no pump data: a 40 min gap at 04:10 every fifth day.
 */
function pumpGap(ms: number): boolean {
  const minute = localMinuteOfDay(ms);
  return dayNumber(ms) % 5 === 1 && minute >= 4 * 60 + 10 && minute < 4 * 60 + 50;
}

/**
 * Whether ovenbird itself wrote the pump at this minute: a short supervised trial from 10:00 to
 * 11:30 every fourth day.
 */
function ovenbirdWrites(ms: number): boolean {
  const minute = localMinuteOfDay(ms);
  return dayNumber(ms) % 4 === 2 && minute >= 10 * 60 && minute < 11 * 60 + 30;
}

/**
 * Whether ovenbird would run its start ramp after the night (06:30 to 07:10, every second day): 2 K
 * below its normal value, a divergence it explains.
 */
function rampAt(ms: number): boolean {
  const minute = localMinuteOfDay(ms);
  return dayNumber(ms) % 2 === 0 && minute >= 6 * 60 + 30 && minute < 7 * 60 + 10;
}

/**
 * One minute of the comparison: ovenbird's would-send setpoint, the pump's target, the mode, the
 * reason and who wrote the pump (also the recorded minutes of the replay mock).
 */
export function minuteAt(
  ts: number,
  now: number,
  scenario: Scenario,
  live?: (ms: number) => LiveMinute | null,
): Minute {
  const recent = live?.(ts);
  if (recent)
    return {
      ts,
      ovenbird: recent.ovenbird,
      pump: recent.pump,
      mode: recent.ovenbird === null ? null : recent.mode,
      reason: recent.ovenbird === null ? null : recent.reason,
      writer:
        recent.pump === null
          ? null
          : recent.mode === 'auto' && recent.pump === recent.ovenbird
            ? 'ovenbird'
            : 'other',
    };
  const normal = decisionAt(ts);
  const ramp = rampAt(ts) && normal.setpoint !== null;
  const decision = ramp
    ? { setpoint: (normal.setpoint as number) - 2, reason: 'start_ramp' }
    : normal;
  const ovenbird = decision.setpoint;
  const own = ovenbirdWrites(ts);
  let pump: number | null = pumpGap(ts)
    ? null
    : own && ovenbird !== null
      ? ovenbird
      : otherControllerAt(ts);
  if (ovenbird !== null && pump !== null && now - ts < SHADOW_NOW_H * HOUR) {
    if (scenario.mode === 'shadow') pump = ovenbird + 2;
    else if (scenario.mode === 'paused') pump = ovenbird + 1;
  }
  return {
    ts,
    ovenbird,
    pump,
    mode: ovenbird === null ? null : own ? 'auto' : 'shadow',
    reason: ovenbird === null ? null : decision.reason,
    writer: pump === null ? null : own && pump === ovenbird ? 'ovenbird' : 'other',
  };
}

const diffOf = (row: Minute) =>
  row.ovenbird === null || row.pump === null ? null : row.ovenbird - row.pump;
const round = (value: number, digits: number) => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};
const iso = (ms: number) => new Date(ms).toISOString();

function findEpisodes(rows: Minute[], threshold: number): Episode[] {
  const found: Episode[] = [];
  let open: Episode | null = null;
  for (const row of rows) {
    const diff = diffOf(row);
    if (diff !== null && Math.abs(diff) > threshold) {
      if (open === null) {
        open = {
          start: row.ts,
          end: row.ts + MINUTE,
          maxAbs: Math.abs(diff),
          maxDiff: diff,
          atMax: row,
          first: row,
          endedBy: 'open',
        };
      } else {
        open.end = row.ts + MINUTE;
        if (Math.abs(diff) > open.maxAbs) {
          open.maxAbs = Math.abs(diff);
          open.maxDiff = diff;
          open.atMax = row;
        }
      }
      continue;
    }
    if (open !== null) {
      open.endedBy = diff === null ? 'gap' : 'converged';
      found.push(open);
      open = null;
    }
  }
  if (open !== null) found.push(open);
  return found;
}

function summarise(rows: Minute[], threshold: number) {
  const diffs = rows.map(diffOf).filter((d): d is number => d !== null);
  const compared = diffs.length;
  const over = diffs.filter((d) => Math.abs(d) > threshold).length;
  return {
    minutes: rows.length,
    compared_minutes: compared,
    gap_minutes: rows.length - compared,
    coverage: rows.length ? round(compared / rows.length, 3) : 0,
    mean_abs_k: compared ? round(diffs.reduce((s, d) => s + Math.abs(d), 0) / compared, 2) : null,
    max_abs_k: compared ? round(Math.max(...diffs.map(Math.abs)), 2) : null,
    bias_k: compared ? round(diffs.reduce((s, d) => s + d, 0) / compared, 2) : null,
    hours_over: round(over / 60, 2),
  };
}

const longest = (episodes: Episode[]) =>
  episodes.reduce((best, ep) => Math.max(best, (ep.end - ep.start) / MINUTE), 0);

function series(rows: Minute[], step: number) {
  const stepMs = step * 1000;
  const columns = {
    at: [] as string[],
    ovenbird: [] as (number | null)[],
    pump: [] as (number | null)[],
    diff: [] as (number | null)[],
    max_abs: [] as (number | null)[],
    writer: [] as ('ovenbird' | 'other' | null)[],
    mode: [] as (string | null)[],
  };
  let index = 0;
  while (index < rows.length) {
    const bucket = Math.floor((rows[index] as Minute).ts / stepMs) * stepMs;
    const items: Minute[] = [];
    while (index < rows.length && (rows[index] as Minute).ts < bucket + stepMs) {
      items.push(rows[index] as Minute);
      index += 1;
    }
    const last = <T>(pick: (row: Minute) => T | null) => {
      for (let i = items.length - 1; i >= 0; i -= 1)
        if (pick(items[i] as Minute) !== null) return items[i] as Minute;
      return null;
    };
    const ovenbird = last((r) => r.ovenbird);
    const pump = last((r) => r.pump);
    const both = last(diffOf);
    const diffs = items
      .map(diffOf)
      .filter((d): d is number => d !== null)
      .map(Math.abs);
    const bothDiff = both === null ? null : diffOf(both);
    columns.at.push(iso(bucket));
    columns.ovenbird.push(ovenbird?.ovenbird ?? null);
    columns.pump.push(pump?.pump ?? null);
    columns.diff.push(bothDiff === null ? null : round(bothDiff, 2));
    columns.max_abs.push(diffs.length ? round(Math.max(...diffs), 2) : null);
    columns.writer.push(pump?.writer ?? null);
    columns.mode.push(ovenbird?.mode ?? null);
  }
  return columns;
}

/**
 * The shadow divergence (`GET shadow/divergence`) for a window, built per minute like the service:
 * ovenbird's would-send setpoint (the mock decisions) against another controller's pump target with
 * whole-degree writes, a night reduction every third night, a start ramp every second morning, a short trial in which ovenbird
 * writes every fourth day and a data gap every fifth day. `mode:shadow` puts the pump 2 K above
 * ovenbird for the last three hours (an open episode), `mode:paused` 1 K. Deterministic in time.
 * `live` gives the minutes the live decisions cover (at least the current one), so the series ends
 * on what the strip and the Setpoint page show.
 */
export function makeDivergence(
  from: number,
  to: number,
  step: number,
  thresholdK: number,
  now: number,
  scenario: Scenario,
  live?: (ms: number) => LiveMinute | null,
): unknown {
  const first = Math.floor(from / MINUTE) * MINUTE;
  const end = Math.min(to, now + MINUTE);
  const rows: Minute[] = [];
  for (let ts = first; ts < end; ts += MINUTE) rows.push(minuteAt(ts, now, scenario, live));
  const found = findEpisodes(rows, thresholdK);
  const days: Record<string, unknown>[] = [];
  let start = 0;
  while (start < rows.length) {
    const date = localDate((rows[start] as Minute).ts);
    let stop = start;
    while (stop < rows.length && localDate((rows[stop] as Minute).ts) === date) stop += 1;
    const inside = rows.slice(start, stop);
    const dayFrom = (inside[0] as Minute).ts;
    const dayTo = (inside[inside.length - 1] as Minute).ts + MINUTE;
    const starting = found.filter((ep) => ep.start >= dayFrom && ep.start < dayTo);
    days.push({
      date,
      from: iso(dayFrom),
      to: iso(dayTo),
      ...summarise(inside, thresholdK),
      episodes: starting.length,
      longest_episode_min: longest(starting),
    });
    start = stop;
  }
  return {
    from: iso(from),
    to: iso(to),
    step,
    threshold_k: thresholdK,
    timezone: TIMEZONE,
    signal: SIGNAL,
    summary: {
      ...summarise(rows, thresholdK),
      episodes: found.length,
      longest_episode_min: longest(found),
    },
    days,
    episodes_total: found.length,
    episodes: found.slice(-MAX_EPISODES).map((ep) => ({
      start: iso(ep.start),
      end: iso(ep.end),
      minutes: (ep.end - ep.start) / MINUTE,
      max_abs_k: round(ep.maxAbs, 2),
      max_diff_k: round(ep.maxDiff, 2),
      ovenbird_c: ep.atMax.ovenbird,
      pump_c: ep.atMax.pump,
      reason: ep.first.reason,
      reason_at_max: ep.atMax.reason,
      mode: ep.first.mode,
      writer: ep.first.writer,
      ended_by: ep.endedBy,
    })),
    series: series(rows, step),
  };
}

const marks = new Map<string, Map<string, Record<string, unknown>>>();

/**
 * `POST shadow/episodes/explain` for a browser's scenario key: `{start, note}` marks the episode
 * that starts at `start` as explained, `{start, explained: false}` removes the mark.
 */
export function explainEpisode(
  key: string,
  body: Record<string, unknown>,
  now: number,
): { status: number; body: unknown } {
  const start = body['start'];
  if (typeof start !== 'string' || !Number.isFinite(Date.parse(start)))
    return { status: 400, body: { detail: 'start must be an ISO time' } };
  const byKey = marks.get(key) ?? new Map<string, Record<string, unknown>>();
  marks.set(key, byKey);
  const at = new Date(Date.parse(start)).toISOString();
  if (body['explained'] === false) {
    byKey.delete(at);
    return { status: 200, body: { explained: null } };
  }
  const note = body['note'];
  if (typeof note !== 'string' || !note.trim())
    return { status: 400, body: { detail: 'note is required' } };
  const mark = {
    start: at,
    start_ts: Date.parse(start) / 1000,
    note: note.trim().slice(0, 500),
    by: 'admin',
    at: new Date(now).toISOString(),
  };
  byKey.set(at, mark);
  return { status: 200, body: { explained: mark } };
}

/**
 * The divergence body with every episode's `explained` mark for the browser's key.
 */
export function withExplained(key: string, body: unknown): unknown {
  const byKey = marks.get(key);
  const data = body as { episodes?: Record<string, unknown>[] };
  if (!Array.isArray(data.episodes)) return body;
  return {
    ...data,
    episodes: data.episodes.map((ep) => ({
      ...ep,
      explained: byKey?.get(new Date(Date.parse(String(ep['start']))).toISOString()) ?? null,
    })),
  };
}
