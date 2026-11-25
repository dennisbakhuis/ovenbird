<!--
  BandMeter: one value on a short scale with its comfort band, target, optional flip point
  ("the setpoint changes at 21.5 °C") and trend arrow.

  Props: value (number | null), low, high (band), target, label, unit ('°C'), digits (1),
  trend (units per hour, e.g. from trendPerHour(); null hides the arrow), flip ({at, label?}),
  min/max (scale ends; default the band padded to include value, target and flip),
  showValue (value + trend in a header row, default true), color (band colour),
  summary (override).
  A11y: role="img" with "Room 20.4 °C, 0.6 K below target 21 °C, below the comfort band
  20.5–21.5 °C, falling 0.2 K per hour"; band position is also written as a word next to the
  value and the marker shape changes outside the band, so colour is never the only cue.
-->
<script lang="ts">
  import { niceStep } from '$lib/core/chart';
  import {
    bandState,
    chartText,
    deltaUnit,
    describeBand,
    formatNum,
    formatValue,
    trendDirection,
  } from '$lib/core/chartSummary';
  import { settings } from '$lib/core/settings.svelte';
  import { SERIES, STATUS } from './palette';

  interface Props {
    value: number | null;
    low: number;
    high: number;
    label: string;
    target?: number | null;
    unit?: string;
    digits?: number;
    trend?: number | null;
    flip?: { at: number; label?: string } | null;
    min?: number;
    max?: number;
    showValue?: boolean;
    color?: string;
    summary?: string;
  }

  let {
    value,
    low,
    high,
    label,
    target = null,
    unit = '°C',
    digits = 1,
    trend = null,
    flip = null,
    min,
    max,
    showValue = true,
    color = SERIES.comfort,
    summary,
  }: Props = $props();

  let measured = $state(0);
  const lang = $derived(settings.language);
  const width = $derived(measured > 0 ? measured : 280);
  const H = 46;
  const PAD = 10;

  const scale = $derived.by(() => {
    const known = [low, high, value, target, flip?.at].filter(
      (v): v is number => v !== null && v !== undefined && Number.isFinite(v),
    );
    const lo = Math.min(...known);
    const hi = Math.max(...known);
    const margin = Math.max((high - low) * 0.6, 0.5);
    const snap = niceStep(margin / 2);
    return {
      min: min ?? Math.floor((lo - margin) / snap) * snap,
      max: max ?? Math.ceil((hi + margin) / snap) * snap,
    };
  });
  const sx = (v: number) =>
    PAD +
    ((Math.min(Math.max(v, scale.min), scale.max) - scale.min) /
      Math.max(scale.max - scale.min, 1e-9)) *
      (width - 2 * PAD);

  const position = $derived(value === null ? null : bandState(value, low, high));
  const direction = $derived(trendDirection(trend));
  const text = $derived(
    summary ??
      describeBand(
        {
          label,
          value,
          unit,
          low,
          high,
          target,
          trend: trend === null ? undefined : trend,
          flip: flip?.at ?? null,
          digits,
        },
        lang,
      ),
  );
  const stateWord = $derived(
    position === null
      ? ''
      : chartText(
          lang,
          position === 'within' ? 'inBand' : position === 'below' ? 'belowBand' : 'aboveBand',
          {
            low: formatNum(low, digits, lang),
            high: formatValue(high, unit, digits, lang),
          },
        ),
  );
  const targetX = $derived(target === null ? null : sx(target));
  const showMin = $derived(targetX === null || targetX - sx(scale.min) > 44);
  const showMax = $derived(targetX === null || sx(scale.max) - targetX > 44);
</script>

<div class="meter" bind:clientWidth={measured} data-testid="band-meter" data-state={position}>
  {#if showValue}
    <p class="head" aria-hidden="true">
      <strong class="value">{formatValue(value, unit, digits, lang)}</strong>
      {#if trend !== null}
        <span class="trend" data-direction={direction}>
          <svg width="16" height="16" viewBox="0 0 24 24">
            <path
              d="M5 12h13M13 7l5 5-5 5"
              transform="rotate({direction === 'rising'
                ? -40
                : direction === 'falling'
                  ? 40
                  : 0} 12 12)"
            />
          </svg>
          {direction === 'steady'
            ? chartText(lang, 'steady')
            : formatValue(Math.abs(trend), `${deltaUnit(unit)}/h`, 1, lang)}
        </span>
      {/if}
      <span class="state">{stateWord}</span>
    </p>
  {/if}
  <svg viewBox="0 0 {width} {H}" {width} height={H} role="img" aria-label={text}>
    <rect x={PAD} y="17" width={width - 2 * PAD} height="6" rx="3" class="track" />
    <rect
      x={sx(low)}
      y="11"
      width={Math.max(sx(high) - sx(low), 2)}
      height="18"
      rx="4"
      fill={color}
      fill-opacity="0.25"
      stroke={color}
      stroke-opacity="0.5"
    />
    {#if targetX !== null}
      <line x1={targetX} x2={targetX} y1="7" y2="33" class="target" />
    {/if}
    {#if flip}
      <line x1={sx(flip.at)} x2={sx(flip.at)} y1="5" y2="35" class="flip" stroke={STATUS.warn} />
      <text
        x={sx(flip.at)}
        y="4"
        text-anchor={sx(flip.at) > width - 60 ? 'end' : 'middle'}
        class="flip-label">{flip.label ?? formatNum(flip.at, digits, lang)}</text
      >
    {/if}
    {#if value !== null}
      {@const x = sx(value)}
      {#if position === 'within'}
        <circle cx={x} cy="20" r="7" fill={STATUS.ok} class="marker" />
      {:else}
        <path
          d="M{x - 7},13 h14 l-7,14 z"
          transform={position === 'above' ? `rotate(180 ${x} 20)` : undefined}
          fill={STATUS.warn}
          class="marker"
        />
      {/if}
    {/if}
    {#if showMin}
      <text x={PAD} y={H - 2} class="tick">{formatNum(scale.min, digits, lang)}</text>
    {/if}
    {#if targetX !== null && target !== null}
      <text
        x={Math.min(Math.max(targetX, PAD + 20), width - PAD - 20)}
        y={H - 2}
        text-anchor="middle"
        class="tick target-label">{formatValue(target, unit, digits, lang)}</text
      >
    {/if}
    {#if showMax}
      <text x={width - PAD} y={H - 2} text-anchor="end" class="tick"
        >{formatNum(scale.max, digits, lang)}</text
      >
    {/if}
  </svg>
</div>

<style>
  .meter {
    min-width: 0;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--chart-space-7);
    margin: 0 0 var(--chart-space-2);
  }
  .value {
    font-size: var(--fs-value);
    font-variant-numeric: tabular-nums;
  }
  .trend {
    display: inline-flex;
    align-items: center;
    gap: var(--chart-space-2);
    font-size: var(--fs-md);
    font-variant-numeric: tabular-nums;
  }
  .trend svg {
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .state {
    font-size: var(--fs-sm);
    color: var(--muted);
  }
  svg[role='img'] {
    display: block;
    width: 100%;
    overflow: visible;
  }
  .track {
    fill: color-mix(in srgb, var(--border) 70%, transparent);
  }
  .target {
    stroke: var(--text);
    stroke-width: 2;
  }
  .flip {
    stroke-width: 1.5;
    stroke-dasharray: 3 2;
  }
  .flip-label {
    fill: var(--muted);
    font-size: var(--fs-chart-tick);
    font-weight: var(--fw-semibold);
  }
  .marker {
    stroke: var(--surface);
    stroke-width: 2;
  }
  .tick {
    fill: var(--muted);
    font-size: var(--fs-micro);
    font-variant-numeric: tabular-nums;
  }
  .target-label {
    fill: var(--text);
    font-weight: var(--fw-semibold);
  }
</style>
