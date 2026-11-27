<!--
  PredictionChart: the room temperature the sensor measured against what the house model had
  predicted 24 hours earlier, over the last 3, 7 or 14 days (the series is loaded once, the range
  switch only cuts it). A gap in either line is a gap in the data. One sentence says how far off
  the prediction typically was and at most; the chart kit adds the table and CSV.

  Hidden on an older service without the endpoint; a short line when the service has no series yet.
  A11y: the chart's role="img" summary is the same sentence.
-->
<script lang="ts">
  import TimeChart, { type PanelSpec } from '$components/charts/TimeChart.svelte';
  import { SERIES } from '$components/charts/palette';
  import { formatNum } from '$lib/core/chartSummary';
  import { formatDateTime } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    SERIES_RANGES,
    differences,
    fetchHouseSeries,
    lastDays,
    type SeriesRange,
    type SeriesResult,
  } from '$lib/house/series';
  import Card from '$ui/Card.svelte';
  import Segmented from '$ui/Segmented.svelte';

  const REFRESH_MS = 1_800_000;
  const lang = $derived(settings.language);

  let result = $state<SeriesResult | null>(null);
  let range = $state<SeriesRange>(7);

  $effect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        result = await fetchHouseSeries(controller.signal);
      } catch {
        if (controller.signal.aborted) return;
        result ??= { kind: 'absent' };
      }
      timer = window.setTimeout(load, REFRESH_MS);
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  });

  const series = $derived(result?.kind === 'ready' ? result.data : null);
  const points = $derived(series ? lastDays(series, range) : []);
  const diff = $derived(differences(points));
  const to = $derived(series ? Date.parse(series.to) : 0);
  const from = $derived(to - range * 86_400_000);
  const options = $derived(
    SERIES_RANGES.map((days) => ({
      value: days,
      label: t('housePredDays', { n: days }),
      testid: `house-pred-range-${days}`,
    })),
  );

  const sentence = $derived(
    diff
      ? t('housePredSummary', {
          days: range,
          typical: formatNum(diff.typicalK, 1, lang),
          largest: formatNum(diff.largestK, 1, lang),
          when: formatDateTime(diff.largestAt, lang),
        })
      : t('housePredNone'),
  );

  const panels = $derived<PanelSpec[]>([
    {
      id: 'room',
      unit: '°C',
      height: 100,
      digits: 1,
      lines: [
        {
          id: 'measured',
          label: t('housePredMeasured'),
          color: SERIES.room,
          points: points.flatMap(([at, measured]) =>
            measured === null ? [] : [[Date.parse(at), measured] as [number, number]],
          ),
        },
        {
          id: 'predicted',
          label: t('housePredPredicted'),
          color: SERIES.forecast,
          dash: '5 4',
          points: points.flatMap(([at, , predicted]) =>
            predicted === null ? [] : [[Date.parse(at), predicted] as [number, number]],
          ),
        },
      ],
    },
  ]);
</script>

{#if result?.kind === 'none'}
  <Card
    title={t('housePredTitle')}
    icon="chart"
    testid="house-prediction"
    help="house.prediction"
    span={12}
  >
    <p class="muted" data-testid="house-pred-none">{t('houseError_house_series_missing')}</p>
  </Card>
{:else if series}
  <Card
    title={t('housePredTitle')}
    icon="chart"
    testid="house-prediction"
    help="house.prediction"
    span={12}
  >
    {#snippet actions()}
      <Segmented
        {options}
        value={range}
        onchange={(value) => (range = value)}
        label={t('housePredRange')}
        appearance="joined"
        size="sm"
        testid="house-pred-range"
      />
    {/snippet}
    {#if diff}
      <TimeChart
        {from}
        {to}
        {panels}
        title={t('housePredTitle')}
        summary={sentence}
        maxGapMs={series.step_s * 1500}
        legend="chips"
      />
    {/if}
    <p class="sentence" data-testid="house-pred-summary">{sentence}</p>
  </Card>
{/if}

<style>
  .sentence {
    margin: var(--space-2) 0 0;
  }
</style>
