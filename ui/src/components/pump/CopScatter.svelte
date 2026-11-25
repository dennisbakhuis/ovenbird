<!--
  CopScatter: COP against outside temperature, one dot per hour of the last 7 days, with a
  least-squares trend line when there are enough dots. Colder hours sit lower; hours with a
  defrost fall far below the cloud.

  Props: dots (CopDot[]), fit (CopFit | null), loading, failed.
  A11y: role="img" with the number of hours, the temperature and COP ranges and the trend; each
  dot has a title with its time, temperature and COP.
-->
<script lang="ts">
  import { linearScale, niceTicks } from '$lib/core/chart';
  import { formatClockTime, formatNum, formatValue } from '$lib/core/chartSummary';
  import { minus } from '$lib/core/minus';
  import type { CopDot, CopFit } from '$lib/pump/pumpStats';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import { SERIES } from '$components/charts/palette';
  import Why from '$ui/Why.svelte';

  interface Props {
    dots: CopDot[];
    fit: CopFit | null;
    loading: boolean;
    failed: boolean;
  }

  let { dots, fit, loading, failed }: Props = $props();

  const lang = $derived(settings.language);
  let measured = $state(0);
  const width = $derived(measured > 0 ? measured : 600);
  const height = $derived(width < 480 ? 220 : 260);
  const pad = { left: 40, right: 12, top: 24, bottom: 36 };

  const xs = $derived(dots.map((d) => d.outside));
  const xMin = $derived(Math.floor(Math.min(...xs, 0) - 1));
  const xMax = $derived(Math.ceil(Math.max(...xs, 1) + 1));
  const yMax = $derived(Math.max(5, Math.ceil(Math.max(...dots.map((d) => d.cop), 0) + 0.5)));
  const sx = $derived(linearScale(xMin, xMax, pad.left, width - pad.right));
  const sy = $derived(linearScale(0, yMax, height - pad.bottom, pad.top));
  const xTicks = $derived(niceTicks(xMin, xMax, width < 480 ? 5 : 8));
  const yTicks = $derived(niceTicks(0, yMax, 5));
  const trend = $derived(
    fit
      ? {
          x1: sx(xMin),
          y1: sy(Math.min(Math.max(fit.intercept + fit.slope * xMin, 0), yMax)),
          x2: sx(xMax),
          y2: sy(Math.min(Math.max(fit.intercept + fit.slope * xMax, 0), yMax)),
        }
      : null,
  );
  const summary = $derived(
    dots.length === 0
      ? t('copNone')
      : t('copSummary', {
          n: dots.length,
          min: minus(formatValue(Math.min(...xs), '°C', 0, lang)),
          max: minus(formatValue(Math.max(...xs), '°C', 0, lang)),
          low: formatNum(Math.min(...dots.map((d) => d.cop)), 1, lang),
          high: formatNum(Math.max(...dots.map((d) => d.cop)), 1, lang),
          trend: fit ? ` ${t('copTrend', { slope: formatNum(fit.slope, 2, lang) })}.` : '',
        }),
  );
</script>

<Card
  title={t('copTitle')}
  subtitle={t('copSubtitle')}
  icon="chart"
  testid="pump-cop"
  span={12}
  help="pump.cop"
>
  {#snippet actions()}
    <Why title={t('copTitle')}><p>{t('copWhy')}</p></Why>
  {/snippet}
  <div class="plot" bind:clientWidth={measured}>
    {#if dots.length > 0}
      <svg
        {width}
        {height}
        viewBox="0 0 {width} {height}"
        role="img"
        aria-label={summary}
        data-testid="cop-plot"
        data-dots={dots.length}
      >
        {#each yTicks as tick (tick)}
          <line class="grid" x1={pad.left} x2={width - pad.right} y1={sy(tick)} y2={sy(tick)} />
          <text class="tick" x={pad.left - 6} y={sy(tick) + 4} text-anchor="end">{tick}</text>
        {/each}
        {#each xTicks as tick (tick)}
          <text class="tick" x={sx(tick)} y={height - pad.bottom + 16} text-anchor="middle"
            >{minus(formatNum(tick, 0, lang))}</text
          >
        {/each}
        <text
          class="axis"
          x={(pad.left + width - pad.right) / 2}
          y={height - 4}
          text-anchor="middle">{t('copAxisX')}</text
        >
        <text class="axis" x="4" y="12">{t('copAxisY')}</text>
        {#if trend}
          <line class="trend" {...trend} />
        {/if}
        {#each dots as dot (dot.t)}
          <circle
            class="dot"
            cx={sx(dot.outside)}
            cy={sy(dot.cop)}
            r="3.5"
            style:fill={SERIES.heat}
          >
            <title
              >{formatClockTime(dot.t, lang, true)} · {minus(
                formatValue(dot.outside, '°C', 1, lang),
              )} · {t('loopCop')}
              {formatNum(dot.cop, 1, lang)}</title
            >
          </circle>
        {/each}
      </svg>
    {:else if failed}
      <p class="muted">{t('dayFailed')}</p>
    {:else if loading}
      <p class="muted">{t('copLoading')}</p>
    {:else}
      <p class="muted" data-testid="cop-none">{t('copNone')}</p>
    {/if}
  </div>
</Card>

<style>
  .plot {
    min-width: 0;
  }
  svg {
    display: block;
    max-width: 100%;
  }
  .grid {
    stroke: var(--chart-grid, var(--border));
    stroke-width: 1;
  }
  .tick,
  .axis {
    fill: var(--chart-axis, var(--muted));
    font-size: var(--fs-caption);
    font-variant-numeric: tabular-nums;
  }
  .trend {
    stroke: var(--text);
    stroke-width: 1.5;
    stroke-dasharray: 5 4;
  }
  .dot {
    fill-opacity: 0.55;
    stroke: var(--surface);
    stroke-width: 0.75;
  }
</style>
