import { copOf } from '$lib/core/chartSummary';
import type { Point } from '$lib/core/chart';

export interface EnergyResult {
  kwh: number;
  coveredMs: number;
  missingMs: number;
}

export interface EnergyOptions {
  maxGapMs?: number;
}

export interface DayEnergy {
  electricKwh: number;
  heatKwh: number;
  cop: number | null;
  coverage: number;
}

export const DEFAULT_MAX_GAP_MS = 20 * 60_000;

/**
 * Start of the local calendar day containing `ms`.
 */
export function startOfLocalDay(ms: number): number {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

/**
 * Integrate a power series in W over [from, to] into kWh. Each sample holds its value until the
 * next sample, at most `maxGapMs` (default 20 min); the last sample holds until `to` within the
 * same limit. Time without a sample inside the window is reported as `missingMs`, not guessed.
 * Samples before `from` count only for the part inside the window; negative power counts as 0.
 */
export function integrateEnergy(
  points: Point[],
  from: number,
  to: number,
  options: EnergyOptions = {},
): EnergyResult {
  const maxGap = options.maxGapMs ?? DEFAULT_MAX_GAP_MS;
  const samples = points
    .filter(([t, v]) => Number.isFinite(t) && Number.isFinite(v))
    .sort((a, b) => a[0] - b[0]);
  let joules = 0;
  let covered = 0;
  samples.forEach(([t, value], i) => {
    const next = samples[i + 1];
    const holdEnd = Math.min(next ? next[0] : to, t + maxGap);
    const start = Math.max(t, from);
    const end = Math.min(holdEnd, to);
    if (end <= start) return;
    joules += Math.max(value, 0) * ((end - start) / 1000);
    covered += end - start;
  });
  const window = Math.max(to - from, 0);
  return { kwh: joules / 3_600_000, coveredMs: covered, missingMs: Math.max(window - covered, 0) };
}

/**
 * Electric and heat energy over [from, to] from W series, with the COP of the totals (null
 * without both) and the covered share of the window (0–1).
 */
export function dayEnergy(
  electricW: Point[],
  heatW: Point[],
  from: number,
  to: number,
  options: EnergyOptions = {},
): DayEnergy {
  const electric = integrateEnergy(electricW, from, to, options);
  const heat = integrateEnergy(heatW, from, to, options);
  const window = Math.max(to - from, 1);
  return {
    electricKwh: electric.kwh,
    heatKwh: heat.kwh,
    cop: copOf(electric.kwh * 1000, heat.kwh * 1000),
    coverage: Math.min(electric.coveredMs, heat.coveredMs) / window,
  };
}
