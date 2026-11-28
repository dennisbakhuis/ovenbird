<script lang="ts">
  import { poll } from '$lib/core/poll.svelte';
  import { fetchHistory, fetchSeries, fetchWeather } from '$lib/core/api';
  import AwayControl from '$components/home/AwayControl.svelte';
  import BoostControl from '$components/home/BoostControl.svelte';
  import ComfortSheet from '$components/home/ComfortSheet.svelte';
  import DayStrip from '$components/home/DayStrip.svelte';
  import HomeTiles from '$components/home/HomeTiles.svelte';
  import WeekCard from '$components/insight/WeekCard.svelte';
  import { createInsight } from '$lib/house/useInsight.svelte';
  import PumpCard from '$components/home/PumpCard.svelte';
  import RoomCard from '$components/home/RoomCard.svelte';
  import SummerNote from '$components/home/SummerNote.svelte';
  import VerdictCard from '$components/home/VerdictCard.svelte';
  import StoveBanner from '$components/stove/StoveBanner.svelte';
  import StoveStart from '$components/stove/StoveStart.svelte';
  import TodayChart from '$components/home/TodayChart.svelte';
  import {
    buildLanes,
    lastRunOf,
    COMFORT_HALF_BAND_K,
    DAY_SIGNALS,
    foreignZone,
    insightToday,
    RANGE_MS,
    seriesPoints,
    serviceMidnight,
    SIGNAL,
    yesterdaySoFar,
    todayStats,
    withDaily,
    type RangeKey,
  } from '$components/home/model';
  import type { Point } from '$lib/core/chart';
  import { trendPerHour } from '$lib/core/chartSummary';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { liveFact } from '$lib/core/controlText';
  import { formatNumber } from '$lib/core/format';
  import { hotWater } from '$lib/core/hotWater.svelte';
  import { minus } from '$lib/core/minus';
  import { tonightHeating, tonightOf, verdictOf } from '$lib/home/verdict';
  import { getSignal, roomTrust, roomView } from '$lib/core/derive';
  import { effectiveAge } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { startOfLocalDay } from '$lib/home/energy';
  import { pumpStateOf } from '$lib/pump/pumpState';
  import { notifyHealth } from '$lib/notify/notifyHealth.svelte';
  import { hasNotifyAlarm } from '$lib/notify/notify';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { ForecastPoint, History } from '$lib/core/types';
  import { reportedTarget } from '$lib/setpoint/waterfall';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const room = $derived(roomView(live.snapshot, ctl.control, ctl.decision));
  const decision = $derived(ctl.decision);
  const roomStatus = $derived(ctl.control?.room ?? null);
  const trust = $derived(roomTrust(ctl.control, ctl.decision));
  const roomFresh = $derived(room.fresh && live.snapshot?.heishamon.alive !== false);
  const changedAgoS = $derived(
    roomStatus?.held_s != null
      ? roomStatus.held_s
      : room.age !== null
        ? effectiveAge(room.age, live.receivedAt, live.now)
        : null,
  );
  const pump = $derived(pumpStateOf(live.snapshot));
  const fact = $derived(liveFact(ctl, live.snapshot));
  const signalValue = (id: string): number | null => {
    const value = getSignal(live.snapshot, id)?.value;
    return typeof value === 'number' ? value : null;
  };

  const ready = $derived(live.snapshot !== null);
  const stoveActive = $derived(ctl.control?.stove?.active === true);
  const verdict = $derived(
    verdictOf({
      alarms: ctl.control?.alarms ?? [],
      fact,
      room: room.value,
      target: room.target,
      halfBand: COMFORT_HALF_BAND_K,
      fresh: roomFresh,
      trust: trust.trust,
      stove: stoveActive,
      notifyFailing: notifyHealth.failing && !hasNotifyAlarm(ctl.control?.alarms ?? []),
    }),
  );
  let comfortOpen = $state(false);

  let day = $state<History | null>(null);
  let dayFailed = $state(false);
  let week = $state<History | null>(null);
  let weekFailed = $state(false);
  let setpoint = $state<Point[]>([]);
  let range = $state<RangeKey>('24h');
  let forecast = $state<ForecastPoint[] | null>(null);
  let forecastOff = $state(false);

  const roomId = $derived(room.signal);
  const dayEnd = $derived(day ? Date.parse(day.to) : 0);
  const dayStart = $derived(dayEnd - RANGE_MS['24h']);
  const roomPoints = $derived(roomId ? seriesPoints(day, roomId) : []);
  const trend = $derived(trendPerHour(roomPoints));
  const lanes = $derived(
    buildLanes(
      day,
      dayEnd,
      {
        compressor: t('homeLaneCompressor'),
        defrost: t('homeLaneDefrost'),
        dhw: t('homeLaneHotWater'),
        quiet: t('homeLaneQuiet'),
        on: t('homeLaneOn'),
      },
      hotWater.shown,
    ),
  );
  const lastRun = $derived(lastRunOf(day, dayEnd));
  const daily = createInsight(1);
  $effect(() => daily.start());
  const stats = $derived(
    withDaily(
      day ? todayStats(day, dayEnd, serviceMidnight(daily.state.data)) : null,
      insightToday(daily.state.data),
    ),
  );
  const zone = $derived(foreignZone(daily.state.data));
  let yesterdayKwh = $state<number | null>(null);
  $effect(() => {
    void ready;
    const midnightOf = () =>
      serviceMidnight(daily.state.data) ?? startOfLocalDay(live.serviceNow());
    return poll(
      async (signal) => {
        const to = live.serviceNow() - 24 * 3_600_000;
        const from = midnightOf() - 24 * 3_600_000;
        if (to - from < 15 * 60_000) {
          yesterdayKwh = null;
          return;
        }
        try {
          const history = await fetchHistory([SIGNAL.electric, SIGNAL.heat], signal, {
            from: new Date(from),
            to: new Date(to),
            step: 900,
          });
          yesterdayKwh = yesterdaySoFar(history, from, to);
        } catch {
          if (!signal.aborted) yesterdayKwh = null;
        }
      },
      { intervalMs: 600_000 },
    );
  });
  const chartHistory = $derived(range === '7d' ? week : day);
  const heatingOffC = $derived(
    ctl.control?.safety?.monitors.find((m) => m.code === 'heating_off_outdoor')?.limit ?? null,
  );
  const tonight = $derived.by(() => {
    const night = tonightOf(forecast, live.clock);
    if (!night) return null;
    const heating = tonightHeating(fact, stoveActive, night.minC, heatingOffC);
    return t('tonightLine', {
      min: minus(formatNumber(night.minC, 0, settings.language)),
      heating: t(`tonightHeating_${heating}`),
    });
  });
  const chartFailed = $derived(range === '7d' ? weekFailed : dayFailed);

  $effect(() => {
    void ready;
    const ids = [...DAY_SIGNALS, ...(roomId ? [roomId] : [])];
    return poll(
      async (signal) => {
        const to = new Date(live.serviceNow());
        const from = new Date(to.getTime() - RANGE_MS['24h']);
        try {
          day = await fetchHistory(ids, signal, { from, to, step: 60 });
          dayFailed = false;
        } catch {
          if (!signal.aborted) dayFailed = true;
        }
      },
      { intervalMs: 120_000 },
    );
  });

  $effect(() => {
    if (range !== '7d') return;
    void ready;
    const ids = [SIGNAL.outside, SIGNAL.outlet, SIGNAL.inlet, ...(roomId ? [roomId] : [])];
    return poll(
      async (signal) => {
        const to = new Date(live.serviceNow());
        const from = new Date(to.getTime() - RANGE_MS['7d']);
        try {
          week = await fetchHistory(ids, signal, { from, to, step: 900 });
          weekFailed = false;
        } catch {
          if (!signal.aborted) weekFailed = true;
        }
      },
      { intervalMs: 600_000 },
    );
  });

  $effect(() => {
    void ready;
    const span = RANGE_MS[range];
    return poll(
      async (signal) => {
        const to = new Date(live.serviceNow());
        const from = new Date(to.getTime() - span);
        try {
          const series = await fetchSeries({ from, to, step: range === '7d' ? 3600 : 900 }, signal);
          setpoint = series.at.flatMap((at, i): Point[] => {
            const value = series.setpoint[i];
            return typeof value === 'number' ? [[Date.parse(at), value]] : [];
          });
        } catch {
          if (!signal.aborted) setpoint = [];
        }
      },
      { intervalMs: 300_000 },
    );
  });

  $effect(() => {
    return poll(
      async (signal) => {
        try {
          const weather = await fetchWeather(1, 26, signal);
          forecastOff = !weather.enabled;
          forecast = weather.enabled ? (weather.forecast?.points ?? []) : null;
        } catch {
          forecast = null;
          forecastOff = false;
        }
      },
      { intervalMs: 600_000 },
    );
  });
</script>

<h1 class="visually-hidden">{t('navHome')}</h1>

<div class="stack">
  <VerdictCard {verdict} {tonight} clock={live.clock} />
  <StoveBanner {ctl} {live} />
  <SummerNote {ctl} />

  <div class="grid top">
    <RoomCard
      value={room.value}
      target={room.target}
      halfBand={COMFORT_HALF_BAND_K}
      {trend}
      fresh={roomFresh}
      {changedAgoS}
      configured={!(ctl.control && !ctl.control.room)}
      trust={trust.trust}
      authority={trust.authority}
      ontarget={ctl.config ? () => (comfortOpen = true) : undefined}
    >
      {#snippet actions()}<StoveStart {ctl} {live} compact />{/snippet}
    </RoomCard>
    <PumpCard
      state={pump}
      electricW={signalValue('main/Heat_Power_Consumption')}
      heatW={signalValue('main/Heat_Power_Production')}
      inletC={signalValue('main/Main_Inlet_Temp')}
      outletC={signalValue('main/Main_Outlet_Temp')}
      flowLpm={signalValue('main/Pump_Flow')}
      {decision}
      reportedC={fact.sending ? (decision ? reportedTarget(decision) : null) : fact.water.pumpHas}
      sending={fact.sending || fact.kind === 'unknown'}
      wouldSendC={fact.water.wouldSend}
      {lastRun}
      startsToday={stats?.starts ?? null}
      decisionsLoaded={ctl.loaded}
    />
  </div>

  {#if ctl.control?.boost?.enabled || ctl.control?.away?.enabled}
    <div class="manual">
      <BoostControl {ctl} {live} />
      <AwayControl {ctl} {live} />
    </div>
  {/if}

  <DayStrip {lanes} from={dayStart} to={dayEnd} loading={day === null} failed={dayFailed} />

  <TodayChart
    history={chartHistory}
    {setpoint}
    {range}
    onrange={(next) => (range = next)}
    {roomId}
    target={room.target}
    halfBand={COMFORT_HALF_BAND_K}
    loading={chartHistory === null}
    failed={chartFailed}
  />

  <HomeTiles {stats} {forecast} {forecastOff} nowMs={dayEnd} {zone} {yesterdayKwh} />

  <WeekCard />
</div>

{#if comfortOpen}
  <ComfortSheet {ctl} room={room.value} onclose={() => (comfortOpen = false)} />
{/if}

<style>
  .manual {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
    gap: var(--space-3);
    align-items: start;
  }
  .top {
    align-items: stretch;
  }
  @media (--narrow) {
    .manual:has(:global(.panel)) {
      grid-template-columns: minmax(0, 1fr);
    }
    .stack,
    .manual,
    .top {
      gap: var(--space-3);
    }
  }
</style>
