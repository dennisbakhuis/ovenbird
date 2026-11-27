<!--
  EvolutionChart: how the learned heat loss and time constant moved from one promoted model to the
  next, as two small charts of the same width side by side (stacked on a phone) sharing the
  model dates. The heat loss shows its 90 % range as a whisker; the history carries no range for
  the time constant, so it is a plain line. The newest model is the one in use.

  Props: models (history entries with a heat loss, oldest first).
  A11y: each chart is role="img" with a sentence; QualityCard lists the models as text as well.
-->
<script lang="ts">
  import { linearScale } from '$lib/core/chart';
  import { formatNum } from '$lib/core/chartSummary';
  import { timeLocale } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { HouseHistoryModel } from '$lib/house/house';

  type Model = HouseHistoryModel & { ua_w_per_k: number };

  let { models }: { models: Model[] } = $props();

  const lang = $derived(settings.language);
  const num = (value: number, digits = 0) => formatNum(value, digits, lang);
  const date = (iso: string | null) =>
    new Date(iso ?? 0).toLocaleDateString(timeLocale(lang), { day: 'numeric', month: 'short' });

  interface Series {
    id: 'ua' | 'tau';
    title: string;
    unit: string;
    values: (number | null)[];
    ranges: ([number, number] | null)[];
    summary: string;
  }

  const series = $derived.by((): Series[] => {
    const ua = models.map((m) => m.ua_w_per_k);
    const tau = models.map((m) => m.time_constant_h);
    const known = tau.filter((v): v is number => typeof v === 'number');
    const out: Series[] = [
      {
        id: 'ua',
        title: t('houseTrendHeat'),
        unit: 'W/K',
        values: ua,
        ranges: models.map((m) => m.ua_interval_90),
        summary: t('houseTrendSummary', {
          n: models.length,
          first: num(ua[0] ?? 0),
          last: num(ua[ua.length - 1] ?? 0),
        }),
      },
    ];
    if (known.length >= 2)
      out.push({
        id: 'tau',
        title: t('houseTrendTime'),
        unit: t('houseTrendUnitH'),
        values: tau,
        ranges: models.map(() => null),
        summary: t('houseTrendTimeSummary', {
          n: known.length,
          first: num(known[0] ?? 0),
          last: num(known[known.length - 1] ?? 0),
        }),
      });
    return out;
  });

  const height = 84;
  const pad = { left: 38, right: 10, top: 10, bottom: 22 };
  let widths = $state<number[]>([]);
  const sxFor = (width: number) =>
    linearScale(0, Math.max(models.length - 1, 1), pad.left + 14, width - pad.right - 14);

  function scaleFor(item: Series) {
    const all = item.values
      .flatMap((v, i) => [v, ...(item.ranges[i] ?? [])])
      .filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
    const lo = Math.floor((Math.min(...all) - 2) / 5) * 5;
    const hi = Math.ceil((Math.max(...all) + 2) / 5) * 5;
    return { lo, hi, sy: linearScale(lo, Math.max(hi, lo + 5), height - pad.bottom, pad.top) };
  }
</script>

<div class="multiples" data-testid="house-trend-multiples">
  {#each series as item, index (item.id)}
    {@const width = widths[index] || 260}
    {@const sx = sxFor(width)}
    {@const scale = scaleFor(item)}
    {@const points = item.values.flatMap((v, i) =>
      v === null ? [] : [[sx(i), scale.sy(v)] as [number, number]],
    )}
    <figure bind:clientWidth={widths[index]}>
      <figcaption>
        {item.title} <span class="caption">{item.unit}</span>
      </figcaption>
      <svg
        {width}
        {height}
        viewBox="0 0 {width} {height}"
        role="img"
        aria-label={item.summary}
        data-testid={item.id === 'ua' ? 'house-trend' : 'house-trend-tau'}
      >
        {#each [scale.lo, (scale.lo + scale.hi) / 2, scale.hi] as tick (tick)}
          <line
            class="grid"
            x1={pad.left}
            x2={width - pad.right}
            y1={scale.sy(tick)}
            y2={scale.sy(tick)}
          />
          <text class="tick" x={pad.left - 6} y={scale.sy(tick) + 4} text-anchor="end"
            >{num(tick)}</text
          >
        {/each}
        <polyline class="line" points={points.map((p) => p.join(',')).join(' ')} />
        {#each models as model, i (model.model)}
          {@const range = item.ranges[i]}
          {@const value = item.values[i]}
          {#if range}
            <line
              class="whisker"
              x1={sx(i)}
              x2={sx(i)}
              y1={scale.sy(range[0])}
              y2={scale.sy(range[1])}
            />
          {/if}
          {#if value !== null && value !== undefined}
            <circle
              class="dot"
              class:champion={model.champion}
              cx={sx(i)}
              cy={scale.sy(value)}
              r="4"
            />
          {/if}
          <text
            class="tick"
            x={sx(i)}
            y={height - 6}
            text-anchor={i === 0 ? 'start' : i === models.length - 1 ? 'end' : 'middle'}
            >{date(model.data_to)}</text
          >
        {/each}
      </svg>
    </figure>
  {/each}
</div>

<style>
  .multiples {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9.5rem, 1fr));
    gap: var(--space-3);
  }
  figure {
    margin: 0;
    min-width: 0;
  }
  figcaption {
    font-size: var(--fs-body);
    font-weight: var(--fw-semibold);
    margin-bottom: var(--space-1);
  }
  svg {
    display: block;
    max-width: 100%;
  }
  .grid {
    stroke: var(--chart-grid, var(--border));
  }
  .tick {
    fill: var(--chart-axis, var(--muted));
    font-size: var(--fs-caption);
    font-variant-numeric: tabular-nums;
  }
  .line {
    fill: none;
    stroke: var(--muted);
    stroke-width: 1.5;
  }
  .whisker {
    stroke: var(--text);
    stroke-width: 2;
    opacity: 0.5;
  }
  .dot {
    fill: var(--surface);
    stroke: var(--text);
    stroke-width: 2;
  }
  .dot.champion {
    fill: var(--accent);
    stroke: var(--accent);
  }
</style>
