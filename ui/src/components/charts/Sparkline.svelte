<!--
  Sparkline: a small trend line for stat tiles (no axes).

  Props: points (Point[]), label (series name for the summary), unit, digits (1), color,
  height (36 px; width fills the container), from/to (x span, default the data span),
  step (hold values), area (soft fill under the line, default true), band ({lower, upper,
  color?}: e.g. comfort band), minMax (show "min–max" under the line), interactive (keyboard
  and pointer crosshair with a read-out; off by default so tiles do not add tab stops),
  summary (overrides the generated text), maxGapMs (break the line at gaps; step lines hold
  their value by default, which suits on-change sensors).
  A11y: role="img" with "Outlet 32.5 °C, range 28–32.5 °C, rising 0.4 K per hour"; when
  interactive a slider overlay reads values with ←/→, Home/End, Esc.
-->
<script lang="ts">
  import { areaPath, axisFor, stepPath, unionTimes, valueAt, type Point } from '$lib/core/chart';
  import {
    describeSeries,
    formatClockTime,
    formatNum,
    formatValue,
    seriesStats,
    chartText,
  } from '$lib/core/chartSummary';
  import { settings } from '$lib/core/settings.svelte';
  import Crosshair from './Crosshair.svelte';
  import { SERIES } from './palette';

  interface Props {
    points: Point[];
    label: string;
    unit?: string;
    digits?: number;
    color?: string;
    height?: number;
    from?: number;
    to?: number;
    step?: boolean;
    area?: boolean;
    band?: { lower: number; upper: number; color?: string } | null;
    minMax?: boolean;
    interactive?: boolean;
    summary?: string;
    maxGapMs?: number;
  }

  let {
    points,
    label,
    unit = '',
    digits = 1,
    color = SERIES.neutral,
    height = 36,
    from,
    to,
    step = false,
    area = true,
    band = null,
    minMax = false,
    interactive = false,
    summary,
    maxGapMs,
  }: Props = $props();

  let measured = $state(0);
  let cursor = $state<number | null>(null);
  const lang = $derived(settings.language);
  const width = $derived(measured > 0 ? measured : 160);
  const t0 = $derived(from ?? points[0]?.[0] ?? 0);
  const t1 = $derived(to ?? points[points.length - 1]?.[0] ?? 1);
  const gap = $derived(maxGapMs ?? (step ? Infinity : Math.max((t1 - t0) / 30, 20 * 60_000)));
  const axis = $derived(
    axisFor(
      [
        points,
        ...(band
          ? [
              [
                [t0, band.lower],
                [t0, band.upper],
              ] as Point[],
            ]
          : []),
      ],
      { pad: 0.1, snap: 1e-6 },
    ),
  );
  const PAD = 3;
  const sx = (t: number) => PAD + ((t - t0) / Math.max(t1 - t0, 1)) * (width - 2 * PAD);
  const sy = (v: number) =>
    axis
      ? PAD + (1 - (v - axis.min) / Math.max(axis.max - axis.min, 1e-9)) * (height - 2 * PAD)
      : height / 2;

  const line = $derived.by(() => {
    if (step) return stepPath(points, sx, sy, gap, t1);
    let path = '';
    let previous: number | null = null;
    for (const [t, v] of points) {
      path += `${previous === null || t - previous > gap ? 'M' : 'L'}${sx(t).toFixed(1)},${sy(v).toFixed(1)}`;
      previous = t;
    }
    return path;
  });
  const fill = $derived(
    area && axis && points.length > 1
      ? areaPath(
          points,
          points.map(([t]): Point => [t, axis.min]),
          sx,
          sy,
        )
      : '',
  );
  const last = $derived(points[points.length - 1] ?? null);
  const stats = $derived(seriesStats(points));
  const times = $derived(unionTimes([points]));
  const at = $derived(
    cursor === null ? null : valueAt(points, cursor, step ? 'step' : 'nearest', gap),
  );
  const text = $derived(summary ?? describeSeries(label, unit, points, lang, digits));
  const readout = $derived(
    cursor === null
      ? chartText(lang, 'cursorIdle')
      : `${formatClockTime(cursor, lang)}: ${label} ${formatValue(at?.[1] ?? null, unit, digits, lang)}`,
  );
</script>

<div class="spark" bind:clientWidth={measured} data-testid="sparkline">
  <div class="plot">
    <svg viewBox="0 0 {width} {height}" {width} {height} role="img" aria-label={text}>
      {#if band && axis}
        <rect
          x="0"
          y={sy(band.upper)}
          {width}
          height={Math.max(sy(band.lower) - sy(band.upper), 1)}
          fill={band.color ?? SERIES.comfort}
          fill-opacity="0.16"
        />
      {/if}
      {#if fill}
        <path d={fill} fill={color} fill-opacity="0.12" stroke="none" />
      {/if}
      <path
        d={line}
        fill="none"
        stroke={color}
        stroke-width="1.75"
        stroke-linejoin="round"
        stroke-linecap="round"
      />
      {#if at}
        <line x1={sx(at[0])} x2={sx(at[0])} y1="0" y2={height} class="cursor" />
        <circle cx={sx(at[0])} cy={sy(at[1])} r="3" fill={color} class="dot" />
      {:else if last}
        <circle cx={sx(last[0])} cy={sy(last[1])} r="2.5" fill={color} class="dot" />
      {/if}
    </svg>
    {#if interactive && points.length > 0}
      <Crosshair
        from={t0}
        to={t1}
        {times}
        bind:cursor
        label={chartText(lang, 'cursor', { title: label })}
        valuetext={readout}
        left={0}
        top={0}
        {width}
        {height}
      />
    {/if}
  </div>
  {#if (minMax && stats) || (interactive && cursor !== null)}
    <p class="caption" aria-hidden="true">
      {#if interactive && cursor !== null}
        {formatClockTime(cursor, lang)} · {formatValue(at?.[1] ?? null, unit, digits, lang)}
      {:else if stats}
        {formatNum(stats.min, digits, lang)}–{formatValue(stats.max, unit, digits, lang)}
      {/if}
    </p>
  {/if}
</div>

<style>
  .spark {
    min-width: 0;
  }
  .plot {
    position: relative;
  }
  svg {
    display: block;
    width: 100%;
  }
  .dot {
    stroke: var(--surface);
    stroke-width: 1.5;
  }
  .cursor {
    stroke: var(--muted);
    stroke-width: 1;
  }
  .caption {
    margin: var(--chart-space-1) 0 0;
    font-size: var(--fs-caption);
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
</style>
