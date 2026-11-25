export type CurvePoint = [number, number];
export type Curve = CurvePoint[];

export const MIN_POINTS = 2;
export const MAX_POINTS = 6;
export const OUTSIDE_MIN = -30;
export const OUTSIDE_MAX = 30;
export const OUTSIDE_GAP = 1;
export const WATER_SNAP = 0.5;
export const WATER_STEP = 1;
export const WATER_FINE_STEP = 0.5;
export const OUTSIDE_SNAP = 1;

export interface CurveLimits {
  waterMin: number;
  waterMax: number;
  outsideMin?: number;
  outsideMax?: number;
  minPoints?: number;
  maxPoints?: number;
}

export const DEFAULT_LIMITS: CurveLimits = { waterMin: 10, waterMax: 60 };

/**
 * Water setpoint of a piecewise-linear curve at an outside temperature, flat beyond the end
 * points. Mirrors `HeatingCurve.water` in the core controller.
 */
export function curveWater(points: Curve, outside: number): number {
  const first = points[0];
  const last = points[points.length - 1];
  if (!first || !last) return NaN;
  if (outside <= first[0]) return first[1];
  if (outside >= last[0]) return last[1];
  let index = 1;
  while (index < points.length - 1 && (points[index] as CurvePoint)[0] <= outside) index += 1;
  const left = points[index - 1] as CurvePoint;
  const right = points[index] as CurvePoint;
  const share = (outside - left[0]) / (right[0] - left[0]);
  return left[1] + share * (right[1] - left[1]);
}

/**
 * Slope magnitude of the segment at an outside temperature; mirrors `HeatingCurve.sensitivity`.
 */
export function curveSensitivity(points: Curve, outside: number): number {
  let index = 1;
  while (index < points.length - 1 && (points[index] as CurvePoint)[0] <= outside) index += 1;
  const left = points[index - 1];
  const right = points[index];
  if (!left || !right) return 0;
  return Math.abs((right[1] - left[1]) / (right[0] - left[0]));
}

/**
 * First-order outside filter step mirroring `filter_outside` in the core controller.
 */
export function filterOutside(
  previous: number | null,
  previousAt: number | null,
  sample: number,
  at: number,
  tauS: number,
): number {
  if (previous === null || previousAt === null || tauS <= 0) return sample;
  const dt = at - previousAt;
  if (dt <= 0) return previous;
  return previous + (1 - Math.exp(-dt / tauS)) * (sample - previous);
}

export type CurveProblem =
  | 'too_few_points'
  | 'too_many_points'
  | 'not_finite'
  | 'outside_not_increasing'
  | 'water_increases'
  | 'outside_out_of_range'
  | 'water_out_of_range';

/**
 * Structural problems of a curve (the same rules the core enforces), empty when valid.
 */
export function curveProblems(points: Curve, limits: CurveLimits = DEFAULT_LIMITS): CurveProblem[] {
  const found = new Set<CurveProblem>();
  if (points.length < (limits.minPoints ?? MIN_POINTS)) found.add('too_few_points');
  if (points.length > (limits.maxPoints ?? MAX_POINTS)) found.add('too_many_points');
  const outsideMin = limits.outsideMin ?? OUTSIDE_MIN;
  const outsideMax = limits.outsideMax ?? OUTSIDE_MAX;
  for (const [outside, water] of points) {
    if (!Number.isFinite(outside) || !Number.isFinite(water)) found.add('not_finite');
    if (outside < outsideMin || outside > outsideMax) found.add('outside_out_of_range');
    if (water < limits.waterMin || water > limits.waterMax) found.add('water_out_of_range');
  }
  for (let i = 1; i < points.length; i += 1) {
    const left = points[i - 1] as CurvePoint;
    const right = points[i] as CurvePoint;
    if (!(left[0] < right[0])) found.add('outside_not_increasing');
    if (right[1] > left[1]) found.add('water_increases');
  }
  return [...found];
}

const snapTo = (value: number, step: number) => Math.round(value / step) * step;
const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high);

/**
 * Set the water temperature of point `index`, snapped to `snap` and held between its neighbours
 * so the curve never rises with outside temperature.
 */
export function setWater(
  points: Curve,
  index: number,
  water: number,
  limits: CurveLimits = DEFAULT_LIMITS,
  snap = WATER_SNAP,
): Curve {
  if (!points[index]) return points;
  const upper = index > 0 ? (points[index - 1] as CurvePoint)[1] : limits.waterMax;
  const lower = index < points.length - 1 ? (points[index + 1] as CurvePoint)[1] : limits.waterMin;
  const next = clamp(snapTo(water, snap), Math.max(lower, limits.waterMin), upper);
  return points.map((p, i): CurvePoint => (i === index ? [p[0], next] : p));
}

/**
 * Set the outside temperature of point `index`, snapped and kept strictly between its neighbours.
 */
export function setOutside(points: Curve, index: number, outside: number): Curve {
  if (!points[index]) return points;
  const low = index > 0 ? (points[index - 1] as CurvePoint)[0] + OUTSIDE_GAP : OUTSIDE_MIN;
  const high =
    index < points.length - 1 ? (points[index + 1] as CurvePoint)[0] - OUTSIDE_GAP : OUTSIDE_MAX;
  if (low > high) return points;
  const next = clamp(snapTo(outside, OUTSIDE_SNAP), low, high);
  return points.map((p, i): CurvePoint => (i === index ? [next, p[1]] : p));
}

/**
 * Insert a point in the widest gap (on the curve, so the shape is unchanged), or extend past
 * the right end when no gap is wide enough. Returns the input when the curve is full.
 */
export function addPoint(points: Curve): Curve {
  if (points.length >= MAX_POINTS) return points;
  let best = -1;
  let widest = 0;
  for (let i = 1; i < points.length; i += 1) {
    const gap = (points[i] as CurvePoint)[0] - (points[i - 1] as CurvePoint)[0];
    if (gap > widest) {
      widest = gap;
      best = i;
    }
  }
  if (best > 0 && widest >= 2 * OUTSIDE_GAP) {
    const left = points[best - 1] as CurvePoint;
    const right = points[best] as CurvePoint;
    const outside = snapTo((left[0] + right[0]) / 2, OUTSIDE_SNAP);
    if (outside > left[0] && outside < right[0]) {
      const water = snapTo(curveWater(points, outside), WATER_SNAP);
      const inserted: CurvePoint = [outside, clamp(water, right[1], left[1])];
      return [...points.slice(0, best), inserted, ...points.slice(best)];
    }
  }
  const last = points[points.length - 1];
  if (!last || last[0] + 2 * OUTSIDE_GAP > OUTSIDE_MAX) return points;
  return [...points, [Math.min(last[0] + 5, OUTSIDE_MAX), last[1]]];
}

/**
 * Remove point `index`, keeping at least two points.
 */
export function removePoint(points: Curve, index: number): Curve {
  if (points.length <= MIN_POINTS || !points[index]) return points;
  return points.filter((_, i) => i !== index);
}

/**
 * Whether two curves have the same points.
 */
export function sameCurve(a: Curve, b: Curve): boolean {
  return a.length === b.length && a.every((p, i) => p[0] === b[i]?.[0] && p[1] === b[i]?.[1]);
}

/**
 * Coerce an unknown value to a curve, or null when it is not a list of number pairs.
 */
export function asCurve(value: unknown): Curve | null {
  if (!Array.isArray(value)) return null;
  const out: Curve = [];
  for (const item of value) {
    if (!Array.isArray(item) || item.length !== 2) return null;
    const [outside, water] = item as unknown[];
    if (typeof outside !== 'number' || typeof water !== 'number') return null;
    out.push([outside, water]);
  }
  return out;
}

export interface DensityBin {
  outside: number;
  low: number;
  high: number;
  median: number;
  count: number;
}

function quantile(sorted: number[], q: number): number {
  if (sorted.length === 0) return NaN;
  const position = (sorted.length - 1) * q;
  const below = Math.floor(position);
  const above = Math.ceil(position);
  const low = sorted[below] as number;
  const high = sorted[above] as number;
  return low + (high - low) * (position - below);
}

/**
 * Group (outside, water) samples into outside-temperature bins of `width` °C, each with the
 * 10–90 % water range, the median and the count; bins in outside order.
 */
export function densityBins(samples: [number, number][], width = 1): DensityBin[] {
  const groups = new Map<number, number[]>();
  for (const [outside, water] of samples) {
    if (!Number.isFinite(outside) || !Number.isFinite(water)) continue;
    const key = Math.round(outside / width) * width;
    const list = groups.get(key);
    if (list) list.push(water);
    else groups.set(key, [water]);
  }
  return [...groups.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([outside, values]) => {
      const sorted = [...values].sort((a, b) => a - b);
      return {
        outside,
        low: quantile(sorted, 0.1),
        high: quantile(sorted, 0.9),
        median: quantile(sorted, 0.5),
        count: sorted.length,
      };
    });
}

/**
 * Outside temperatures where either curve has a corner, plus the ends, sorted and unique: the
 * samples that draw both curves and the area between them exactly.
 */
export function cornerSamples(a: Curve, b: Curve, from: number, to: number): number[] {
  const xs = new Set<number>([from, to]);
  for (const [outside] of [...a, ...b]) if (outside > from && outside < to) xs.add(outside);
  return [...xs].sort((x, y) => x - y);
}

export interface CurveShift {
  at: number;
  shift: number;
}

/**
 * Largest absolute water difference `next − before` over whole outside degrees in [from, to].
 */
export function largestShift(before: Curve, next: Curve, from = -15, to = 20): CurveShift {
  let best: CurveShift = { at: from, shift: 0 };
  for (let outside = from; outside <= to; outside += 1) {
    const shift = curveWater(next, outside) - curveWater(before, outside);
    if (Math.abs(shift) > Math.abs(best.shift) + 1e-9) best = { at: outside, shift };
  }
  return best;
}
