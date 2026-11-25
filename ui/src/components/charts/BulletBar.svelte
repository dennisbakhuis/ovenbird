<!--
  BulletBar: a measured value against an alarm limit (safety monitors).

  Props: label, value (number | null), limit (number | null), direction ('above' = alarm when
  value ≥ limit, 'below' = alarm when value ≤ limit), warn (optional early-warning threshold),
  unit, digits (1), min/max (scale; default includes zero for positive data and pads past the
  limit), showLabel (label + read-out row, default true), summary (override).
  A11y: role="img" with "Outlet 30.8 °C, alarm above 45 °C, 14.2 K margin"; status is shown
  with an icon shape (check / triangle / octagon) and words, not by colour alone.
-->
<script lang="ts">
  import { axisFor, type Point } from '$lib/core/chart';
  import { chartText, describeBullet, formatValue, limitBreached } from '$lib/core/chartSummary';
  import { settings } from '$lib/core/settings.svelte';
  import { GLYPHS } from './glyphs';
  import { STATUS } from './palette';

  interface Props {
    label: string;
    value: number | null;
    limit: number | null;
    direction?: 'above' | 'below';
    warn?: number | null;
    unit?: string;
    digits?: number;
    min?: number;
    max?: number;
    showLabel?: boolean;
    summary?: string;
  }

  let {
    label,
    value,
    limit,
    direction = 'above',
    warn = null,
    unit = '',
    digits = 1,
    min,
    max,
    showLabel = true,
    summary,
  }: Props = $props();

  const uid = $props.id();
  let measured = $state(0);
  const lang = $derived(settings.language);
  const width = $derived(measured > 0 ? measured : 280);
  const H = 22;

  const axis = $derived.by(() => {
    const known = [value, limit, warn].filter((v): v is number => v !== null);
    const points = known.map((v): Point => [0, v]);
    const positive = known.every((v) => v >= 0);
    return axisFor([points], { min, max, zero: positive, pad: 0.15 }) ?? { min: 0, max: 1 };
  });
  const sx = (v: number) =>
    ((Math.min(Math.max(v, axis.min), axis.max) - axis.min) / Math.max(axis.max - axis.min, 1e-9)) *
    width;

  const breached = $derived(limitBreached(value, limit, direction));
  const warned = $derived(!breached && limitBreached(value, warn, direction));
  const status = $derived(breached ? 'critical' : warned ? 'warning' : 'ok');
  const statusColor = $derived(
    status === 'critical' ? STATUS.critical : status === 'warning' ? STATUS.warn : STATUS.ok,
  );
  const zone = (edge: number) =>
    direction === 'above' ? { x: sx(edge), w: width - sx(edge) } : { x: 0, w: sx(edge) };
  const base = $derived(axis.min <= 0 && axis.max >= 0 ? 0 : axis.min);
  const text = $derived(
    summary ?? describeBullet({ label, value, unit, limit, direction, digits }, lang),
  );
</script>

<div class="bullet" bind:clientWidth={measured} data-testid="bullet-bar" data-status={status}>
  {#if showLabel}
    <p class="head" aria-hidden="true">
      <span class="label">{label}</span>
      <span class="read">
        <svg width="16" height="16" viewBox="0 0 24 24" class="icon" style="color: {statusColor}">
          <path
            d={status === 'ok'
              ? GLYPHS.check
              : status === 'warning'
                ? GLYPHS.warning
                : GLYPHS.critical}
          />
        </svg>
        <strong>{formatValue(value, unit, digits, lang)}</strong>
        {#if limit !== null}
          <span class="muted"
            >/ {chartText(lang, direction === 'above' ? 'limitAbove' : 'limitBelow', {
              limit: formatValue(limit, unit, digits, lang),
            })}</span
          >
        {/if}
      </span>
    </p>
  {/if}
  <svg viewBox="0 0 {width} {H}" {width} height={H} role="img" aria-label={text}>
    <defs>
      <pattern
        id="{uid}-hatch"
        width="6"
        height="6"
        patternUnits="userSpaceOnUse"
        patternTransform="rotate(45)"
      >
        <line
          x1="0"
          y1="0"
          x2="0"
          y2="6"
          stroke={STATUS.critical}
          stroke-width="2"
          stroke-opacity="0.45"
        />
      </pattern>
    </defs>
    <rect x="0" y="6" {width} height="10" rx="3" class="track" />
    {#if warn !== null && limit !== null}
      {@const w = zone(warn)}
      <rect
        x={w.x}
        y="6"
        width={Math.max(w.w, 0)}
        height="10"
        fill={STATUS.warn}
        fill-opacity="0.22"
      />
    {/if}
    {#if limit !== null}
      {@const z = zone(limit)}
      <rect
        x={z.x}
        y="6"
        width={Math.max(z.w, 0)}
        height="10"
        fill={STATUS.critical}
        fill-opacity="0.14"
      />
      <rect x={z.x} y="6" width={Math.max(z.w, 0)} height="10" fill="url(#{uid}-hatch)" />
    {/if}
    {#if value !== null}
      <rect
        x={Math.min(sx(base), sx(value))}
        y="8"
        width={Math.max(Math.abs(sx(value) - sx(base)), 2)}
        height="6"
        rx="2"
        class="value"
        fill={breached ? STATUS.critical : 'var(--text)'}
      />
      <line
        x1={sx(value)}
        x2={sx(value)}
        y1="3"
        y2="19"
        class="tip"
        stroke={breached ? STATUS.critical : 'var(--text)'}
      />
    {/if}
    {#if limit !== null}
      <line x1={sx(limit)} x2={sx(limit)} y1="1" y2="21" class="limit" stroke={STATUS.critical} />
    {/if}
  </svg>
</div>

<style>
  .bullet {
    min-width: 0;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: var(--chart-space-1) var(--space-3);
    margin: 0 0 var(--chart-space-2);
    font-size: var(--fs-md);
  }
  .read {
    display: inline-flex;
    align-items: center;
    gap: var(--chart-space-4);
    font-variant-numeric: tabular-nums;
  }
  .icon {
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  svg[role='img'] {
    display: block;
    width: 100%;
  }
  .track {
    fill: color-mix(in srgb, var(--border) 60%, transparent);
  }
  .value {
    fill-opacity: 0.75;
  }
  .tip {
    stroke-width: 2;
  }
  .limit {
    stroke-width: 2.5;
  }
</style>
