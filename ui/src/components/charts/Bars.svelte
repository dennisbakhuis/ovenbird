<!--
  Bars: a handful of labelled values — daily energy (vertical), forecast bias/MAE per lead time
  or other per-category values (horizontal). Negative values grow from a zero line.

  Props: title (summary and slider name), items (BarItem[]: label, value | null, color?, note?),
  unit, digits (1), orientation ('vertical' | 'horizontal'), height (vertical plot, 120 px),
  color (default bar colour), highlight (index drawn emphasised, e.g. today), showValues
  (direct value labels, default true; vertical bars hide them past 12 items), min/max (domain),
  summary (override), onselect(index) on click/Enter.
  A11y: role="img" with every value (≤ 8 items) or lowest/highest/mean; a slider overlay moves
  between bars with the arrow keys and reads "Mon: 9.6 kWh"; the read-out row repeats it.
-->
<script lang="ts" module>
  import type * as Kit from './types';

  export type BarItem = Kit.BarItem;
</script>

<script lang="ts">
  import { axisFor, type Point } from '$lib/core/chart';
  import { chartText, describeBars, formatValue } from '$lib/core/chartSummary';
  import { settings } from '$lib/core/settings.svelte';
  import Crosshair from './Crosshair.svelte';

  interface Props {
    title: string;
    items: BarItem[];
    unit?: string;
    digits?: number;
    orientation?: 'vertical' | 'horizontal';
    height?: number;
    color?: string;
    highlight?: number | null;
    showValues?: boolean;
    min?: number;
    max?: number;
    summary?: string;
    onselect?: (index: number) => void;
  }

  let {
    title,
    items,
    unit = '',
    digits = 1,
    orientation = 'vertical',
    height = 120,
    color = 'var(--series-bar)',
    highlight = null,
    showValues = true,
    min,
    max,
    summary,
    onselect,
  }: Props = $props();

  let measured = $state(0);
  let cursor = $state<number | null>(null);
  const lang = $derived(settings.language);
  const width = $derived(measured > 0 ? measured : 320);
  const n = $derived(items.length);
  const active = $derived(cursor === null ? null : Math.round(cursor));
  const focus = $derived(active ?? highlight);
  const indices = $derived(items.map((_, i) => i));

  const axis = $derived(
    axisFor([items.filter((i) => i.value !== null).map((i): Point => [0, i.value as number])], {
      zero: true,
      min,
      max,
      pad: 0.05,
    }) ?? { min: 0, max: 1 },
  );
  const span = $derived(Math.max(axis.max - axis.min, 1e-9));

  const TOP = 16;
  const BOTTOM = 18;
  const innerH = $derived(Math.max(height - TOP - BOTTOM, 20));
  const band = $derived(width / Math.max(n, 1));
  const barW = $derived(Math.min(band * 0.68, 48));
  const sy = (v: number) => TOP + (1 - (v - axis.min) / span) * innerH;
  const labelEvery = $derived(Math.max(1, Math.ceil((n * 34) / Math.max(width, 1))));
  const valuesShown = $derived(showValues && n <= 12 && band >= 28);
  const pct = (v: number) => ((v - axis.min) / span) * 100;

  const describe = (index: number | null) => {
    const item = index === null ? undefined : items[index];
    if (!item) return chartText(lang, 'cursorIdle');
    return `${item.label}: ${formatValue(item.value, unit, digits, lang)}${item.note ? ` (${item.note})` : ''}`;
  };
  const text = $derived(summary ?? describeBars(title, items, unit, lang, digits));
</script>

<div class="bars {orientation}" bind:clientWidth={measured} data-testid="bars">
  <p class="readout" aria-hidden="true">{focus === null ? ' ' : describe(focus)}</p>
  {#if orientation === 'vertical'}
    <div class="plot">
      <svg viewBox="0 0 {width} {height}" {width} {height} role="img" aria-label={text}>
        <line x1="0" x2={width} y1={sy(0)} y2={sy(0)} class="base" />
        {#each items as item, i (i)}
          {@const x = i * band + (band - barW) / 2}
          {@const dim = focus !== null && focus !== i}
          {#if item.value === null}
            <line x1={x} x2={x + barW} y1={sy(0) - 1} y2={sy(0) - 1} class="missing" />
          {:else}
            <rect
              {x}
              y={Math.min(sy(item.value), sy(0))}
              width={barW}
              height={Math.max(Math.abs(sy(item.value) - sy(0)), 1)}
              rx="3"
              fill={item.color ?? color}
              fill-opacity={dim ? 0.45 : 0.9}
              class:focus={focus === i}
              data-bar={i}
            />
            {#if valuesShown || focus === i}
              <text
                x={x + barW / 2}
                y={item.value >= 0 ? sy(item.value) - 4 : sy(item.value) + 12}
                text-anchor="middle"
                class="value">{formatValue(item.value, '', digits, lang)}</text
              >
            {/if}
          {/if}
          {#if i % labelEvery === 0 || focus === i}
            <text
              x={x + barW / 2}
              y={height - 4}
              text-anchor="middle"
              class="label"
              class:strong={focus === i}>{item.label}</text
            >
          {/if}
        {/each}
      </svg>
      <Crosshair
        from={-0.5}
        to={n - 0.5}
        times={indices}
        bind:cursor
        label={chartText(lang, 'cursor', { title })}
        valuetext={describe(active)}
        left={0}
        top={0}
        {width}
        {height}
        onpick={onselect ? (i) => onselect(Math.round(i)) : undefined}
      />
    </div>
  {:else}
    <div class="plot">
      <ul class="rows" role="img" aria-label={text}>
        {#each items as item, i (i)}
          {@const v = item.value}
          <li class:dim={focus !== null && focus !== i} data-bar={i}>
            <span class="label">{item.label}</span>
            <span class="track">
              <span class="zero" style="left: {pct(0)}%"></span>
              {#if v !== null}
                <span
                  class="fill"
                  style="left: {pct(Math.min(v, 0))}%; width: {Math.max(
                    Math.abs(pct(v) - pct(0)),
                    0.5,
                  )}%; background: {item.color ?? color}"
                ></span>
              {/if}
            </span>
            {#if showValues}
              <span class="value">{formatValue(v, unit, digits, lang)}</span>
            {/if}
          </li>
        {/each}
      </ul>
      <Crosshair
        from={-0.5}
        to={n - 0.5}
        times={indices}
        bind:cursor
        orientation="y"
        label={chartText(lang, 'cursor', { title })}
        valuetext={describe(active)}
        left={0}
        top={0}
        {width}
        height={n * 30}
        onpick={onselect ? (i) => onselect(Math.round(i)) : undefined}
      />
    </div>
  {/if}
</div>

<style>
  .bars {
    min-width: 0;
  }
  .readout {
    margin: 0 0 var(--chart-space-3);
    min-height: 1.3em;
    font-size: var(--fs-sm);
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    white-space: pre;
  }
  .plot {
    position: relative;
  }
  svg {
    display: block;
    width: 100%;
  }
  .base {
    stroke: var(--border);
  }
  .missing {
    stroke: var(--muted);
    stroke-dasharray: 2 2;
  }
  .focus {
    stroke: var(--text);
    stroke-width: 1.5;
  }
  .value {
    fill: var(--text);
    font-size: var(--fs-micro);
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
  .label {
    fill: var(--muted);
    font-size: var(--fs-micro);
  }
  .label.strong {
    fill: var(--text);
    font-weight: var(--fw-semibold);
  }
  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .rows li {
    display: grid;
    grid-template-columns: minmax(3rem, max-content) 1fr minmax(4.5rem, max-content);
    align-items: center;
    gap: var(--space-2);
    height: 30px;
    font-size: var(--fs-md);
  }
  .rows li.dim {
    opacity: 0.55;
  }
  .rows .label {
    color: var(--muted);
  }
  .rows .value {
    text-align: right;
    font-size: var(--fs-md);
  }
  .track {
    position: relative;
    height: 12px;
    border-radius: var(--radius-xs);
    background: color-mix(in srgb, var(--border) 45%, transparent);
  }
  .zero {
    position: absolute;
    top: -3px;
    bottom: -3px;
    width: 1px;
    background: var(--muted);
  }
  .fill {
    position: absolute;
    top: 1px;
    bottom: 1px;
    border-radius: var(--radius-xs);
  }
</style>
