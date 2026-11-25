<!--
  ReplayChart: the replayed setpoint over the recorded one and the pump's water target, on one
  water-temperature axis, with the difference between the replay and the pump shaded. Gaps are
  drawn as gaps. All three are setpoints as issued, whole degrees, and read as such.

  Props: result (a finished replay), now (service clock, ms).
  A11y: TimeChart's keyboard crosshair and "Show as table"; the summary states the key numbers.
-->
<script lang="ts">
  import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import { replayBand, seriesPoints, type ReplayResult } from '$lib/replay/replay';
  import { SERIES } from '$components/charts/palette';
  import TimeChart, { type PanelSpec } from '$components/charts/TimeChart.svelte';

  let { result, now = null }: { result: ReplayResult; now?: number | null } = $props();

  const lang = $derived(settings.language);
  const from = $derived(Date.parse(result.from));
  const to = $derived(Date.parse(result.to));
  const gapMs = $derived(result.step * 1000 * 1.5);

  const panels = $derived.by<PanelSpec[]>(() => {
    const band = replayBand(result.series);
    return [
      {
        id: 'water',
        label: t('replayWaterPanel'),
        unit: '°C',
        height: 220,
        snap: 1,
        digits: 0,
        bands: [
          {
            id: 'difference',
            label: t('replaySeriesDifference'),
            color: 'var(--cat-limited)',
            opacity: 0.3,
            upper: band.upper,
            lower: band.lower,
          },
        ],
        lines: [
          {
            id: 'recorded',
            label: t('replaySeriesRecorded'),
            color: SERIES.neutral,
            dash: '2 3',
            points: seriesPoints(result.series, 'recorded'),
            step: true,
            width: 1.5,
            maxGapMs: gapMs,
          },
          {
            id: 'pump',
            label: t('replaySeriesPump'),
            color: SERIES.outlet,
            dash: '5 3',
            points: seriesPoints(result.series, 'pump'),
            step: true,
            width: 2,
            maxGapMs: gapMs,
          },
          {
            id: 'replayed',
            label: t('replaySeriesReplayed'),
            color: 'var(--accent)',
            points: seriesPoints(result.series, 'replayed'),
            step: true,
            width: 2,
            maxGapMs: gapMs,
          },
        ],
      },
    ];
  });

  const summary = $derived(
    t('replayChartSummary', {
      from: formatDateTime(from, lang, now ?? to),
      to: formatDateTime(to, lang, now ?? to),
      changes: result.summary.changes_replayed,
      recorded: result.summary.changes_recorded,
      above: formatDuration(result.summary.above_pump_min * 60, lang),
      below: formatDuration(result.summary.below_pump_min * 60, lang),
      k: formatNumber(result.threshold_k, 1, lang),
    }),
  );
</script>

<div class="replay-chart" data-testid="replay-chart">
  <TimeChart
    {from}
    {to}
    {panels}
    {now}
    nowLabel={t('chartNow')}
    title={t('replayChartTitle')}
    {summary}
    maxGapMs={gapMs}
  />
  <p class="caption muted note">{t('replayChartNote')}</p>
</div>

<style>
  .replay-chart {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
  }
  .note {
    margin: 0;
  }
</style>
