import { mergeRuns, timeTicks, valueAt, type Point, type StateSegment } from './chart';
import { timeLocale } from './format';
import { minus } from './minus';
import type { Language } from '$lib/i18n';

const STRINGS = {
  en: {
    showTable: 'Show as table',
    hideTable: 'Hide table',
    downloadCsv: 'Download CSV',
    showList: 'Show as list',
    hideList: 'Hide list',
    latest: 'Latest',
    time: 'Time',
    noData: 'no data',
    cursor: '{title}: time cursor',
    cursorIdle: 'Use the arrow keys to read values over time',
    rising: 'rising {value} per hour',
    falling: 'falling {value} per hour',
    steady: 'steady',
    range: 'range {min}–{max}',
    belowTarget: '{delta} below target {target}',
    aboveTarget: '{delta} above target {target}',
    onTarget: 'on target {target}',
    inBand: 'within the comfort band',
    belowBand: 'below the comfort band {low}–{high}',
    aboveBand: 'above the comfort band {low}–{high}',
    flip: 'changes at {value}',
    times: '{count} times',
    once: 'once',
    inTotal: '{duration} in total',
    off: 'off',
    on: 'on',
    none: 'none',
    limitAbove: 'alarm above {limit}',
    limitBelow: 'alarm below {limit}',
    margin: '{margin} margin',
    exceededAbove: 'above the alarm limit {limit} by {delta}',
    exceededBelow: 'below the alarm limit {limit} by {delta}',
    noLimit: 'no limit',
    highest: 'highest {value} ({label})',
    lowest: 'lowest {value} ({label})',
    mean: 'mean {value}',
    electric: 'Electric',
    heat: 'Heat',
    ambient: 'from the air',
    cop: 'COP',
    flowRunning:
      'Electric {electric} in, heat {heat} out, of which {ambient} from the outside air, COP {cop}',
    flowNoHeat: 'Electric {electric} in, no heat out',
    flowIdle: 'Idle: no electric input or heat output',
    flowUnknown: 'Power not available',
    lessThanMinute: '<1 min',
    hours: '{h} h',
    minutes: '{m} min',
    hidden: 'hidden',
  },
  nl: {
    showTable: 'Toon als tabel',
    hideTable: 'Verberg tabel',
    downloadCsv: 'CSV downloaden',
    showList: 'Toon als lijst',
    hideList: 'Verberg lijst',
    latest: 'Laatst',
    time: 'Tijd',
    noData: 'geen gegevens',
    cursor: '{title}: tijdcursor',
    cursorIdle: 'Gebruik de pijltjestoetsen om waarden in de tijd te lezen',
    rising: 'stijgend {value} per uur',
    falling: 'dalend {value} per uur',
    steady: 'stabiel',
    range: 'bereik {min}–{max}',
    belowTarget: '{delta} onder doel {target}',
    aboveTarget: '{delta} boven doel {target}',
    onTarget: 'op doel {target}',
    inBand: 'binnen de comfortband',
    belowBand: 'onder de comfortband {low}–{high}',
    aboveBand: 'boven de comfortband {low}–{high}',
    flip: 'verandert bij {value}',
    times: '{count} keer',
    once: 'één keer',
    inTotal: '{duration} in totaal',
    off: 'uit',
    on: 'aan',
    none: 'geen',
    limitAbove: 'alarm boven {limit}',
    limitBelow: 'alarm onder {limit}',
    margin: '{margin} marge',
    exceededAbove: 'boven de alarmgrens {limit}, {delta} te hoog',
    exceededBelow: 'onder de alarmgrens {limit}, {delta} te laag',
    noLimit: 'geen grens',
    highest: 'hoogste {value} ({label})',
    lowest: 'laagste {value} ({label})',
    mean: 'gemiddeld {value}',
    electric: 'Elektrisch',
    heat: 'Warmte',
    ambient: 'uit de lucht',
    cop: 'COP',
    flowRunning:
      'Elektrisch {electric} in, warmte {heat} uit, waarvan {ambient} uit de buitenlucht, COP {cop}',
    flowNoHeat: 'Elektrisch {electric} in, geen warmte uit',
    flowIdle: 'In rust: geen elektrisch verbruik of warmte',
    flowUnknown: 'Vermogen niet beschikbaar',
    lessThanMinute: '<1 min',
    hours: '{h} u',
    minutes: '{m} min',
    hidden: 'verborgen',
  },
} as const;

export type ChartTextKey = keyof (typeof STRINGS)['en'];

/**
 * Chart kit text in the given language with `{name}` parameters filled in.
 */
export function chartText(
  lang: Language,
  key: ChartTextKey,
  params: Record<string, string | number> = {},
): string {
  const template: string = (STRINGS[lang] ?? STRINGS.en)[key];
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? ''));
}

const NARROW_SPACE = ' ';
const numberFormats = new Map<string, Intl.NumberFormat>();
const clockFormats = new Map<string, Intl.DateTimeFormat>();

/**
 * A number with at most `digits` decimals in the language's notation.
 */
export function formatNum(value: number, digits: number, lang: Language): string {
  const key = `${lang}:${digits}`;
  let format = numberFormats.get(key);
  if (!format) {
    format = new Intl.NumberFormat(lang, { maximumFractionDigits: digits });
    numberFormats.set(key, format);
  }
  const text = format.format(value);
  return minus(text === '-0' ? '0' : text);
}

/**
 * A value with its unit separated by a narrow no-break space; "–" for null.
 */
export function formatValue(
  value: number | null | undefined,
  unit: string,
  digits: number,
  lang: Language,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '–';
  const text = formatNum(value, digits, lang);
  return unit ? `${text}${NARROW_SPACE}${unit}` : text;
}

/**
 * Unit of a difference: kelvin for temperatures, the unit itself otherwise.
 */
export function deltaUnit(unit: string): string {
  return unit === '°C' ? 'K' : unit;
}

/**
 * 24-hour clock time, with the weekday when `withDay` is set.
 */
export function formatClockTime(t: number, lang: Language, withDay = false): string {
  const key = `${lang}:${withDay}`;
  let format = clockFormats.get(key);
  if (!format) {
    format = new Intl.DateTimeFormat(timeLocale(lang), {
      weekday: withDay ? 'short' : undefined,
      hour: '2-digit',
      minute: '2-digit',
    });
    clockFormats.set(key, format);
  }
  return format.format(t);
}

/**
 * Duration as "2 h 30 min", "45 min" or "<1 min".
 */
export function formatDuration(ms: number, lang: Language): string {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 1) return chartText(lang, 'lessThanMinute');
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const parts: string[] = [];
  if (h > 0) parts.push(chartText(lang, 'hours', { h }));
  if (m > 0 || h === 0) parts.push(chartText(lang, 'minutes', { m }));
  return parts.join(' ');
}

export interface SeriesStats {
  first: number;
  last: number;
  min: number;
  max: number;
  mean: number;
  count: number;
}

/**
 * First, last, min, max and mean of a point list; null when empty.
 */
export function seriesStats(points: Point[]): SeriesStats | null {
  const values = points.map(([, v]) => v).filter((v) => Number.isFinite(v));
  if (values.length === 0) return null;
  let min = Infinity;
  let max = -Infinity;
  let sum = 0;
  for (const v of values) {
    min = Math.min(min, v);
    max = Math.max(max, v);
    sum += v;
  }
  return {
    first: values[0] as number,
    last: values[values.length - 1] as number,
    min,
    max,
    mean: sum / values.length,
    count: values.length,
  };
}

/**
 * Least-squares slope in units per hour over the last `windowMs` of data; null with fewer than
 * two points or less than ten minutes of data in the window.
 */
export function trendPerHour(points: Point[], windowMs = 3 * 3_600_000): number | null {
  const last = points[points.length - 1];
  if (!last) return null;
  const recent = points.filter(([t, v]) => t >= last[0] - windowMs && Number.isFinite(v));
  const first = recent[0];
  if (recent.length < 2 || !first || last[0] - first[0] < 600_000) return null;
  const n = recent.length;
  const meanT = recent.reduce((s, [t]) => s + t, 0) / n;
  const meanV = recent.reduce((s, [, v]) => s + v, 0) / n;
  let num = 0;
  let den = 0;
  for (const [t, v] of recent) {
    num += (t - meanT) * (v - meanV);
    den += (t - meanT) ** 2;
  }
  return den === 0 ? 0 : (num / den) * 3_600_000;
}

export type TrendDirection = 'rising' | 'falling' | 'steady';

/**
 * Direction of a per-hour trend, steady within ±`threshold`.
 */
export function trendDirection(slope: number | null, threshold = 0.05): TrendDirection {
  if (slope === null || Math.abs(slope) < threshold) return 'steady';
  return slope > 0 ? 'rising' : 'falling';
}

/**
 * "falling 0.2 K per hour" or "steady".
 */
export function describeTrend(
  slope: number | null,
  unit: string,
  lang: Language,
  threshold = 0.05,
): string {
  const direction = trendDirection(slope, threshold);
  if (direction === 'steady' || slope === null) return chartText(lang, 'steady');
  return chartText(lang, direction, {
    value: formatValue(Math.abs(slope), deltaUnit(unit), 1, lang),
  });
}

/**
 * One series in a sentence: "Room 21.2 °C, range 20.9–21.6 °C, falling 0.2 K per hour".
 */
export function describeSeries(
  label: string,
  unit: string,
  points: Point[],
  lang: Language,
  digits = 1,
): string {
  const stats = seriesStats(points);
  if (!stats) return `${label}: ${chartText(lang, 'noData')}`;
  const parts = [`${label} ${formatValue(stats.last, unit, digits, lang)}`];
  if (stats.max - stats.min > 0) {
    parts.push(
      chartText(lang, 'range', {
        min: formatNum(stats.min, digits, lang),
        max: formatValue(stats.max, unit, digits, lang),
      }),
    );
  }
  parts.push(describeTrend(trendPerHour(points), unit, lang));
  return parts.join(', ');
}

export interface SummarySeries {
  label: string;
  unit: string;
  points: Point[];
  digits?: number;
}

export interface SummaryLane {
  label: string;
  segments: StateSegment[];
  states?: Record<string, { label: string }>;
  events?: { at: number; text: string }[];
}

/**
 * Text alternative for a time chart: title and time span, then one sentence per series and lane.
 */
export function describeTimeChart(
  title: string,
  from: number,
  to: number,
  series: SummarySeries[],
  lanes: SummaryLane[],
  lang: Language,
): string {
  const withDay = to - from > 40 * 3_600_000;
  const head = `${title}, ${formatClockTime(from, lang, withDay)}–${formatClockTime(to, lang, withDay)}`;
  const body = [
    ...series.map((s) => describeSeries(s.label, s.unit, s.points, lang, s.digits ?? 1)),
    ...lanes.map((lane) => describeLane(lane, lang)),
  ];
  return [head, ...body].join('. ') + '.';
}

/**
 * One lane in a sentence: "Compressor: on 4 times, 14 h 20 min in total".
 */
export function describeLane(lane: SummaryLane, lang: Language): string {
  if (lane.events) {
    const n = lane.events.length;
    if (n === 0) return `${lane.label}: ${chartText(lang, 'none')}`;
    return `${lane.label}: ${n === 1 ? chartText(lang, 'once') : chartText(lang, 'times', { count: n })}`;
  }
  const runs = mergeRuns(lane.segments);
  if (runs.length === 0) return `${lane.label}: ${chartText(lang, 'none')}`;
  const order: string[] = [];
  const totals = new Map<string, { count: number; ms: number }>();
  for (const run of runs) {
    const entry = totals.get(run.state) ?? { count: 0, ms: 0 };
    if (!totals.has(run.state)) order.push(run.state);
    entry.count += 1;
    entry.ms += run.to - run.from;
    totals.set(run.state, entry);
  }
  const parts = order.map((state) => {
    const entry = totals.get(state) as { count: number; ms: number };
    const name = lane.states?.[state]?.label;
    const count =
      entry.count === 1
        ? chartText(lang, 'once')
        : chartText(lang, 'times', { count: entry.count });
    const total = chartText(lang, 'inTotal', { duration: formatDuration(entry.ms, lang) });
    return `${name && name !== lane.label ? `${name} ` : ''}${count}, ${total}`;
  });
  return `${lane.label}: ${parts.join('; ')}`;
}

/**
 * One moment of a point-event lane: "12:19 · Water setpoint 32 · failed".
 */
export function describeEvent(
  event: { at: number; text: string },
  lang: Language,
  withDay = false,
): string {
  return `${formatClockTime(event.at, lang, withDay)} · ${event.text}`;
}

/**
 * One segment for a list: "06:10–08:40, on, 2 h 30 min".
 */
export function describeSegment(
  segment: StateSegment,
  stateLabel: string,
  lang: Language,
  withDay = false,
): string {
  const span = `${formatClockTime(segment.from, lang, withDay)}–${formatClockTime(segment.to, lang, withDay)}`;
  return `${span}, ${stateLabel}, ${formatDuration(segment.to - segment.from, lang)}`;
}

export interface BandDescription {
  label: string;
  value: number | null;
  unit: string;
  low: number;
  high: number;
  target?: number | null;
  trend?: number | null;
  flip?: number | null;
  digits?: number;
}

export type BandState = 'below' | 'within' | 'above';

/**
 * Where a value sits relative to [low, high].
 */
export function bandState(value: number, low: number, high: number): BandState {
  if (value < low) return 'below';
  if (value > high) return 'above';
  return 'within';
}

/**
 * Comfort meter in a sentence: "Room 20.4 °C, 0.6 K below target 21 °C, below the comfort
 * band 20.5–21.5 °C, falling 0.2 K per hour".
 */
export function describeBand(d: BandDescription, lang: Language): string {
  const digits = d.digits ?? 1;
  if (d.value === null) return `${d.label}: ${chartText(lang, 'noData')}`;
  const parts = [`${d.label} ${formatValue(d.value, d.unit, digits, lang)}`];
  if (d.target !== null && d.target !== undefined) {
    const delta = d.value - d.target;
    const target = formatValue(d.target, d.unit, digits, lang);
    const deltaText = formatValue(Math.abs(delta), deltaUnit(d.unit), digits, lang);
    if (Math.abs(delta) < 0.5 * 10 ** -digits) parts.push(chartText(lang, 'onTarget', { target }));
    else
      parts.push(
        chartText(lang, delta < 0 ? 'belowTarget' : 'aboveTarget', { delta: deltaText, target }),
      );
  }
  const state = bandState(d.value, d.low, d.high);
  const low = formatNum(d.low, digits, lang);
  const high = formatValue(d.high, d.unit, digits, lang);
  parts.push(
    chartText(lang, state === 'within' ? 'inBand' : state === 'below' ? 'belowBand' : 'aboveBand', {
      low,
      high,
    }),
  );
  if (d.trend !== undefined) parts.push(describeTrend(d.trend, d.unit, lang));
  if (d.flip !== null && d.flip !== undefined)
    parts.push(chartText(lang, 'flip', { value: formatValue(d.flip, d.unit, digits, lang) }));
  return parts.join(', ');
}

export interface BulletDescription {
  label: string;
  value: number | null;
  unit: string;
  limit: number | null;
  direction: 'above' | 'below';
  digits?: number;
}

/**
 * Whether a value is past its limit in the alarm direction.
 */
export function limitBreached(
  value: number | null,
  limit: number | null,
  direction: 'above' | 'below',
): boolean {
  if (value === null || limit === null) return false;
  return direction === 'above' ? value >= limit : value <= limit;
}

/**
 * Monitor in a sentence: "Outlet 30.8 °C, alarm above 45 °C, 14.2 K margin".
 */
export function describeBullet(d: BulletDescription, lang: Language): string {
  const digits = d.digits ?? 1;
  if (d.value === null) return `${d.label}: ${chartText(lang, 'noData')}`;
  const head = `${d.label} ${formatValue(d.value, d.unit, digits, lang)}`;
  if (d.limit === null) return `${head}, ${chartText(lang, 'noLimit')}`;
  const limit = formatValue(d.limit, d.unit, digits, lang);
  const delta = formatValue(Math.abs(d.limit - d.value), deltaUnit(d.unit), digits, lang);
  if (limitBreached(d.value, d.limit, d.direction)) {
    return `${head}, ${chartText(lang, d.direction === 'above' ? 'exceededAbove' : 'exceededBelow', { limit, delta })}`;
  }
  return `${head}, ${chartText(lang, d.direction === 'above' ? 'limitAbove' : 'limitBelow', { limit })}, ${chartText(lang, 'margin', { margin: delta })}`;
}

export interface BarDatum {
  label: string;
  value: number | null;
}

/**
 * Bars in a sentence: every value when there are at most eight, else lowest, highest and mean.
 */
export function describeBars(
  title: string,
  items: BarDatum[],
  unit: string,
  lang: Language,
  digits = 1,
): string {
  const known = items.filter((i): i is { label: string; value: number } => i.value !== null);
  if (known.length === 0) return `${title}: ${chartText(lang, 'noData')}`;
  if (items.length <= 8) {
    const list = items.map((i) => `${i.label} ${formatValue(i.value, unit, digits, lang)}`);
    return `${title}: ${list.join(', ')}`;
  }
  let low = known[0] as { label: string; value: number };
  let high = low;
  let sum = 0;
  for (const item of known) {
    if (item.value < low.value) low = item;
    if (item.value > high.value) high = item;
    sum += item.value;
  }
  return `${title}: ${[
    chartText(lang, 'lowest', {
      value: formatValue(low.value, unit, digits, lang),
      label: low.label,
    }),
    chartText(lang, 'highest', {
      value: formatValue(high.value, unit, digits, lang),
      label: high.label,
    }),
    chartText(lang, 'mean', { value: formatValue(sum / known.length, unit, digits, lang) }),
  ].join(', ')}`;
}

/**
 * Coefficient of performance: heat out over electric in when both are positive, else null.
 */
export function copOf(electricW: number | null, heatW: number | null): number | null {
  if (electricW === null || heatW === null || electricW <= 0 || heatW <= 0) return null;
  return heatW / electricW;
}

/**
 * Power flow in a sentence, in kW; idle when there is no heat and the electric draw is at most
 * `standbyW`.
 */
export function describePowerFlow(
  electricW: number | null,
  heatW: number | null,
  cop: number | null,
  lang: Language,
  standbyW = 0,
): string {
  if (electricW === null && heatW === null) return chartText(lang, 'flowUnknown');
  const electric = electricW ?? 0;
  const heat = heatW ?? 0;
  if (electric <= standbyW && heat <= 0) return chartText(lang, 'flowIdle');
  const kw = (w: number) => formatValue(w / 1000, 'kW', 1, lang);
  if (heat <= 0) return chartText(lang, 'flowNoHeat', { electric: kw(electric) });
  return chartText(lang, 'flowRunning', {
    electric: kw(electric),
    heat: kw(heat),
    ambient: kw(Math.max(heat - electric, 0)),
    cop: cop === null ? '–' : formatNum(cop, 1, lang),
  });
}

export interface TableSeries {
  points: Point[];
  step?: boolean;
  maxDistMs?: number;
}

export interface TableRow {
  t: number;
  values: (number | null)[];
}

/**
 * Rows for a "show as table" view: round times across [from, to] (about `maxRows`), each with
 * the value every series shows at that time.
 */
export function tableRows(
  series: TableSeries[],
  from: number,
  to: number,
  maxRows: number,
  maxDistMs: number,
): TableRow[] {
  return timeTicks(from, to, maxRows).map((t) => ({
    t,
    values: series.map(
      (s) =>
        valueAt(s.points, t, s.step ? 'step' : 'nearest', s.maxDistMs ?? maxDistMs)?.[1] ?? null,
    ),
  }));
}

/**
 * CSV rows of chart lines at every sample time of any line (ISO time first, then one column per
 * line; empty where a line has no value within `maxDistMs`).
 */
export function csvRows(
  series: { points: Point[]; step?: boolean; maxDistMs?: number }[],
  maxDistMs: number,
): (string | number | null)[][] {
  const times = [...new Set(series.flatMap((s) => s.points.map(([t]) => t)))].sort((a, b) => a - b);
  return times.map((t) => [
    new Date(t).toISOString(),
    ...series.map(
      (s) =>
        valueAt(s.points, t, s.step ? 'step' : 'nearest', s.maxDistMs ?? maxDistMs)?.[1] ?? null,
    ),
  ]);
}
