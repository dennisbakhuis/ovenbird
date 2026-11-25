import type { HistoryPoint } from './types';

export interface XY {
  x: number;
  y: number;
}

export interface Domain {
  tMin: number;
  tMax: number;
  vMin: number;
  vMax: number;
}

/**
 * Convert history points to numeric (ms, value) pairs, dropping non-numeric entries.
 */
export function numericPoints(points: HistoryPoint[]): [number, number][] {
  const out: [number, number][] = [];
  for (const [iso, value] of points) {
    const t = Date.parse(iso);
    if (Number.isFinite(t) && typeof value === 'number' && Number.isFinite(value)) {
      out.push([t, value]);
    }
  }
  return out;
}

/**
 * Compute a padded domain over all series; value bounds are rounded outward to whole degrees.
 */
export function computeDomain(
  series: [number, number][][],
  tMin: number,
  tMax: number,
): Domain | null {
  let vMin = Infinity;
  let vMax = -Infinity;
  for (const points of series) {
    for (const [, v] of points) {
      if (v < vMin) vMin = v;
      if (v > vMax) vMax = v;
    }
  }
  if (!Number.isFinite(vMin) || tMax <= tMin) return null;
  vMin = Math.floor(vMin - 1);
  vMax = Math.ceil(vMax + 1);
  return { tMin, tMax, vMin, vMax };
}

/**
 * Build an SVG path, breaking the line where consecutive points are further apart than `gapMs`.
 */
export function linePath(
  points: [number, number][],
  domain: Domain,
  width: number,
  height: number,
  gapMs: number,
): string {
  const sx = (t: number) => ((t - domain.tMin) / (domain.tMax - domain.tMin)) * width;
  const sy = (v: number) => height - ((v - domain.vMin) / (domain.vMax - domain.vMin)) * height;
  let path = '';
  let previous: number | null = null;
  for (const [t, v] of points) {
    const command = previous === null || t - previous > gapMs ? 'M' : 'L';
    path += `${command}${sx(t).toFixed(1)},${sy(v).toFixed(1)}`;
    previous = t;
  }
  return path;
}

/**
 * Evenly spaced tick values covering [min, max], aiming for roughly `count` ticks, never closer
 * than `minStep`.
 */
export function niceTicks(min: number, max: number, count = 5, minStep = 1): number[] {
  const span = max - min;
  if (span <= 0) return [min];
  const step = Math.max(niceStep(span / count), minStep);
  const decimals = Math.max(0, -Math.floor(Math.log10(step)));
  const ticks: number[] = [];
  for (let i = Math.ceil(min / step - 1e-9); i * step <= max + 1e-9; i++) {
    ticks.push(Number((i * step).toFixed(decimals)));
  }
  return ticks;
}

/**
 * Round a raw step up to 1, 2 or 5 times a power of ten.
 */
export function niceStep(rough: number): number {
  if (!(rough > 0) || !Number.isFinite(rough)) return 1;
  const power = 10 ** Math.floor(Math.log10(rough));
  const unit = rough / power;
  const factor = unit <= 1 + 1e-9 ? 1 : unit <= 2 + 1e-9 ? 2 : unit <= 5 + 1e-9 ? 5 : 10;
  return factor * power;
}

export type Point = [number, number];

export interface Axis {
  min: number;
  max: number;
}

/**
 * Min and max over several point lists, padded by `pad` of the span and snapped outward to
 * `snap`; null when there is no data.
 */
export function valueAxis(lists: Point[][], pad = 0.08, snap = 1): Axis | null {
  let min = Infinity;
  let max = -Infinity;
  for (const list of lists) {
    for (const [, v] of list) {
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  if (!Number.isFinite(min)) return null;
  const span = Math.max(max - min, snap);
  return {
    min: Math.floor((min - span * pad) / snap) * snap,
    max: Math.ceil((max + span * pad) / snap) * snap,
  };
}

/**
 * SVG path for a step line (value held until the next sample), broken at gaps over `gapMs`.
 */
export function stepPath(
  points: Point[],
  sx: (t: number) => number,
  sy: (v: number) => number,
  gapMs: number,
  endT?: number,
): string {
  let path = '';
  let previous: Point | null = null;
  for (const point of points) {
    const [t, v] = point;
    if (previous === null || t - previous[0] > gapMs) {
      path += `M${sx(t).toFixed(1)},${sy(v).toFixed(1)}`;
    } else {
      path += `H${sx(t).toFixed(1)}V${sy(v).toFixed(1)}`;
    }
    previous = point;
  }
  if (previous !== null && endT !== undefined && endT > previous[0]) {
    path += `H${sx(endT).toFixed(1)}`;
  }
  return path;
}

/**
 * SVG polygon path between an upper and a lower line sharing the same timestamps.
 */
export function areaPath(
  upper: Point[],
  lower: Point[],
  sx: (t: number) => number,
  sy: (v: number) => number,
): string {
  if (upper.length < 2 || upper.length !== lower.length) return '';
  const top = upper.map(([t, v]) => `${sx(t).toFixed(1)},${sy(v).toFixed(1)}`);
  const bottom = lower.map(([t, v]) => `${sx(t).toFixed(1)},${sy(v).toFixed(1)}`).reverse();
  return `M${top.join('L')}L${bottom.join('L')}Z`;
}

const TICK_STEPS_MS = [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440, 2880, 10080].map(
  (minutes) => minutes * 60_000,
);

/**
 * Time ticks at round local-time steps (minutes to days), roughly `count` across [from, to], and
 * never fewer than three steps across the span (14 days get a tick every 2 days, not every week).
 */
export function timeTicks(from: number, to: number, count = 5): number[] {
  if (to <= from) return [from];
  const rough = (to - from) / count;
  let index = TICK_STEPS_MS.findIndex((s) => s >= rough);
  if (index < 0) index = TICK_STEPS_MS.length - 1;
  while (index > 0 && (to - from) / (TICK_STEPS_MS[index] ?? 1) < 3) index -= 1;
  const step = TICK_STEPS_MS[index] ?? 0;
  const offsetMs = -new Date(from).getTimezoneOffset() * 60_000;
  const ticks: number[] = [];
  let t = Math.ceil((from + offsetMs) / step) * step - offsetMs;
  while (t <= to) {
    ticks.push(t);
    t += step;
  }
  return ticks;
}

/**
 * Index of the sample closest to `t` in a sorted list of timestamps, or -1 when empty.
 */
export function nearestIndex(times: number[], t: number): number {
  if (times.length === 0) return -1;
  let lo = 0;
  let hi = times.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((times[mid] ?? 0) < t) lo = mid + 1;
    else hi = mid;
  }
  const after = times[lo] ?? 0;
  const before = lo > 0 ? (times[lo - 1] ?? after) : after;
  return lo > 0 && Math.abs(before - t) <= Math.abs(after - t) ? lo - 1 : lo;
}

export interface Interval {
  from: number;
  to: number;
}

export interface Scale {
  (value: number): number;
  invert(pixel: number): number;
}

/**
 * Linear map from [d0, d1] to [r0, r1], with an inverse for pointer positions.
 */
export function linearScale(d0: number, d1: number, r0: number, r1: number): Scale {
  const k = (r1 - r0) / (d1 - d0 || 1) || 1e-9;
  const scale = ((value: number) => r0 + (value - d0) * k) as Scale;
  scale.invert = (pixel: number) => d0 + (pixel - r0) / k;
  return scale;
}

export interface AxisOptions {
  min?: number;
  max?: number;
  zero?: boolean;
  pad?: number;
  snap?: number;
}

/**
 * Value axis over several point lists with optional fixed ends, zero inclusion and snapping;
 * the snap step defaults to a nice step of an eighth of the data span. Null when there is nothing to show.
 */
export function axisFor(lists: Point[][], options: AxisOptions = {}): Axis | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const list of lists) {
    for (const [, v] of list) {
      if (!Number.isFinite(v)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (options.min !== undefined) lo = Math.min(lo, options.min);
  if (options.max !== undefined) hi = Math.max(hi, options.max);
  if (!Number.isFinite(lo)) return null;
  if (options.zero) {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  }
  const span = Math.max(hi - lo, Math.abs(hi) * 0.02, 0.5);
  const snap = options.snap ?? niceStep(span / 8);
  const pad = options.pad ?? 0.08;
  let min = options.min ?? Math.floor((lo - span * pad) / snap) * snap;
  let max = options.max ?? Math.ceil((hi + span * pad) / snap) * snap;
  if (options.min === undefined && lo >= 0 && min < 0) min = 0;
  if (options.max === undefined && hi <= 0 && max > 0) max = 0;
  if (max - min < 1e-9) max = min + snap;
  return { min: round(min), max: round(max) };
}

function round(value: number): number {
  return Number(value.toFixed(9));
}

export interface PanelBox {
  top: number;
  height: number;
}

/**
 * Stack panels of the given pixel heights from `top`, separated by `gap`.
 */
export function panelLayout(heights: number[], gap: number, top = 0): PanelBox[] {
  let y = top;
  return heights.map((height) => {
    const box = { top: y, height };
    y += height + gap;
    return box;
  });
}

/**
 * Split `available` pixels over panels by weight after the gaps, giving each at least `min`.
 */
export function distributeHeights(
  weights: number[],
  available: number,
  gap: number,
  min = 24,
): number[] {
  if (weights.length === 0) return [];
  const safe = weights.map((w) => (w > 0 ? w : 1));
  const usable = Math.max(available - gap * (safe.length - 1), 0);
  const total = safe.reduce((sum, w) => sum + w, 0);
  return safe.map((w) => Math.max(Math.floor((usable * w) / total), min));
}

export interface StateSegment {
  from: number;
  to: number;
  state: string;
  level?: number;
}

export interface RunOptions {
  endT?: number;
  gapMs?: number;
  level?: (value: number) => number;
  levels?: number;
}

/**
 * Run-length segments of a sampled state signal: each sample holds until the next one (at most
 * `gapMs`, the last until `endT`); consecutive samples with the same state and intensity level
 * merge. `classify` returns null for "nothing to draw" (off). `level` maps a value to 0–1 and
 * is quantised to `levels` steps.
 */
export function runLengthSegments(
  points: Point[],
  classify: (value: number) => string | null,
  options: RunOptions = {},
): StateSegment[] {
  const { endT, gapMs = Infinity, level, levels = 4 } = options;
  const out: StateSegment[] = [];
  let current: StateSegment | null = null;
  for (let i = 0; i < points.length; i++) {
    const [t, v] = points[i] as Point;
    const next = points[i + 1];
    let end = next ? next[0] : (endT ?? t);
    if (end - t > gapMs) end = t + gapMs;
    const state = classify(v);
    if (state === null || end <= t) {
      current = null;
      continue;
    }
    const lvl = level ? quantise(level(v), levels) : undefined;
    if (current && current.state === state && current.level === lvl && current.to === t) {
      current.to = end;
    } else {
      current =
        lvl === undefined ? { from: t, to: end, state } : { from: t, to: end, state, level: lvl };
      out.push(current);
    }
  }
  return out;
}

function quantise(value: number, levels: number): number {
  const clamped = Math.min(Math.max(value, 0), 1);
  return Math.max(1, Math.ceil(clamped * levels - 1e-9)) / levels;
}

/**
 * Merge touching segments of the same state, dropping intensity levels.
 */
export function mergeRuns(segments: StateSegment[]): StateSegment[] {
  const out: StateSegment[] = [];
  for (const segment of segments) {
    const last = out[out.length - 1];
    if (last && last.state === segment.state && last.to >= segment.from) {
      last.to = Math.max(last.to, segment.to);
    } else {
      out.push({ from: segment.from, to: segment.to, state: segment.state });
    }
  }
  return out;
}

export interface RunStats {
  count: number;
  totalMs: number;
  longestMs: number;
}

/**
 * Number of runs, total and longest duration, optionally for one state only.
 */
export function runStats(segments: StateSegment[], state?: string): RunStats {
  const runs = mergeRuns(segments).filter((s) => state === undefined || s.state === state);
  let totalMs = 0;
  let longestMs = 0;
  for (const run of runs) {
    const duration = run.to - run.from;
    totalMs += duration;
    longestMs = Math.max(longestMs, duration);
  }
  return { count: runs.length, totalMs, longestMs };
}

/**
 * The segment covering `t` (end inclusive, so the state at `now` is the last one), or null.
 */
export function segmentAt(segments: StateSegment[], t: number): StateSegment | null {
  let lo = 0;
  let hi = segments.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const segment = segments[mid] as StateSegment;
    if (t < segment.from) hi = mid - 1;
    else if (t > segment.to) lo = mid + 1;
    else return segment;
  }
  return null;
}

/**
 * The sample shown for time `t`: the nearest one, or for step series the last one at or before
 * `t`; null when the chosen sample is further away than `maxDistMs`.
 */
export function valueAt(
  points: Point[],
  t: number,
  mode: 'nearest' | 'step' = 'nearest',
  maxDistMs = Infinity,
): Point | null {
  if (points.length === 0) return null;
  let lo = 0;
  let hi = points.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((points[mid] as Point)[0] <= t) lo = mid + 1;
    else hi = mid;
  }
  const before = lo > 0 ? (points[lo - 1] as Point) : null;
  const after = lo < points.length ? (points[lo] as Point) : null;
  let pick: Point | null;
  if (mode === 'step') pick = before;
  else if (!before) pick = after;
  else if (!after) pick = before;
  else pick = t - before[0] <= after[0] - t ? before : after;
  if (!pick || Math.abs(pick[0] - t) > maxDistMs) return null;
  return pick;
}

/**
 * Sorted, de-duplicated timestamps of several point lists.
 */
export function unionTimes(lists: Point[][]): number[] {
  const set = new Set<number>();
  for (const list of lists) for (const [t] of list) set.add(t);
  return [...set].sort((a, b) => a - b);
}

/**
 * New crosshair time after a key press, snapping to `times` (or 48 even steps when empty):
 * arrows move one sample, PageUp/PageDown (or `big`) about a twelfth of the span, Home/End to
 * the ends; the first press starts at the latest sample. Undefined for keys it does not handle.
 */
export function stepCursor(
  times: number[],
  current: number | null,
  key: string,
  from: number,
  to: number,
  big = false,
): number | undefined {
  const grid = times.length > 0 ? times : evenTimes(from, to, 48);
  const first = grid[0] as number;
  const last = grid[grid.length - 1] as number;
  if (key === 'Home') return first;
  if (key === 'End') return last;
  const backward = key === 'ArrowLeft' || key === 'ArrowDown' || key === 'PageDown';
  const forward = key === 'ArrowRight' || key === 'ArrowUp' || key === 'PageUp';
  if (!backward && !forward) return undefined;
  if (current === null) return last;
  const index = nearestIndex(grid, current);
  const jump = big || key === 'PageUp' || key === 'PageDown';
  if (!jump) {
    const next = Math.min(Math.max(index + (forward ? 1 : -1), 0), grid.length - 1);
    return grid[next] as number;
  }
  const target = current + ((to - from) / 12) * (forward ? 1 : -1);
  let next = nearestIndex(grid, target);
  if (next === index) next = Math.min(Math.max(index + (forward ? 1 : -1), 0), grid.length - 1);
  return grid[next] as number;
}

function evenTimes(from: number, to: number, count: number): number[] {
  const step = (to - from) / Math.max(count, 1);
  return Array.from({ length: count + 1 }, (_, i) => from + i * step);
}

/**
 * Greedy label placement: each label (sorted by x) takes the first of `rows` rows where it does
 * not overlap the previous label; -1 when it fits nowhere.
 */
export function layoutLabels(items: { x: number; width: number }[], rows = 2, gap = 4): number[] {
  const order = items.map((_, i) => i).sort((a, b) => (items[a]?.x ?? 0) - (items[b]?.x ?? 0));
  const ends = Array.from({ length: rows }, () => -Infinity);
  const out = items.map(() => -1);
  for (const i of order) {
    const item = items[i] as { x: number; width: number };
    const row = ends.findIndex((end) => item.x >= end + gap);
    if (row >= 0) {
      ends[row] = item.x + item.width;
      out[i] = row;
    }
  }
  return out;
}

export interface MarkerPlacement {
  label: boolean;
  align: 'start' | 'end';
}

/**
 * Lay marker labels out left to right on one row.
 * Each label sits right of its marker, or left of it when it would cross the right edge. A label
 * that would overlap the previous one is dropped (the marker keeps its icon).
 *
 * Parameters
 * ----------
 * items : marker x and label width (px), the label width includes the icon.
 * width : plot width (px).
 * gap : minimum space between two labels (px).
 *
 * Returns
 * -------
 * MarkerPlacement[] in input order.
 */
export function layoutMarkers(
  items: { x: number; width: number }[],
  width: number,
  gap = 6,
): MarkerPlacement[] {
  const order = items.map((_, i) => i).sort((a, b) => (items[a]?.x ?? 0) - (items[b]?.x ?? 0));
  const out: MarkerPlacement[] = items.map(() => ({ label: false, align: 'start' }));
  let end = -Infinity;
  for (const i of order) {
    const item = items[i] as { x: number; width: number };
    const align = item.x + item.width > width ? 'end' : 'start';
    const start = align === 'start' ? item.x : item.x - item.width;
    if (start >= end + gap && start >= 0) {
      out[i] = { label: true, align };
      end = align === 'start' ? item.x + item.width : item.x;
    } else {
      out[i] = { label: false, align };
    }
  }
  return out;
}

/**
 * Constant value as a two-point line over [from, to]; point lists pass through.
 */
export function asPoints(value: Point[] | number, from: number, to: number): Point[] {
  return typeof value === 'number'
    ? [
        [from, value],
        [to, value],
      ]
    : value;
}

const RAD = Math.PI / 180;

/**
 * Sunrise and sunset (epoch ms) of the UTC day containing `dayMs` at a location, from the
 * standard sunrise equation (about a minute accurate); `polar` reports midnight sun or polar night.
 */
export function sunTimes(
  dayMs: number,
  lat: number,
  lon: number,
): { rise: number; set: number } | { polar: 'day' | 'night' } {
  const julianDay = Math.floor(dayMs / 86_400_000) + 2440588;
  const n = julianDay - 2451545 + 0.0008;
  const meanSolar = n - lon / 360;
  const anomaly = (357.5291 + 0.98560028 * meanSolar) % 360;
  const centre =
    1.9148 * Math.sin(anomaly * RAD) +
    0.02 * Math.sin(2 * anomaly * RAD) +
    0.0003 * Math.sin(3 * anomaly * RAD);
  const longitude = (anomaly + centre + 180 + 102.9372) % 360;
  const transit =
    2451545 + meanSolar + 0.0053 * Math.sin(anomaly * RAD) - 0.0069 * Math.sin(2 * longitude * RAD);
  const declination = Math.asin(Math.sin(longitude * RAD) * Math.sin(23.4397 * RAD));
  const cosHour =
    (Math.sin(-0.833 * RAD) - Math.sin(lat * RAD) * Math.sin(declination)) /
    (Math.cos(lat * RAD) * Math.cos(declination));
  if (cosHour > 1) return { polar: 'night' };
  if (cosHour < -1) return { polar: 'day' };
  const half = Math.acos(cosHour) / RAD / 360;
  const toMs = (jd: number) => (jd - 2440587.5) * 86_400_000;
  return { rise: toMs(transit - half), set: toMs(transit + half) };
}

/**
 * Night intervals (sunset to sunrise) clipped to [from, to] for a location.
 */
export function nightIntervals(from: number, to: number, lat: number, lon: number): Interval[] {
  const nights: Interval[] = [];
  const startDay = Math.floor(from / 86_400_000) - 1;
  const endDay = Math.floor(to / 86_400_000) + 1;
  let darkSince: number | null = null;
  for (let day = startDay; day <= endDay; day++) {
    const sun = sunTimes(day * 86_400_000 + 43_200_000, lat, lon);
    if ('polar' in sun) {
      if (sun.polar === 'night') darkSince ??= day * 86_400_000;
      else if (darkSince !== null) {
        nights.push({ from: darkSince, to: day * 86_400_000 });
        darkSince = null;
      }
      continue;
    }
    if (darkSince !== null) nights.push({ from: darkSince, to: sun.rise });
    darkSince = sun.set;
  }
  if (darkSince !== null) nights.push({ from: darkSince, to: (endDay + 1) * 86_400_000 });
  return clipIntervals(nights, from, to);
}

/**
 * Night intervals between fixed local clock hours (e.g. 22 → 7), clipped to [from, to].
 */
export function nightByHours(from: number, to: number, startHour = 22, endHour = 7): Interval[] {
  const nights: Interval[] = [];
  const day = new Date(from);
  day.setHours(0, 0, 0, 0);
  day.setDate(day.getDate() - 1);
  while (day.getTime() <= to) {
    const start = new Date(day);
    start.setHours(startHour, 0, 0, 0);
    const end = new Date(day);
    if (endHour <= startHour) end.setDate(end.getDate() + 1);
    end.setHours(endHour, 0, 0, 0);
    nights.push({ from: start.getTime(), to: end.getTime() });
    day.setDate(day.getDate() + 1);
  }
  return clipIntervals(nights, from, to);
}

function clipIntervals(intervals: Interval[], from: number, to: number): Interval[] {
  return intervals
    .map((i) => ({ from: Math.max(i.from, from), to: Math.min(i.to, to) }))
    .filter((i) => i.to > i.from);
}
