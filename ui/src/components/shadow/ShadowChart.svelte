<!--
  ShadowChart: what ovenbird would send against what the pump has, on one water-temperature axis,
  with the difference shaded between the two lines, and a lane marking who wrote the pump's value
  (ovenbird, another controller, or a gap without data) with its own legend under the chart.
  Gaps are drawn as gaps.

  Props: data (Divergence), now (service clock, ms).
  A11y: TimeChart's keyboard crosshair and "Show as table"; the summary states the key numbers.
-->
<script lang="ts">
  import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import { ICONS } from '$lib/core/icons';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    differenceBand,
    seriesPoints,
    writerSegments,
    type Divergence,
    type WriterState,
  } from '$lib/shadow/shadow';
  import { SERIES } from '$components/charts/palette';
  import TimeChart, { type LaneSpec, type PanelSpec } from '$components/charts/TimeChart.svelte';

  let { data, now = null }: { data: Divergence; now?: number | null } = $props();

  const lang = $derived(settings.language);
  const from = $derived(Date.parse(data.from));
  const to = $derived(Date.parse(data.to));
  const gapMs = $derived(data.step * 1000 * 1.5);
  const num = (value: number | null, digits = 1) =>
    value === null ? '–' : formatNumber(value, digits, lang);

  const WRITER_COLOURS: Record<WriterState, string> = {
    ovenbird: 'var(--accent)',
    other: SERIES.outlet,
    gap: 'var(--status-unknown, var(--muted))',
  };

  const panels = $derived.by<PanelSpec[]>(() => {
    const band = differenceBand(data.series);
    const states: LaneSpec['states'] = {};
    for (const state of ['ovenbird', 'other', 'gap'] as const)
      states[state] = { label: t(`shadowWriter_${state}`), color: WRITER_COLOURS[state] };
    return [
      {
        id: 'water',
        label: t('shadowWaterPanel'),
        unit: '°C',
        height: 200,
        snap: 1,
        bands: [
          {
            id: 'difference',
            label: t('shadowSeriesDifference'),
            color: 'var(--cat-limited)',
            opacity: 0.35,
            upper: band.upper,
            lower: band.lower,
          },
        ],
        lines: [
          {
            id: 'would',
            label: t('shadowSeriesWould'),
            color: 'var(--accent)',
            points: seriesPoints(data.series, 'ovenbird'),
            step: true,
            width: 2,
            maxGapMs: gapMs,
          },
          {
            id: 'pump',
            label: t('shadowSeriesPump'),
            color: SERIES.outlet,
            dash: '5 3',
            points: seriesPoints(data.series, 'pump'),
            step: true,
            width: 2,
            maxGapMs: gapMs,
          },
        ],
      },
      {
        id: 'writer',
        lanes: [
          {
            id: 'writer',
            label: t('shadowLaneWriter'),
            color: WRITER_COLOURS.other,
            icon: ICONS.pump,
            segments: writerSegments(data.series, data.step),
            states,
          },
        ],
      },
    ];
  });

  const summary = $derived.by(() => {
    const s = data.summary;
    const span = {
      from: formatDateTime(from, lang, now ?? to),
      to: formatDateTime(to, lang, now ?? to),
    };
    if (!s.compared_minutes) return t('shadowChartSummaryEmpty', span);
    return t('shadowChartSummary', {
      ...span,
      coverage: `${num((s.coverage ?? 0) * 100, 0)} %`,
      mean: num(s.mean_abs_k),
      max: num(s.max_abs_k),
      hours: formatDuration(s.hours_over * 3600, lang),
      k: num(data.threshold_k),
      episodes: s.episodes,
    });
  });
</script>

<div class="shadow-chart" data-testid="shadow-chart">
  <TimeChart
    {from}
    {to}
    {panels}
    {now}
    nowLabel={t('chartNow')}
    title={t('shadowChartTitle')}
    {summary}
    maxGapMs={gapMs}
  />
  <ul class="writer-legend caption" data-testid="shadow-writer-legend">
    <li class="lead">{t('shadowLaneWriter')}:</li>
    {#each ['ovenbird', 'other', 'gap'] as const as state (state)}
      <li>
        <span class="swatch" style:background={WRITER_COLOURS[state]} aria-hidden="true"></span>
        {t(`shadowWriter_${state}`)}
      </li>
    {/each}
  </ul>
  <p class="caption muted threshold">{t('shadowThreshold', { k: num(data.threshold_k) })}</p>
</div>

<style>
  .shadow-chart {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
  }
  .threshold {
    margin: 0;
  }
  .writer-legend {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
    color: var(--muted);
  }
  .writer-legend li {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .writer-legend .lead {
    font-weight: var(--fw-semibold);
  }
  .swatch {
    width: 1.25rem;
    height: 0.6rem;
    border-radius: var(--radius-2xs);
  }
</style>
