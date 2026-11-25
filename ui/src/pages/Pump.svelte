<script lang="ts">
  import InsightCharts from '$components/insight/InsightCharts.svelte';
  import { createInsight } from '$components/insight/useInsight.svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import CopScatter from '$components/pump/CopScatter.svelte';
  import DayCard from '$components/pump/DayCard.svelte';
  import FlowCharts from '$components/pump/FlowCharts.svelte';
  import LoopDiagram from '$components/pump/LoopDiagram.svelte';
  import PumpSettingRow from '$components/pump/PumpSettingRow.svelte';
  import Why from '$ui/Why.svelte';
  import {
    fetchHistory,
    fetchPumpSettings,
    isForbidden,
    isMissing,
    writePumpSetting,
  } from '$lib/core/api';
  import { numericPoints } from '$lib/core/chart';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { getSignal } from '$lib/core/derive';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { pumpStateOf } from '$lib/pump/pumpState';
  import {
    foreignZone,
    insightToday,
    lastRunOf,
    serviceMidnight,
    todayStats,
    withDaily,
  } from '$components/home/model';
  import { formatClock, formatDuration } from '$lib/core/format';
  import { copDots, copFit, daySegments } from '$lib/pump/pumpStats';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { History, PumpSetting, PumpSettingsResponse } from '$lib/core/types';
  import { NARROW_QUERY } from '$lib/core/breakpoints';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const ready = $derived(live.snapshot !== null);
  const DAY_MS = 24 * 3_600_000;
  const WEEK_MS = 7 * DAY_MS;
  const GROUPS: { id: string; ids: string[] }[] = [
    { id: 'flow', ids: ['max_pump_duty'] },
    { id: 'operation', ids: ['heating_mode', 'heating_control', 'heater_on_outdoor'] },
    { id: 'quiet', ids: ['quiet_mode_level', 'quiet_mode_priority', 'powerful_mode_time'] },
    {
      id: 'backup',
      ids: ['room_heater_state', 'heater_delay_time', 'heater_start_delta', 'heater_stop_delta'],
    },
    {
      id: 'curve',
      ids: [
        'z1_curve_target_high',
        'z1_curve_target_low',
        'z1_curve_outside_high',
        'z1_curve_outside_low',
      ],
    },
    {
      id: 'status',
      ids: [
        'operating_mode_state',
        'zones_state',
        'pump_duty',
        'pump_flow',
        'internal_heater_state',
        'error',
      ],
    },
  ];

  let data = $state<PumpSettingsResponse | null>(null);
  let phase = $state<'loading' | 'ok' | 'missing' | 'failed'>('loading');
  let day = $state<History | null>(null);
  let dayFailed = $state(false);
  let week = $state<History | null>(null);
  let weekFailed = $state(false);

  async function load(): Promise<void> {
    try {
      data = await fetchPumpSettings();
      phase = 'ok';
    } catch (error) {
      phase = isMissing(error) ? 'missing' : 'failed';
    }
  }

  const inFlight = $derived(
    data?.settings.some((s) => ['queued', 'sent', 'retry'].includes(s.last_write?.status ?? '')) ??
      false,
  );

  $effect(() => {
    void load();
    const timer = window.setInterval(() => void load(), inFlight ? 1500 : 15_000);
    return () => window.clearInterval(timer);
  });

  const DAY_IDS = [
    'main/Compressor_Freq',
    'main/Defrosting_State',
    'main/ThreeWay_Valve_State',
    'main/Quiet_Mode_Level',
    'main/Main_Outlet_Temp',
    'main/Main_Inlet_Temp',
    'main/Pump_Flow',
    'main/Pump_Duty',
    'main/Heat_Power_Consumption',
    'main/Heat_Power_Production',
  ];
  const WEEK_IDS = [
    'main/Outside_Temp',
    'main/Heat_Power_Consumption',
    'main/Heat_Power_Production',
  ];

  $effect(() => {
    void ready;
    const controller = new AbortController();
    const refresh = async () => {
      const to = new Date(live.serviceNow());
      try {
        day = await fetchHistory(DAY_IDS, controller.signal, {
          from: new Date(to.getTime() - DAY_MS),
          to,
          step: 60,
        });
        dayFailed = false;
      } catch {
        if (!controller.signal.aborted) dayFailed = true;
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 120_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  });

  $effect(() => {
    void ready;
    const controller = new AbortController();
    const refresh = async () => {
      const to = new Date(live.serviceNow());
      try {
        week = await fetchHistory(WEEK_IDS, controller.signal, {
          from: new Date(to.getTime() - WEEK_MS),
          to,
          step: 3600,
        });
        weekFailed = false;
      } catch {
        if (!controller.signal.aborted) weekFailed = true;
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 600_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  });

  const num = (id: string): number | null => {
    const value = getSignal(live.snapshot, id)?.value;
    return typeof value === 'number' ? value : null;
  };
  const setting = (id: string): PumpSetting | undefined => data?.settings.find((s) => s.id === id);
  const numeric = (id: string): number | null => {
    const value = setting(id)?.value;
    return typeof value === 'number' ? value : null;
  };

  const pump = $derived(pumpStateOf(live.snapshot));
  const setDelta = $derived(numeric('heat_delta') ?? num('main/Heat_Delta'));
  const maxDuty = $derived(num('main/Max_Pump_Duty') ?? numeric('max_pump_duty'));

  const dayTo = $derived(day ? Date.parse(day.to) : 0);
  const dayFrom = $derived(dayTo - DAY_MS);
  const segments = $derived(day ? daySegments(day, dayTo) : null);
  const daily = createInsight(1);
  $effect(() => daily.start());
  const today = $derived(
    withDaily(
      day ? todayStats(day, dayTo, serviceMidnight(daily.state.data)) : null,
      insightToday(daily.state.data),
    ),
  );
  const zone = $derived(foreignZone(daily.state.data));
  const lastRun = $derived(lastRunOf(day, dayTo));
  const runLine = $derived.by(() => {
    if (!lastRun) return '';
    const clock = (ms: number) => formatClock(ms, locale);
    const run = lastRun.running
      ? t('pumpRunSince', { from: clock(lastRun.from) })
      : t('pumpLastRun', {
          from: clock(lastRun.from),
          to: clock(lastRun.to),
          len: formatDuration((lastRun.to - lastRun.from) / 1000),
        });
    return today ? `${run} · ${t('pumpStartsToday', { n: today.starts })}` : run;
  });
  const dots = $derived(
    week
      ? copDots(
          numericPoints(week.series['main/Outside_Temp']?.points ?? []),
          numericPoints(week.series['main/Heat_Power_Consumption']?.points ?? []),
          numericPoints(week.series['main/Heat_Power_Production']?.points ?? []),
        )
      : [],
  );

  const writableRows = $derived((data?.settings ?? []).filter((s) => s.access === 'write'));
  const readRows = $derived(
    (data?.settings ?? []).filter((s) => s.access !== 'write' && s.supported),
  );
  const hidden = $derived((data?.settings ?? []).filter((s) => !s.supported).length);
  const groups = $derived.by(() => {
    const used = new Set(GROUPS.flatMap((g) => g.ids));
    const out = GROUPS.map((g) => ({
      id: g.id,
      rows: g.ids.flatMap((id) => readRows.filter((s) => s.id === id)),
    }));
    const rest = readRows.filter((s) => !used.has(s.id));
    if (rest.length > 0) out.push({ id: 'other', rows: rest });
    return out.filter((g) => g.rows.length > 0);
  });

  async function write(id: string, value: number, expect: number | null): Promise<void> {
    try {
      await writePumpSetting(id, { value, expect });
    } catch (error) {
      if (isForbidden(error)) ctl.admin = false;
      throw error;
    }
    ctl.admin = true;
    void load();
  }

  let phone = $state(false);
  $effect(() => {
    const query = window.matchMedia(NARROW_QUERY);
    const update = () => (phone = query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  });

  const refusal = $derived(data?.refusals[0] ?? null);
  const locale = $derived(settings.language);
</script>

<h1 class="visually-hidden">{t('pumpTitle')}</h1>

{#snippet flow()}
  <FlowCharts
    history={day}
    from={dayFrom}
    to={dayTo}
    setDeltaK={setDelta}
    {maxDuty}
    defrost={segments?.defrost ?? []}
    loading={day === null}
    failed={dayFailed}
  />
{/snippet}

{#snippet readonlyGroups()}
  {#if !phone}<h3 class="readonly">{t('readonlyTitle')}</h3>{/if}
  {#each groups as group (group.id)}
    <Details
      summary={t(`pumpGroup_${group.id}` as 'pumpGroup_flow')}
      meta={group.rows.length}
      id="pump-group-{group.id}"
      testid="pump-group-{group.id}"
    >
      {#each group.rows as row (row.id)}
        <PumpSettingRow
          setting={row}
          writable={false}
          {refusal}
          admin={ctl.admin}
          onwrite={write}
        />
      {/each}
    </Details>
  {/each}
{/snippet}

{#snippet cop()}
  <CopScatter {dots} fit={copFit(dots)} loading={week === null} failed={weekFailed} />
{/snippet}

<div class="stack">
  <div class="grid top">
    <Card title={t('loopTitle')} icon="pump" span={6} testid="pump-live" help="pump.loop">
      {#snippet actions()}
        <Why title={t('loopTitle')}><p>{t('loopWhy')}</p></Why>
      {/snippet}
      <LoopDiagram
        kind={pump.kind}
        outletC={num('main/Main_Outlet_Temp')}
        inletC={num('main/Main_Inlet_Temp')}
        flowLpm={num('main/Pump_Flow')}
        duty={num('main/Pump_Duty')}
        {maxDuty}
        hz={num('main/Compressor_Freq')}
        electricW={num('main/Heat_Power_Consumption')}
        heatW={num('main/Heat_Power_Production')}
        setDeltaK={setDelta}
      />
      {#if runLine}<p class="caption runs" data-testid="loop-runs">{runLine}</p>{/if}
    </Card>
    <DayCard
      {segments}
      stats={today}
      {zone}
      from={dayFrom}
      to={dayTo}
      loading={day === null}
      failed={dayFailed}
    />
  </div>

  {#if phone}
    <div data-help="pump.flow">
      <Details summary={t('chartsTitle')} id="pump-flow" icon="chart" testid="pump-flow-details">
        {@render flow()}
      </Details>
    </div>
    <div data-help="pump.cop">
      <Details summary={t('copTitle')} id="pump-cop" icon="chart" testid="pump-cop-details">
        {@render cop()}
      </Details>
    </div>
  {:else}
    {@render flow()}
    {@render cop()}
  {/if}

  <div class="insight-slot" data-testid="pump-insight-slot" data-help="pump.daily">
    <InsightCharts />
  </div>

  {#if phase === 'loading'}
    <p class="muted">{t('pumpLoading')}</p>
  {:else if phase === 'missing'}
    <p class="unavailable muted" data-testid="unavailable">
      <Icon name="info" size={18} />{t('pumpUnavailable')}
    </p>
  {:else if phase === 'failed' || !data}
    <p class="unavailable muted" data-testid="pump-failed">
      <Icon name="warning" size={18} />{t('pumpFailed')}
    </p>
  {:else}
    <Card
      title={t('pumpSettingsTitle')}
      icon="settings"
      testid="pump-settings"
      help="pump.settings"
    >
      {#if !data.writable}
        <div class="notice" data-testid="pump-readonly">
          <Icon name="lock" size={18} />
          <span>{t('settingsRefused')}</span>
          <Why title={t('settingsRefused')} label={t('settingsRefusedWhy')}>
            <ul>
              {#each data.refusals as reason (reason)}<li>{reason}</li>{/each}
            </ul>
          </Why>
        </div>
      {/if}
      {#each writableRows as row (row.id)}
        <PumpSettingRow
          setting={row}
          writable={data.writable}
          {refusal}
          admin={ctl.admin}
          onwrite={write}
        />
      {/each}
      {#if groups.length > 0}
        {#if phone}
          <Details
            summary={t('readonlyTitle')}
            meta={groups.length}
            id="pump-readonly"
            testid="pump-readonly-details"
          >
            {@render readonlyGroups()}
          </Details>
        {:else}
          {@render readonlyGroups()}
        {/if}
      {/if}
      {#if hidden > 0}<p class="muted">{t('pumpHidden', { n: hidden })}</p>{/if}
      {#if data.model}<p class="muted" lang={locale}>
          {t('pumpModel', { model: String(data.model) })}
        </p>{/if}
    </Card>
  {/if}
</div>

<style>
  .top {
    align-items: stretch;
  }
  .runs {
    margin: var(--space-3) 0 0;
  }
  @media (--narrow) {
    .runs {
      display: none;
    }
  }
  .insight-slot:empty {
    display: none;
  }
  .unavailable {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin: 0;
  }
  .notice {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--warn-bg);
    color: var(--warn-text);
  }
  .readonly {
    margin: var(--space-4) 0 var(--space-1);
    font-size: var(--fs-body);
    color: var(--muted);
    font-weight: var(--fw-semibold);
  }
</style>
