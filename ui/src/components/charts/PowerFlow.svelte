<!--
  PowerFlow: electric power in → heat out as one bar split into "electric" and "from the air"
  (heat − electric), with COP. Heat = electric + ambient, so the split is the efficiency.

  Props: electricW, heatW (watts | null); cop (default heat / electric when both > 0, else
  null; pass your own to use one definition app-wide); maxW (scale the bar length to this
  power, e.g. the pump's rating; default: the bar fills the width); running (animate the flow
  chevrons, default heat > 0; never with prefers-reduced-motion); compact (one-line ends);
  standbyW (no heat and at most this electric draw reads as idle, default 100 W);
  summary (override).
  A11y: role="img" with "Electric 1.9 kW in, heat 8.4 kW out, of which 6.5 kW from the outside
  air, COP 4.4"; idle, unknown and no-heat (defrost) states are written as words.
-->
<script lang="ts">
  import {
    chartText,
    copOf,
    describePowerFlow,
    formatNum,
    formatValue,
  } from '$lib/core/chartSummary';
  import { settings } from '$lib/core/settings.svelte';
  import { GLYPHS } from './glyphs';
  import { SERIES } from './palette';

  interface Props {
    electricW: number | null;
    heatW: number | null;
    cop?: number | null;
    maxW?: number;
    running?: boolean;
    compact?: boolean;
    standbyW?: number;
    summary?: string;
  }

  let {
    electricW,
    heatW,
    cop,
    maxW,
    running,
    compact = false,
    standbyW = 100,
    summary,
  }: Props = $props();

  const lang = $derived(settings.language);
  const electric = $derived(Math.max(electricW ?? 0, 0));
  const heat = $derived(Math.max(heatW ?? 0, 0));
  const ambient = $derived(Math.max(heat - electric, 0));
  const ratio = $derived(cop === undefined ? copOf(electricW, heatW) : cop);
  const total = $derived(Math.max(heat, electric));
  const unknown = $derived(electricW === null && heatW === null);
  const idle = $derived(!unknown && heat <= 0 && electric <= standbyW);
  const fill = $derived(maxW ? Math.min(total / maxW, 1) * 100 : 100);
  const moving = $derived(running ?? heat > 0);
  const kw = (w: number | null) => formatValue(w === null ? null : w / 1000, 'kW', 1, lang);
  const text = $derived(summary ?? describePowerFlow(electricW, heatW, ratio, lang, standbyW));
</script>

<div
  class="flow"
  class:compact
  role="img"
  aria-label={text}
  data-testid="power-flow"
  data-state={unknown ? 'unknown' : idle ? 'idle' : heat > 0 ? 'running' : 'no-heat'}
>
  <div class="ends">
    <span class="end">
      <svg viewBox="0 0 24 24" width="18" height="18" style="color: {SERIES.electric}">
        <path d={GLYPHS.bolt} />
      </svg>
      <strong>{kw(electricW)}</strong>
      {#if !compact}<span class="muted">{chartText(lang, 'electric')}</span>{/if}
    </span>
    <span class="cop">
      {chartText(lang, 'cop')}
      <strong>{ratio === null || ratio === undefined ? '–' : formatNum(ratio, 1, lang)}</strong>
    </span>
    <span class="end right">
      {#if !compact}<span class="muted">{chartText(lang, 'heat')}</span>{/if}
      <strong>{kw(heatW)}</strong>
      <svg viewBox="0 0 24 24" width="18" height="18" style="color: {SERIES.heat}">
        <path d={GLYPHS.flame} />
      </svg>
    </span>
  </div>
  <div class="track" class:blank={unknown || idle}>
    {#if unknown || idle}
      <span class="empty">{chartText(lang, unknown ? 'noData' : 'off')}</span>
    {:else}
      <div class="bar" class:moving style="width: {fill}%">
        <span class="seg" style="flex: {electric || 0.0001}; background: {SERIES.electric}"></span>
        {#if ambient > 0}
          <span class="seg ambient" style="flex: {ambient}; background: {SERIES.ambient}">
            {#if !compact}<em>+{kw(ambient)} {chartText(lang, 'ambient')}</em>{/if}
          </span>
        {/if}
        <span class="chevrons"></span>
      </div>
    {/if}
  </div>
</div>

<style>
  .flow {
    min-width: 0;
  }
  .ends {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--fs-lg);
    font-variant-numeric: tabular-nums;
    margin-bottom: var(--space-1);
  }
  .end {
    display: inline-flex;
    align-items: center;
    gap: var(--chart-space-4);
    white-space: nowrap;
  }
  .end svg {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .cop {
    font-size: var(--fs-md);
    color: var(--muted);
  }
  .cop strong {
    color: var(--text);
    font-size: var(--fs-emph);
  }
  .track {
    position: relative;
    height: 22px;
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--border) 45%, transparent);
    overflow: hidden;
  }
  .compact .track {
    height: 12px;
  }
  .track.blank {
    height: auto;
  }
  .empty {
    display: block;
    text-align: center;
    font-size: var(--fs-caption);
    line-height: 22px;
    color: var(--muted);
  }
  .compact .empty {
    line-height: 18px;
  }
  .bar {
    position: relative;
    display: flex;
    height: 100%;
    gap: var(--chart-space-px);
  }
  .seg {
    position: relative;
    display: flex;
    align-items: center;
    min-width: 2px;
    overflow: hidden;
  }
  .seg:first-child {
    border-radius: var(--radius-sm) 0 0 var(--radius-sm);
  }
  .seg:nth-last-child(2) {
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  }
  .seg:first-child:nth-last-child(2) {
    border-radius: var(--radius-sm);
  }
  .ambient em {
    padding: 0 var(--chart-space-5);
    font-size: var(--fs-xs);
    font-style: normal;
    font-weight: var(--fw-semibold);
    color: var(--text);
    white-space: nowrap;
  }
  .chevrons {
    position: absolute;
    inset: 0;
    pointer-events: none;
    background-image: linear-gradient(100deg, transparent 40%, var(--shimmer) 50%, transparent 60%);
    background-size: 28px 100%;
    opacity: 0;
  }
  .moving .chevrons {
    opacity: 1;
    animation: flow 1.4s linear infinite;
  }
  @keyframes flow {
    from {
      background-position: 0 0;
    }
    to {
      background-position: 28px 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .moving .chevrons {
      animation: none;
    }
  }
</style>
