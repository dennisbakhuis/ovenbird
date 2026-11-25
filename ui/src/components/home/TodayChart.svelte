<!--
  TodayChart: room, water and outside temperatures as stacked panels on one time axis (never one
  shared y axis), with the comfort band on the room panel and the issued setpoint on the water
  panel. A range switch (6 h / 24 h / 7 d) sits in the card header.

  Props: history (History | null), setpoint (Point[]), range, onrange, roomId (signal | null),
  target (°C | null), halfBand (K), loading, failed.
-->
<script lang="ts">
  import Segmented from '$ui/Segmented.svelte';
  import { nightByHours, type Point } from '$lib/core/chart';
  import { SERIES } from '$components/charts/palette';
  import { t } from '$lib/core/settings.svelte';
  import type { History } from '$lib/core/types';
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import TimeChart, { type PanelSpec } from '$components/charts/TimeChart.svelte';
  import { RANGE_MS, seriesPoints, SIGNAL, type RangeKey } from './model';
  import { NARROW_QUERY } from '$lib/core/breakpoints';

  interface Props {
    history: History | null;
    setpoint: Point[];
    range: RangeKey;
    onrange: (range: RangeKey) => void;
    roomId: string | null;
    target: number | null;
    halfBand: number;
    loading: boolean;
    failed: boolean;
  }

  let { history, setpoint, range, onrange, roomId, target, halfBand, loading, failed }: Props =
    $props();

  const RANGES: RangeKey[] = ['6h', '24h', '7d'];
  const RANGE_LABEL = { '6h': 'range6h', '24h': 'range24h', '7d': 'range7d' } as const;
  const rangeOptions = $derived(
    RANGES.map((key) => ({ value: key, label: t(RANGE_LABEL[key]), testid: `range-${key}` })),
  );

  let narrow = $state(false);
  $effect(() => {
    const query = window.matchMedia(NARROW_QUERY);
    const update = () => (narrow = query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  });

  const to = $derived(history ? Date.parse(history.to) : 0);
  const from = $derived(to - RANGE_MS[range]);
  const clip = (points: Point[]): Point[] => points.filter(([time]) => time >= from);
  const line = (id: string) => clip(seriesPoints(history, id));

  const empty = $derived(
    history !== null &&
      [roomId ? roomId : '', SIGNAL.outlet, SIGNAL.inlet, SIGNAL.outside].every(
        (id) => seriesPoints(history, id).length === 0,
      ),
  );

  const panels = $derived.by<PanelSpec[]>(() => {
    const room = roomId ? line(roomId) : [];
    return [
      {
        id: 'room',
        label: t('homePanelRoom'),
        unit: '°C',
        height: narrow ? 72 : 110,
        digits: 1,
        lines: [
          {
            id: 'room',
            label: t('homePanelRoom'),
            color: SERIES.room,
            points: room,
            step: true,
            maxGapMs: Infinity,
          },
        ],
        bands:
          target === null
            ? []
            : [
                {
                  id: 'comfort',
                  label: t('seriesComfortBand'),
                  color: SERIES.comfort,
                  lower: target - halfBand,
                  upper: target + halfBand,
                  opacity: 0.16,
                },
              ],
      },
      {
        id: 'water',
        label: t('homePanelWater'),
        unit: '°C',
        height: narrow ? 90 : 120,
        digits: 1,
        lines: [
          {
            id: 'setpoint',
            label: t('seriesSetpoint'),
            color: SERIES.setpoint,
            points: clip(setpoint),
            step: true,
          },
          {
            id: 'outlet',
            label: t('seriesOutlet'),
            color: SERIES.outlet,
            points: line(SIGNAL.outlet),
          },
          {
            id: 'inlet',
            label: t('seriesInlet'),
            color: SERIES.inlet,
            points: line(SIGNAL.inlet),
            dash: '4 3',
          },
        ],
      },
      {
        id: 'outside',
        label: t('panelOutside'),
        unit: '°C',
        height: narrow ? 52 : 90,
        digits: 1,
        lines: [
          {
            id: 'outside',
            label: t('seriesOutside'),
            color: SERIES.outside,
            points: line(SIGNAL.outside),
          },
        ],
      },
    ];
  });
</script>

<Card title={t('todayTitle')} icon="chart" testid="home-chart" help="home.chart">
  {#snippet actions()}
    <Segmented
      options={rangeOptions}
      value={range}
      onchange={onrange}
      label={t('homeRangeLabel')}
      appearance="joined"
      size="sm"
    />
  {/snippet}
  {#if history && empty}
    <EmptyState art="noData" size="small" text={t('chartEmpty')} testid="home-chart-empty" />
  {:else if history}
    <TimeChart
      {from}
      {to}
      {panels}
      now={to}
      nowLabel={t('homeChartNow')}
      title={t('chartTitleRange', { range: t(RANGE_LABEL[range]) })}
      night={nightByHours(from, to)}
    />
  {:else if failed}
    <p class="muted">{t('chartError')}</p>
  {:else if loading}
    <p class="muted">{t('chartLoading')}</p>
  {/if}
</Card>

<style>
</style>
