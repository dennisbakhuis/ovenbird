<!--
  PredictionChart: the room temperature the sensor measured against what the house model had
  predicted 24 hours earlier, over the last 3, 7 or 14 days (the series is loaded once, the range
  switch only cuts it). A gap in either line is a gap in the data. Periods the model cannot
  represent are shaded and the predicted line is broken there: a wood stove with its recovery
  (hatched, then lighter) and a day the owner left out (dotted); a legend line says which is which
  and the table lists them. One sentence gives the typical error on days the model had not seen
  (the service's own figure, with the lean to cold or warm in plain words) and the largest
  difference of the window, events left out; a quiet marker shows where the days the model had seen
  end. The chart kit adds the table and CSV.

  Hidden on an older service without the endpoint; a short line when the service has no series yet.
  A11y: the chart's role="img" summary is the same sentence; shading never carries meaning alone.
-->
<script lang="ts">
  import TimeChart, {
    type MarkerSpec,
    type PanelSpec,
    type SpanSpec,
  } from '$components/charts/TimeChart.svelte';
  import { SERIES } from '$components/charts/palette';
  import { formatNum } from '$lib/core/chartSummary';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    SERIES_RANGES,
    differences,
    eventKinds,
    eventSpans,
    fetchHouseSeries,
    lastDays,
    typicalErrorSentence,
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
  const events = $derived(series?.events ?? []);
  const diff = $derived(differences(points, events, series?.out_of_sample_from ?? null));
  const to = $derived(series ? Date.parse(series.to) : 0);
  const from = $derived(to - range * 86_400_000);
  const spans = $derived(eventSpans(events, from, to));
  const kinds = $derived(eventKinds(spans));
  const options = $derived(
    SERIES_RANGES.map((days) => ({
      value: days,
      label: t('housePredDays', { n: days }),
      testid: `house-pred-range-${days}`,
    })),
  );
  const unseenAt = $derived.by(() => {
    const first = series?.out_of_sample_from ? Date.parse(series.out_of_sample_from) : NaN;
    const at = first + 86_400_000;
    return Number.isFinite(first) && at > from && at < to ? at : null;
  });

  const typical = $derived(
    series
      ? typicalErrorSentence(series.rmse_k, series.bias_k, t, (value, digits) =>
          formatNumber(value, digits, lang),
        )
      : '',
  );
  const largest = $derived(
    diff
      ? t('housePredLargest', {
          largest: formatNum(diff.largestK, 1, lang),
          when: formatDateTime(diff.largestAt, lang),
        })
      : '',
  );
  const sentence = $derived(
    typical
      ? `${typical} ${largest}`.trim()
      : diff
        ? t('housePredSummary', {
            days: range,
            typical: formatNum(diff.typicalK, 1, lang),
            largest: formatNum(diff.largestK, 1, lang),
            when: formatDateTime(diff.largestAt, lang),
          })
        : t('housePredNone'),
  );

  const spanSpecs = $derived<SpanSpec[]>(
    spans.flatMap((span): SpanSpec[] => {
      if (span.kind === 'excluded_day')
        return [
          {
            from: span.from,
            to: span.tailTo,
            pattern: 'dots',
            label: t('housePredEventDay', { day: formatDateTime(span.from, lang) }),
          },
        ];
      const label = t('housePredEventStove', {
        from: formatDateTime(span.from, lang),
        to: formatDateTime(span.to, lang),
        tail: formatDateTime(span.tailTo, lang),
      });
      return [
        { from: span.from, to: span.to, pattern: 'hatch', label },
        { from: span.to, to: span.tailTo, opacity: 0.1 },
      ];
    }),
  );
  const markers = $derived<MarkerSpec[]>(
    unseenAt === null ? [] : [{ t: unseenAt, label: t('housePredUnseen') }],
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
    {#if points.length > 0}
      <TimeChart
        {from}
        {to}
        {panels}
        {markers}
        spans={spanSpecs}
        spansTitle={t('housePredEventsTitle')}
        title={t('housePredTitle')}
        summary={sentence}
        maxGapMs={series.step_s * 1500}
        legend="chips"
      />
    {/if}
    {#if kinds.length > 0}
      <p class="events caption" data-testid="house-pred-events">
        {#if kinds.includes('stove')}
          <span class="key"
            ><span class="swatch hatch" aria-hidden="true"></span>{t('housePredLegendStove')}</span
          >
        {/if}
        {#if kinds.includes('excluded_day')}
          <span class="key"
            ><span class="swatch dots" aria-hidden="true"></span>{t('housePredLegendDay')}</span
          >
        {/if}
      </p>
    {/if}
    <p class="sentence" data-testid="house-pred-summary">{sentence}</p>
  </Card>
{/if}

<style>
  .sentence {
    margin: var(--space-2) 0 0;
  }
  .events {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    margin: var(--space-2) 0 0;
  }
  .key {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
  .swatch {
    display: inline-block;
    width: 1.4rem;
    height: 0.8rem;
    border: 1px solid var(--muted);
  }
  .hatch {
    background: repeating-linear-gradient(135deg, var(--muted) 0 1.5px, transparent 1.5px 5px);
  }
  .dots {
    background: radial-gradient(var(--muted) 1.2px, transparent 1.4px) 0 0 / 5px 5px;
  }
</style>
