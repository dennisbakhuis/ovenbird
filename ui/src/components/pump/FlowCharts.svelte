<!--
  FlowCharts: ΔT (outlet − inlet) against its setting, water flow and pump duty against its
  maximum as stacked panels on one time axis, with defrosts shaded across all panels (during a
  defrost ΔT and duty leave their normal range — the shading explains it).

  Props: history (History | null), from, to (ms), setDeltaK, maxDuty (number | null), defrost
  (StateSegment[]), loading, failed.
-->
<script lang="ts">
  import { nightByHours, numericPoints, type StateSegment } from '$lib/core/chart';
  import { deltaSeries } from '$lib/pump/pumpStats';
  import { t } from '$lib/core/settings.svelte';
  import type { History } from '$lib/core/types';
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import { SERIES } from '$components/charts/palette';
  import TimeChart, { type PanelSpec } from '$components/charts/TimeChart.svelte';
  import Why from '$ui/Why.svelte';

  interface Props {
    history: History | null;
    from: number;
    to: number;
    setDeltaK: number | null;
    maxDuty: number | null;
    defrost: StateSegment[];
    loading: boolean;
    failed: boolean;
  }

  let { history, from, to, setDeltaK, maxDuty, defrost, loading, failed }: Props = $props();

  const line = (id: string) => numericPoints(history?.series[id]?.points ?? []);

  const panels = $derived.by<PanelSpec[]>(() => [
    {
      id: 'delta',
      label: t('panelDelta'),
      unit: 'K',
      height: 110,
      digits: 1,
      zero: true,
      lines: [
        {
          id: 'delta',
          label: t('seriesDelta'),
          color: SERIES.outlet,
          points: deltaSeries(line('main/Main_Outlet_Temp'), line('main/Main_Inlet_Temp')),
        },
      ],
      rules:
        setDeltaK === null
          ? []
          : [
              {
                value: setDeltaK,
                label: t('ruleSetDelta', { value: setDeltaK }),
                color: SERIES.setpoint,
                dash: '4 3',
              },
            ],
    },
    {
      id: 'flow',
      label: t('panelFlow'),
      unit: 'l/min',
      height: 100,
      digits: 1,
      zero: true,
      lines: [
        {
          id: 'flow',
          label: t('seriesFlow'),
          color: SERIES.outside,
          points: line('main/Pump_Flow'),
        },
      ],
    },
    {
      id: 'duty',
      label: t('panelDuty'),
      height: 90,
      digits: 0,
      lines: [
        {
          id: 'duty',
          label: t('seriesDuty'),
          unit: '',
          color: SERIES.quiet,
          points: line('main/Pump_Duty'),
        },
      ],
      rules:
        maxDuty === null
          ? []
          : [
              {
                value: maxDuty,
                label: t('ruleMaxDuty', { value: maxDuty }),
                color: SERIES.setpoint,
                dash: '4 3',
              },
            ],
    },
  ]);

  const empty = $derived(
    history !== null &&
      panels.every((panel) => (panel.lines ?? []).every((l) => l.points.length === 0)),
  );
  const spans = $derived(
    defrost.map((run) => ({
      from: run.from,
      to: run.to,
      label: t('spanDefrost'),
      color: SERIES.defrost,
      opacity: 0.16,
    })),
  );
</script>

<Card title={t('chartsTitle')} icon="chart" testid="pump-charts" help="pump.flow">
  {#snippet actions()}
    <Why title={t('chartsTitle')}><p>{t('chartsWhy')}</p></Why>
  {/snippet}
  {#if history && !failed && empty}
    <EmptyState art="noData" size="small" text={t('chartNoData')} testid="flow-empty" />
  {:else if history && !failed}
    <TimeChart
      {from}
      {to}
      {panels}
      {spans}
      now={to}
      nowLabel={t('chartNow')}
      title={t('chartTitle')}
      night={nightByHours(from, to)}
    />
  {:else if failed}
    <p class="muted">{t('dayFailed')}</p>
  {:else if loading}
    <p class="muted">{t('dayLoading')}</p>
  {/if}
</Card>
