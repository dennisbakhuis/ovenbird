<!--
  DayCard: the last 24 hours of pump activity as a day strip (compressor shaded by frequency,
  defrost, hot water, quiet mode; with hot water hidden its lane only shows runs, neutrally named)
  with today's figures under it: starts, runs, defrosts, energy
  and COP since midnight in the service's time zone (from insight/daily), the same numbers Home
  shows.

  Props: segments (DaySegments | null), stats (TodayStats | null), zone (the service's time zone
  when it differs from the browser's, shown in the heading), from, to (ms), loading, failed.
-->
<script lang="ts">
  import { formatNum, formatValue } from '$lib/core/chartSummary';
  import { formatDuration } from '$lib/core/format';
  import { hotWater, hotWaterLanes } from '$lib/core/hotWater.svelte';
  import type { DaySegments } from '$lib/pump/pumpStats';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import type { TodayStats } from '$components/home/model';
  import { GLYPHS } from '$components/charts/glyphs';
  import { SERIES } from '$components/charts/palette';
  import StateStrip from '$components/charts/StateStrip.svelte';
  import type { LaneSpec } from '$components/charts/types';
  import StatChip from '$ui/StatChip.svelte';
  import Why from '$ui/Why.svelte';

  interface Props {
    segments: DaySegments | null;
    stats: TodayStats | null;
    zone?: string | null;
    from: number;
    to: number;
    loading: boolean;
    failed: boolean;
  }

  let { segments, stats, zone = null, from, to, loading, failed }: Props = $props();

  const lang = $derived(settings.language);
  const on = $derived({ on: { label: t('laneOn') } });
  const lanes = $derived.by<LaneSpec[]>(() =>
    segments
      ? hotWaterLanes<LaneSpec>(
          [
            {
              id: 'compressor',
              label: t('laneCompressor'),
              icon: GLYPHS.fan,
              color: SERIES.compressor,
              segments: segments.compressor,
              states: on,
            },
            {
              id: 'defrost',
              label: t('laneDefrost'),
              icon: GLYPHS.snowflake,
              color: SERIES.defrost,
              segments: segments.defrost,
              states: on,
            },
            {
              id: 'dhw',
              label: t('laneHotWater'),
              icon: GLYPHS.tap,
              color: SERIES.dhw,
              segments: segments.dhw,
              states: on,
            },
            {
              id: 'quiet',
              label: t('laneQuiet'),
              icon: GLYPHS.moon,
              color: SERIES.quiet,
              segments: segments.quiet,
              states: on,
            },
          ],
          hotWater.shown,
        )
      : [],
  );

  const minutes = (s: number | null) => (s === null ? '–' : formatDuration(s));
  const energy = $derived(stats?.energy ?? null);
  const kwh = (value: number | undefined) =>
    value === undefined ? '–' : formatNum(value, 1, lang);
  const coveragePct = $derived(
    energy && energy.coverage < 0.9 ? formatValue(energy.coverage * 100, '%', 0, lang) : null,
  );
</script>

<Card title={t('dayTitle')} icon="clock" testid="pump-day" span={6} help="pump.day">
  {#snippet actions()}
    <Why title={t('dayTitle')}><p>{t('dayWhy')}</p></Why>
  {/snippet}
  <div class="stack">
    {#if lanes.length > 0 && !failed}
      <StateStrip {from} {to} {lanes} now={to} title={t('dayTitle')} />
    {:else if failed}
      <p class="muted">{t('dayFailed')}</p>
    {:else if loading}
      <p class="muted">{t('dayLoading')}</p>
    {/if}
    {#if stats}
      <h3 class="today" data-testid="pump-stats-title">
        {zone ? t('statsTodayZone', { zone }) : t('statsToday')}
      </h3>
      <div class="chips" data-testid="pump-stats">
        <StatChip
          size="sm"
          label={t('statStarts')}
          value={String(stats.starts)}
          icon="fan"
          testid="pump-starts"
        />
        <StatChip
          size="sm"
          label={t('statRunMean')}
          value={minutes(stats.meanRunS)}
          caption={stats.longestRunS === null
            ? undefined
            : `${t('statRunLongest')} ${minutes(stats.longestRunS)}`}
        />
        <StatChip
          size="sm"
          label={t('statDefrosts')}
          value={String(stats.defrosts)}
          testid="pump-defrosts"
          icon="snowflake"
          iconColor={SERIES.defrost}
        />
        <StatChip
          size="sm"
          label={t('statElectric')}
          value={kwh(energy?.electricKwh)}
          unit="kWh"
          icon="bolt"
          iconColor={SERIES.electric}
        />
        <StatChip
          size="sm"
          label={t('statHeat')}
          value={kwh(energy?.heatKwh)}
          unit="kWh"
          icon="flame"
          iconColor={SERIES.heat}
        />
        <StatChip
          size="sm"
          label={t('statCop')}
          value={energy?.cop == null ? '–' : formatNum(energy.cop, 1, lang)}
          caption={coveragePct ? t('statCoverage', { pct: coveragePct }) : undefined}
        />
      </div>
    {/if}
  </div>
</Card>

<style>
  .today {
    margin: 0 0 calc(-1 * var(--space-2));
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr));
    gap: var(--space-2);
  }
</style>
