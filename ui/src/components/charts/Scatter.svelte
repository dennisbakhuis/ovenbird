<!--
  Scatter: points on two numeric axes with an optional dashed straight line (the look of the COP
  scatter on the Pump page), for a fit and its data.
  Marks differ in shape as well as colour (dot, ring, cross), so the kinds stay apart without
  colour vision; a legend below names the kinds that are present.

  Props: title, points (x, y, mark, label), marks (id -> label, color, shape), line (from, to),
  xLabel, yLabel (axis titles with units), digits, height (220), summary (override).
  A11y: role="img" with the count per mark and the line; each point carries a native tooltip.
-->
<script lang="ts" module>
  export type MarkShape = 'dot' | 'ring' | 'cross';

  export interface ScatterMark {
    label: string;
    color: string;
    shape: MarkShape;
  }

  export interface ScatterPoint {
    x: number;
    y: number;
    mark: string;
    label: string;
  }
</script>

<script lang="ts">
  import { axisFor, linearScale, niceTicks, type Point } from '$lib/core/chart';
  import { formatNum } from '$lib/core/chartSummary';
  import { settings } from '$lib/core/settings.svelte';

  interface Props {
    title: string;
    points: ScatterPoint[];
    marks: Record<string, ScatterMark>;
    line?: { from: [number, number]; to: [number, number] } | null;
    lineLabel?: string;
    xLabel: string;
    yLabel: string;
    digits?: number;
    height?: number;
    summary?: string;
  }

  let {
    title,
    points,
    marks,
    line = null,
    lineLabel = '',
    xLabel,
    yLabel,
    digits = 1,
    height = 220,
    summary,
  }: Props = $props();

  let measured = $state(0);
  const lang = $derived(settings.language);
  const width = $derived(measured > 0 ? measured : 320);

  const LEFT = 34;
  const RIGHT = 10;
  const TOP = 10;
  const BOTTOM = 36;
  const R = 3.6;

  const xAxis = $derived(
    axisFor([points.map((p): Point => [0, p.x]), line ? [[0, line.to[0]]] : []], {
      min: 0,
      pad: 0.04,
    }) ?? { min: 0, max: 1 },
  );
  const yAxis = $derived(
    axisFor([points.map((p): Point => [0, p.y]), line ? [[0, line.from[1]]] : []], {
      min: 0,
      pad: 0.06,
    }) ?? { min: 0, max: 1 },
  );
  const sx = $derived(linearScale(xAxis.min, xAxis.max, LEFT, Math.max(width - RIGHT, LEFT + 1)));
  const sy = $derived(linearScale(yAxis.min, yAxis.max, height - BOTTOM, TOP));
  const xTicks = $derived(niceTicks(xAxis.min, xAxis.max, Math.max(Math.floor(width / 70), 3), 1));
  const yTicks = $derived(niceTicks(yAxis.min, yAxis.max, 4, 0.5));

  const present = $derived(Object.keys(marks).filter((id) => points.some((p) => p.mark === id)));
  const counts = $derived(
    present.map((id) => `${points.filter((p) => p.mark === id).length} ${marks[id]?.label ?? id}`),
  );
  const text = $derived(
    summary ?? `${title}: ${counts.join(', ')}${line && lineLabel ? `, ${lineLabel}` : ''}`,
  );
  const fmt = (v: number) => formatNum(v, digits, lang);
</script>

<div class="scatter" bind:clientWidth={measured} data-testid="scatter">
  <svg viewBox="0 0 {width} {height}" {width} {height} role="img" aria-label={text}>
    {#each yTicks as tick (tick)}
      <line x1={LEFT} x2={width - RIGHT} y1={sy(tick)} y2={sy(tick)} class="grid" />
      <text x={LEFT - 5} y={sy(tick) + 3} text-anchor="end" class="tick">{fmt(tick)}</text>
    {/each}
    {#each xTicks as tick (tick)}
      <text x={sx(tick)} y={height - BOTTOM + 13} text-anchor="middle" class="tick"
        >{fmt(tick)}</text
      >
    {/each}
    <line x1={LEFT} x2={width - RIGHT} y1={sy(0)} y2={sy(0)} class="axis" />
    <text x={(LEFT + width - RIGHT) / 2} y={height - 4} text-anchor="middle" class="title"
      >{xLabel}</text
    >
    <text x={LEFT} y={TOP - 1} text-anchor="start" class="title">{yLabel}</text>
    {#if line}
      <line
        x1={sx(line.from[0])}
        y1={sy(line.from[1])}
        x2={sx(line.to[0])}
        y2={sy(line.to[1])}
        class="fit"
        data-testid="scatter-line"
      />
    {/if}
    {#each points as p, i (i)}
      {@const mark = marks[p.mark]}
      {#if mark}
        {@const cx = sx(p.x)}
        {@const cy = sy(p.y)}
        <g data-mark={p.mark} data-testid="scatter-point">
          <title>{p.label}</title>
          {#if mark.shape === 'cross'}
            <path
              d="M{cx - R} {cy - R}L{cx + R} {cy + R}M{cx - R} {cy + R}L{cx + R} {cy - R}"
              stroke={mark.color}
              class="cross"
            />
          {:else if mark.shape === 'ring'}
            <circle {cx} {cy} r={R} stroke={mark.color} class="ring" />
          {:else}
            <circle {cx} {cy} r={R} fill={mark.color} fill-opacity="0.85" class="dot" />
          {/if}
        </g>
      {/if}
    {/each}
  </svg>
  <ul class="legend" aria-hidden="true">
    {#each present as id (id)}
      {@const mark = marks[id]}
      {#if mark}
        <li>
          <svg width="14" height="14" viewBox="-7 -7 14 14">
            {#if mark.shape === 'cross'}
              <path d="M-4 -4L4 4M-4 4L4 -4" stroke={mark.color} class="cross" />
            {:else if mark.shape === 'ring'}
              <circle r="4" stroke={mark.color} class="ring" />
            {:else}
              <circle r="4" fill={mark.color} fill-opacity="0.85" />
            {/if}
          </svg>
          {mark.label}
        </li>
      {/if}
    {/each}
    {#if line && lineLabel}
      <li>
        <svg width="14" height="14" viewBox="-7 -7 14 14"><path d="M-7 0H7" class="fit" /></svg>
        {lineLabel}
      </li>
    {/if}
  </ul>
</div>

<style>
  .scatter {
    min-width: 0;
  }
  svg[role='img'] {
    display: block;
    width: 100%;
  }
  .grid {
    stroke: var(--chart-grid);
  }
  .axis {
    stroke: var(--chart-axis);
    stroke-opacity: 0.6;
  }
  .tick {
    fill: var(--chart-axis);
    font-size: var(--fs-caption);
    font-variant-numeric: tabular-nums;
  }
  .title {
    fill: var(--chart-axis);
    font-size: var(--fs-caption);
  }
  .fit {
    stroke: var(--text);
    stroke-width: 1.5;
    stroke-dasharray: 5 4;
    fill: none;
  }
  .dot {
    stroke: var(--surface);
    stroke-width: 0.75;
  }
  .ring {
    fill: none;
    stroke-width: 1.8;
  }
  .cross {
    fill: none;
    stroke-width: 2;
    stroke-linecap: round;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: var(--chart-space-1) var(--space-3);
    margin: var(--chart-space-3) 0 0;
    padding: 0;
    list-style: none;
    font-size: var(--fs-sm);
    color: var(--muted);
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: var(--chart-space-4);
  }
</style>
