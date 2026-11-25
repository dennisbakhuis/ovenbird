import type { LaneSpec } from '$components/charts/types';
import { GLYPHS } from '$components/charts/glyphs';
import { SERIES } from '$components/charts/palette';
import { mergeRuns, numericPoints, runLengthSegments, type Point } from '$lib/core/chart';
import { dayEnergy, startOfLocalDay, type DayEnergy } from '$lib/home/energy';
import { hotWaterLanes } from '$lib/core/hotWater.svelte';
import { daySegments, runStats } from '$lib/pump/pumpStats';
import type { InsightDaily, InsightDay } from '$lib/house/insight';
import type { History, HistoryPoint } from '$lib/core/types';

export const COMFORT_HALF_BAND_K = 0.5;
export const LANE_GAP_MS = 20 * 60_000;

export const SIGNAL = {
  outside: 'main/Outside_Temp',
  outlet: 'main/Main_Outlet_Temp',
  inlet: 'main/Main_Inlet_Temp',
  electric: 'main/Heat_Power_Consumption',
  heat: 'main/Heat_Power_Production',
  frequency: 'main/Compressor_Freq',
  defrost: 'main/Defrosting_State',
  valve: 'main/ThreeWay_Valve_State',
  quiet: 'main/Quiet_Mode_Level',
} as const;

export const DAY_SIGNALS: string[] = Object.values(SIGNAL);

export type RangeKey = '6h' | '24h' | '7d';

export const RANGE_MS: Record<RangeKey, number> = {
  '6h': 6 * 3_600_000,
  '24h': 24 * 3_600_000,
  '7d': 7 * 24 * 3_600_000,
};

export interface LaneLabels {
  compressor: string;
  defrost: string;
  dhw: string;
  quiet: string;
  on: string;
}

/**
 * Numeric points of one history series; empty when the series is absent.
 */
export function seriesPoints(history: History | null, id: string): Point[] {
  return numericPoints(history?.series[id]?.points ?? []);
}

/**
 * State lanes of the day strip: compressor (shaded by frequency), defrost, hot water (three-way
 * valve towards the tank) and quiet mode. With hot water hidden its lane only shows runs, under a
 * neutral glyph.
 */
export function buildLanes(
  history: History | null,
  to: number,
  labels: LaneLabels,
  hotWater = true,
): LaneSpec[] {
  const options = { endT: to, gapMs: LANE_GAP_MS };
  const frequency = seriesPoints(history, SIGNAL.frequency);
  const top = Math.max(1, ...frequency.map(([, v]) => v));
  const on = (value: number) => (value > 0 ? 'on' : null);
  const lanes: LaneSpec[] = [
    {
      id: 'compressor',
      label: labels.compressor,
      icon: GLYPHS.fan,
      color: SERIES.compressor,
      segments: runLengthSegments(frequency, on, { ...options, level: (v) => v / top }),
      states: { on: { label: labels.on } },
    },
    {
      id: 'defrost',
      label: labels.defrost,
      icon: GLYPHS.snowflake,
      color: SERIES.defrost,
      segments: runLengthSegments(seriesPoints(history, SIGNAL.defrost), on, options),
      states: { on: { label: labels.on } },
    },
    {
      id: 'dhw',
      label: labels.dhw,
      icon: GLYPHS.tap,
      color: SERIES.dhw,
      segments: runLengthSegments(seriesPoints(history, SIGNAL.valve), on, options),
      states: { on: { label: labels.on } },
    },
    {
      id: 'quiet',
      label: labels.quiet,
      icon: GLYPHS.moon,
      color: SERIES.quiet,
      segments: runLengthSegments(seriesPoints(history, SIGNAL.quiet), on, options),
      states: { on: { label: labels.on } },
    },
  ];
  return hotWaterLanes(lanes, hotWater);
}

export interface TodayStats {
  energy: DayEnergy;
  starts: number;
  defrosts: number;
  meanRunS: number | null;
  longestRunS: number | null;
}

/**
 * Energy, COP and compressor starts since `since` (default: the browser's local midnight) from a
 * day-long history.
 */
export function todayStats(
  history: History | null,
  nowMs: number,
  dayStart: number | null = null,
): TodayStats | null {
  if (!history) return null;
  const midnight = dayStart ?? startOfLocalDay(nowMs);
  const energy = dayEnergy(
    seriesPoints(history, SIGNAL.electric),
    seriesPoints(history, SIGNAL.heat),
    midnight,
    nowMs,
  );
  const since = (id: string): HistoryPoint[] =>
    (history.series[id]?.points ?? []).filter(([iso]) => Date.parse(iso) >= midnight);
  const runs = runStats(since(SIGNAL.frequency), since(SIGNAL.defrost));
  return {
    energy,
    starts: runs.starts,
    defrosts: runs.defrosts,
    meanRunS: runs.meanRunS,
    longestRunS: runs.longestRunS,
  };
}

export interface LastRun {
  from: number;
  to: number;
  running: boolean;
}

/**
 * The most recent compressor run in a day-long history; `running` when it lasts up to `nowMs`.
 */
export function lastRunOf(history: History | null, nowMs: number): LastRun | null {
  if (!history) return null;
  const runs = mergeRuns(daySegments(history, nowMs).compressor);
  const last = runs[runs.length - 1];
  if (!last) return null;
  return { from: last.from, to: last.to, running: nowMs - last.to < 120_000 };
}

/**
 * Today's entry of `insight/daily` (the last day, marked partial), or null.
 */
export function insightToday(daily: InsightDaily | null): InsightDay | null {
  const last = daily?.days[daily.days.length - 1] ?? null;
  return last && last.partial ? last : null;
}

/**
 * Start of today in the service's time zone, from `insight/daily`; null without it.
 */
export function serviceMidnight(daily: InsightDaily | null): number | null {
  const today = insightToday(daily);
  const from = today ? Date.parse(today.from) : NaN;
  return Number.isFinite(from) ? from : null;
}

/**
 * Today's figures with the service's definition of "today": energy, COP, starts and defrosts from
 * `insight/daily` where it has them; the mean and longest run from the completed runs in the
 * history since the service's midnight, so the mean never exceeds the longest (the service's
 * `run_s` also counts the run carried over from before midnight and the one in progress). Without
 * runs in the history the mean falls back to `run_s / starts`.
 */
export function withDaily(stats: TodayStats | null, today: InsightDay | null): TodayStats | null {
  if (!today) return stats;
  const starts = today.compressor_starts ?? stats?.starts ?? null;
  if (starts === null && !stats) return null;
  const meanRunS =
    stats?.meanRunS ??
    (today.run_s !== null && starts !== null && starts > 0 ? today.run_s / starts : null);
  return {
    energy: {
      electricKwh: today.electric_kwh ?? stats?.energy.electricKwh ?? 0,
      heatKwh: today.heat_kwh ?? stats?.energy.heatKwh ?? 0,
      cop: today.cop ?? stats?.energy.cop ?? null,
      coverage: today.coverage ?? stats?.energy.coverage ?? 0,
    },
    starts: starts ?? 0,
    defrosts: today.defrosts ?? stats?.defrosts ?? 0,
    meanRunS,
    longestRunS: stats?.longestRunS ?? null,
  };
}

/**
 * The service's time zone when it differs from the browser's, else null.
 */
export function foreignZone(
  daily: InsightDaily | null,
  browserZone: string = Intl.DateTimeFormat().resolvedOptions().timeZone,
): string | null {
  const zone = daily?.timezone ?? null;
  if (!zone || zone === browserZone) return null;
  const now = Date.now();
  const offset = (timeZone: string) => {
    try {
      return new Intl.DateTimeFormat('en-US', { timeZone, timeZoneName: 'longOffset' })
        .formatToParts(now)
        .find((part) => part.type === 'timeZoneName')?.value;
    } catch {
      return undefined;
    }
  };
  const same = offset(zone);
  return same !== undefined && same === offset(browserZone) ? null : zone;
}

/**
 * Electricity used yesterday from its midnight up to the same time of day as now, from a history
 * of that window; null when less than half of it has data.
 */
export function yesterdaySoFar(history: History | null, from: number, to: number): number | null {
  if (!history || to <= from) return null;
  const energy = dayEnergy(
    seriesPoints(history, SIGNAL.electric),
    seriesPoints(history, SIGNAL.heat),
    from,
    to,
  );
  return energy.coverage >= 0.5 ? energy.electricKwh : null;
}
