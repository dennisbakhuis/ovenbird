/**
 * Fixed series colours of the chart kit. Each reads its theme token from `app.css`, which
 * defines it for the light and the dark theme.
 */
export const SERIES = {
  outside: 'var(--series-outside)',
  outlet: 'var(--series-outlet)',
  inlet: 'var(--series-inlet)',
  setpoint: 'var(--series-setpoint)',
  room: 'var(--series-room)',
  comfort: 'var(--series-comfort)',
  electric: 'var(--series-electric)',
  heat: 'var(--series-heat)',
  ambient: 'var(--series-ambient)',
  defrost: 'var(--series-defrost)',
  dhw: 'var(--series-dhw)',
  quiet: 'var(--series-quiet)',
  compressor: 'var(--series-compressor)',
  hold: 'var(--series-hold)',
  forecast: 'var(--series-forecast)',
  neutral: 'var(--series-neutral)',
} as const;

export const STATUS = {
  ok: 'var(--status-ok)',
  warn: 'var(--status-warn)',
  critical: 'var(--status-critical)',
} as const;

export const NIGHT_FILL = 'var(--chart-night)';

export type SeriesName = keyof typeof SERIES;
