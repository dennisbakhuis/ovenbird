import { numericPoints, runLengthSegments, type Point, type StateSegment } from '$lib/core/chart';
import { copOf } from '$lib/core/chartSummary';
import type { History, HistoryPoint } from '$lib/core/types';

export interface RunStats {
  starts: number;
  defrosts: number;
  runsS: number[];
  meanRunS: number | null;
  shortestRunS: number | null;
  longestRunS: number | null;
  windowS: number;
}

function samples(points: HistoryPoint[]): [number, number][] {
  const out: [number, number][] = [];
  for (const [iso, value] of points) {
    const at = Date.parse(iso);
    if (Number.isFinite(at) && typeof value === 'number') out.push([at, value]);
  }
  return out;
}

/**
 * Compressor starts, completed run lengths and defrost starts in a history window. A run is a
 * stretch of samples with a positive compressor frequency; runs cut off by the window edges are
 * not counted as starts or completed runs.
 */
export function runStats(frequency: HistoryPoint[], defrost: HistoryPoint[]): RunStats {
  const freq = samples(frequency);
  const runs: number[] = [];
  let starts = 0;
  let runStart: number | null = null;
  freq.forEach(([at, value], i) => {
    const running = value > 0;
    if (running && runStart === null) {
      runStart = at;
      if (i > 0) starts += 1;
    } else if (!running && runStart !== null) {
      if (freq[0] && runStart > freq[0][0]) runs.push((at - runStart) / 1000);
      runStart = null;
    }
  });
  const flags = samples(defrost);
  let defrosts = 0;
  flags.forEach(([, value], i) => {
    if (value > 0 && i > 0 && (flags[i - 1]?.[1] ?? 0) <= 0) defrosts += 1;
  });
  const first = freq[0]?.[0];
  const last = freq[freq.length - 1]?.[0];
  return {
    starts,
    defrosts,
    runsS: runs,
    meanRunS: runs.length ? runs.reduce((a, b) => a + b, 0) / runs.length : null,
    shortestRunS: runs.length ? Math.min(...runs) : null,
    longestRunS: runs.length ? Math.max(...runs) : null,
    windowS: first !== undefined && last !== undefined ? (last - first) / 1000 : 0,
  };
}

/**
 * Coefficient of performance estimate from heat production and electrical consumption in W;
 * null while the pump draws (almost) no power.
 */
export function copEstimate(production: unknown, consumption: unknown): number | null {
  if (typeof production !== 'number' || typeof consumption !== 'number') return null;
  return consumption > 50 ? production / consumption : null;
}

/**
 * Scale a count in a window to a per-day figure.
 */
export function perDay(count: number, windowS: number): number | null {
  return windowS > 0 ? (count * 86_400) / windowS : null;
}

export const LANE_GAP_MS = 20 * 60_000;
export const MIN_SCATTER_ELECTRIC_W = 300;

export interface DaySegments {
  compressor: StateSegment[];
  defrost: StateSegment[];
  dhw: StateSegment[];
  quiet: StateSegment[];
}

const seriesOf = (history: History | null, id: string): Point[] =>
  numericPoints(history?.series[id]?.points ?? []);

/**
 * Run-length segments of the compressor (shaded by frequency), defrost, hot water (three-way
 * valve towards the tank) and quiet mode from a history window.
 */
export function daySegments(history: History | null, to: number): DaySegments {
  const options = { endT: to, gapMs: LANE_GAP_MS };
  const frequency = seriesOf(history, 'main/Compressor_Freq');
  const top = Math.max(1, ...frequency.map(([, v]) => v));
  const on = (value: number) => (value > 0 ? 'on' : null);
  return {
    compressor: runLengthSegments(frequency, on, { ...options, level: (v) => v / top }),
    defrost: runLengthSegments(seriesOf(history, 'main/Defrosting_State'), on, options),
    dhw: runLengthSegments(seriesOf(history, 'main/ThreeWay_Valve_State'), on, options),
    quiet: runLengthSegments(seriesOf(history, 'main/Quiet_Mode_Level'), on, options),
  };
}

/**
 * Outlet minus inlet at the timestamps both are reported.
 */
export function deltaSeries(outlet: Point[], inlet: Point[]): Point[] {
  const inletAt = new Map(inlet.map(([t, v]) => [t, v]));
  return outlet.flatMap(([t, v]): Point[] => {
    const other = inletAt.get(t);
    return other === undefined ? [] : [[t, v - other]];
  });
}

export interface DutyReading {
  duty: number | null;
  max: number | null;
  above: boolean;
}

/**
 * The pump duty against its configured maximum. During a defrost the pump drives its own duty
 * above the setting, so `above` is a fact to show, not an error.
 */
export function dutyReading(duty: number | null, max: number | null): DutyReading {
  return { duty, max, above: duty !== null && max !== null && duty > max };
}

export interface CopDot {
  t: number;
  outside: number;
  cop: number;
}

export interface CopFit {
  slope: number;
  intercept: number;
}

/**
 * One dot per timestamp with outside temperature, electric and heat power: COP from copOf,
 * dropping hours with (almost) no electric draw. Series are matched on identical timestamps.
 */
export function copDots(
  outside: Point[],
  electricW: Point[],
  heatW: Point[],
  minElectricW = MIN_SCATTER_ELECTRIC_W,
): CopDot[] {
  const electric = new Map(electricW);
  const heat = new Map(heatW);
  return outside.flatMap(([t, temperature]): CopDot[] => {
    const e = electric.get(t);
    const h = heat.get(t);
    if (e === undefined || h === undefined || e < minElectricW) return [];
    const cop = copOf(e, h);
    return cop === null ? [] : [{ t, outside: temperature, cop }];
  });
}

/**
 * Least-squares line of COP over outside temperature; null with fewer than five dots or no
 * spread in temperature.
 */
export function copFit(dots: CopDot[]): CopFit | null {
  if (dots.length < 5) return null;
  const n = dots.length;
  const mx = dots.reduce((s, d) => s + d.outside, 0) / n;
  const my = dots.reduce((s, d) => s + d.cop, 0) / n;
  const sxx = dots.reduce((s, d) => s + (d.outside - mx) ** 2, 0);
  if (sxx < 1e-9) return null;
  const sxy = dots.reduce((s, d) => s + (d.outside - mx) * (d.cop - my), 0);
  const slope = sxy / sxx;
  return { slope, intercept: my - slope * mx };
}

/**
 * Readable fallback for a catalogue label without a translation: "compensation_curve" becomes
 * "Compensation curve".
 */
export function humanizeLabel(label: string): string {
  const words = label.split('_').filter(Boolean);
  const text = words.join(' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
