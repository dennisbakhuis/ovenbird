<!--
  MiniCurve: a small heating-curve picture. With `before`, the old curve is drawn grey, the new
  one in the accent colour and the area between them shaded (the review dialog, the emitter
  preset diff); without, one curve (the Settings overview). `labels` writes the water value at
  each point of the newest curve. role="img" with the change as text.
-->
<script lang="ts">
  import { cornerSamples, curveWater, largestShift, sameCurve, type Curve } from '$lib/core/curve';
  import { curveText, formatDelta } from '$lib/core/fieldFormat';
  import { settings, t } from '$lib/core/settings.svelte';

  interface Props {
    curve: Curve;
    before?: Curve | null;
    height?: number;
    labels?: boolean;
    axis?: boolean;
    xRange?: [number, number];
    yRange?: [number, number] | null;
    testid?: string;
  }

  let {
    curve,
    before = null,
    height = 96,
    labels = false,
    axis = false,
    xRange = [-15, 20],
    yRange = null,
    testid,
  }: Props = $props();

  const locale = $derived(settings.language);
  let measured = $state(0);
  const width = $derived(measured > 0 ? measured : 240);
  const pad = $derived({
    left: axis ? 26 : 4,
    right: labels ? 14 : 4,
    top: labels ? 16 : 6,
    bottom: axis ? 16 : 6,
  });
  const innerW = $derived(Math.max(width - pad.left - pad.right, 40));
  const innerH = $derived(Math.max(height - pad.top - pad.bottom, 20));
  const changed = $derived(before !== null && !sameCurve(before, curve));
  const all = $derived([...curve, ...(before ?? [])]);
  const yLow = $derived(yRange ? yRange[0] : Math.floor(Math.min(...all.map((p) => p[1])) - 1));
  const yHigh = $derived(yRange ? yRange[1] : Math.ceil(Math.max(...all.map((p) => p[1])) + 1));
  const sx = (x: number) => pad.left + ((x - xRange[0]) / (xRange[1] - xRange[0])) * innerW;
  const sy = (y: number) => pad.top + innerH - ((y - yLow) / Math.max(yHigh - yLow, 1)) * innerH;
  const xy = (x: number, y: number) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`;
  const line = (c: Curve) =>
    'M' +
    cornerSamples(c, c, xRange[0], xRange[1])
      .map((x) => xy(x, curveWater(c, x)))
      .join('L');
  const area = $derived.by(() => {
    if (!before || !changed) return '';
    const xs = cornerSamples(before, curve, xRange[0], xRange[1]);
    return (
      'M' +
      xs.map((x) => xy(x, curveWater(curve, x))).join('L') +
      'L' +
      [...xs]
        .reverse()
        .map((x) => xy(x, curveWater(before as Curve, x)))
        .join('L') +
      'Z'
    );
  });
  const fmt = (v: number) =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(v).replace('-', '−');
  const summary = $derived.by(() => {
    const next = curveText(curve, locale);
    if (!before || !changed)
      return t('miniCurveText', { water: next.water, outside: next.outside });
    const old = curveText(before, locale);
    const shift = largestShift(before, curve);
    return t('miniCurveDiffText', {
      old: old.water,
      oldOutside: old.outside,
      water: next.water,
      outside: next.outside,
      shift: formatDelta(0, shift.shift, locale) ?? '0',
      at: fmt(shift.at),
    });
  });
  const inside = (x: number) => x >= xRange[0] && x <= xRange[1];
</script>

<figure class="mini" bind:clientWidth={measured} data-testid={testid}>
  <svg viewBox="0 0 {width} {height}" {width} {height} role="img" aria-label={summary}>
    {#if axis}
      <line
        x1={pad.left}
        x2={pad.left + innerW}
        y1={pad.top + innerH}
        y2={pad.top + innerH}
        class="axis"
      />
      <text x={pad.left - 4} y={sy(yHigh)} dy="0.7em" text-anchor="end" class="tick">{yHigh}</text>
      <text x={pad.left - 4} y={sy(yLow)} text-anchor="end" class="tick">{yLow}</text>
      {#each [xRange[0], 0, xRange[1]] as x (x)}
        <text x={sx(x)} y={height - 3} text-anchor="middle" class="tick">{fmt(x)}</text>
      {/each}
    {/if}
    {#if area}<path d={area} class="area" />{/if}
    {#if before && changed}<path d={line(before)} class="old" />{/if}
    <path d={line(curve)} class="new" class:accent={changed} />
    {#each curve.filter(([x]) => inside(x)) as [x, y] (x)}
      <circle cx={sx(x)} cy={sy(y)} r="2.75" class="pt" class:accent={changed} />
      {#if labels}
        <text x={sx(x)} y={sy(y) - 6} text-anchor="middle" class="label">{fmt(y)}</text>
      {/if}
    {/each}
  </svg>
</figure>

<style>
  .mini {
    margin: 0;
    min-width: 0;
    width: 100%;
  }
  svg {
    display: block;
    max-width: 100%;
    overflow: visible;
  }
  .axis {
    stroke: var(--chart-grid);
  }
  .tick {
    fill: var(--chart-axis);
    font-size: var(--fs-chart-tick);
  }
  .area {
    fill: var(--accent);
    fill-opacity: 0.2;
  }
  .old {
    fill: none;
    stroke: var(--muted);
    stroke-width: 2;
    stroke-dasharray: 4 3;
  }
  .new {
    fill: none;
    stroke: var(--series-curve);
    stroke-width: 2.25;
  }
  .new.accent {
    stroke: var(--accent);
    stroke-width: 2.5;
  }
  .pt {
    fill: var(--surface);
    stroke: var(--series-curve);
    stroke-width: 1.75;
  }
  .pt.accent {
    stroke: var(--accent);
  }
  .label {
    fill: var(--text);
    font-size: var(--fs-chart-tick-lg);
    font-weight: var(--fw-semibold);
  }
</style>
