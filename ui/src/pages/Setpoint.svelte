<script lang="ts">
  import { tick, untrack } from 'svelte';
  import {
    fetchAlarms,
    fetchDayShift,
    fetchDecisions,
    fetchHistory,
    fetchSeries,
    isMissing,
  } from '$lib/core/api';
  import type { Point } from '$lib/core/chart';
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import DecisionTable from '$components/setpoint/DecisionTable.svelte';
  import DayShiftCard from '$components/setpoint/DayShiftCard.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import InputsTable from '$components/setpoint/InputsTable.svelte';
  import Pill from '$ui/Pill.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import ReasonSentence from '$components/setpoint/ReasonSentence.svelte';
  import ReasonStrip from '$components/setpoint/ReasonStrip.svelte';
  import ArbiterList from '$components/setpoint/ArbiterList.svelte';
  import FactList from '$components/setpoint/FactList.svelte';
  import FlipMeter from '$components/setpoint/FlipMeter.svelte';
  import Pipeline from '$components/setpoint/Pipeline.svelte';
  import RoomSensor from '$components/setpoint/RoomSensor.svelte';
  import StateGauges from '$components/setpoint/StateGauges.svelte';
  import TermHistoryChart from '$components/setpoint/TermHistoryChart.svelte';
  import Waterfall from '$components/setpoint/Waterfall.svelte';
  import Why from '$ui/Why.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import {
    buildEpisodes,
    holdIntervals,
    type Episode,
    type HoldInterval,
  } from '$lib/setpoint/episodes';
  import {
    decisionFacts,
    flipModel,
    inputViews,
    numberFormats,
    roomFacts,
  } from '$lib/setpoint/explain';
  import { formatClock, formatDateTime } from '$lib/core/format';
  import type { IconName } from '$lib/core/icons';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { router } from '$lib/core/router.svelte';
  import {
    reasonCategory,
    seriesFromDecisions,
    stackSeries,
    type StackedSeries,
  } from '$lib/setpoint/series';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import { dayshiftShown } from '$lib/setpoint/dayshift';
  import { poll } from '$lib/core/poll.svelte';
  import type { DayShift, Decision, DecisionSeries } from '$lib/core/types';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const HOUR = 3_600_000;
  const MINUTE = 60_000;
  const FALLBACK_LIMIT = 720;

  const at = $derived(router.location.query['at'] ?? null);
  const rangeOptions = $derived(
    [6, 24, 168].map((h) => ({
      value: h,
      label: h >= 48 ? t('rangeDays', { n: h / 24 }) : t('rangeHours', { n: h }),
    })),
  );
  const hours = $derived.by(() => {
    const value = Number(router.location.query['range']);
    return [6, 24, 168].includes(value) ? value : 24;
  });
  const atMs = $derived(at ? Date.parse(at) : Number.NaN);

  let dayshift = $state<DayShift | null>(null);
  $effect(() => {
    return poll(
      async (signal) => {
        try {
          dayshift = await fetchDayShift(signal);
        } catch {
          if (!signal.aborted) dayshift = null;
        }
      },
      { intervalMs: 30_000 },
    );
  });

  let picked = $state<Decision | null>(null);
  let pickedMissing = $state(false);
  let recent = $state<Decision[]>([]);

  let cache: Record<number, Decision> = {};
  let cached = 0;

  async function decisionNear(ms: number, signal?: AbortSignal): Promise<Decision | null> {
    const key = Math.round(ms / MINUTE);
    const hit = cache[key];
    if (hit) return hit;
    const response = await fetchDecisions(
      { from: new Date(ms - 90_000), to: new Date(ms + 90_000), limit: 5 },
      signal,
    );
    const best =
      [...response.decisions].sort(
        (a, b) => Math.abs(Date.parse(a.at) - ms) - Math.abs(Date.parse(b.at) - ms),
      )[0] ?? null;
    if (best) {
      if (cached >= 400) {
        cache = {};
        cached = 0;
      }
      cache[key] = best;
      cached += 1;
    }
    return best;
  }

  $effect(() => {
    const target = at;
    const ms = atMs;
    if (!target || Number.isNaN(ms)) {
      picked = null;
      pickedMissing = false;
      return;
    }
    const controller = new AbortController();
    decisionNear(ms, controller.signal)
      .then((best) => {
        picked = best;
        pickedMissing = best === null;
      })
      .catch(() => {
        if (!controller.signal.aborted) pickedMissing = true;
      });
    return () => controller.abort();
  });

  $effect(() => {
    void live.decisionSeq;
    const controller = new AbortController();
    fetchDecisions({ limit: 60 }, controller.signal)
      .then((response) => (recent = response.decisions))
      .catch(() => undefined);
    return () => controller.abort();
  });

  interface HistoryData {
    from: number;
    to: number;
    series: DecisionSeries;
    stacked: StackedSeries;
    holds: HoldInterval[];
    room: Point[];
    limited: boolean;
  }

  let history = $state<HistoryData | null>(null);
  let historyState = $state<'loading' | 'ok' | 'error'>('loading');

  const nowMs = $derived(live.snapshot ? Date.parse(live.snapshot.at) : null);
  const bucket = $derived(nowMs === null ? null : Math.floor(nowMs / MINUTE));
  const roomSignal = $derived(
    ctl.control?.room?.signal ??
      ctl.decision?.record.inputs_used.find((input) => input.source === 'room')?.signal ??
      null,
  );

  async function loadHistory(
    toMs: number,
    span: number,
    room: string | null,
    signal: AbortSignal,
  ): Promise<HistoryData> {
    const to = new Date(toMs);
    const from = new Date(toMs - span * HOUR);
    const step = span <= 24 ? 0 : 900;
    let series: DecisionSeries;
    let limited = false;
    try {
      series = await fetchSeries({ from, to, step }, signal);
    } catch (failure) {
      if (!isMissing(failure)) throw failure;
      const response = await fetchDecisions({ from, to, limit: FALLBACK_LIMIT }, signal);
      series = seriesFromDecisions(response.decisions, from.toISOString(), to.toISOString());
      limited = response.decisions.length >= FALLBACK_LIMIT;
    }
    const [events, roomHistory] = await Promise.all([
      fetchAlarms({ from: new Date(from.getTime() - 12 * HOUR), to }, signal)
        .then((response) => response.events)
        .catch(() => []),
      room
        ? fetchHistory([room], signal, { from, to, step: span <= 6 ? 0 : span <= 24 ? 60 : 900 })
            .then((response) => response.series[room]?.points ?? [])
            .catch(() => [])
        : Promise.resolve([]),
    ]);
    const roomPoints: Point[] = [];
    for (const [iso, value] of roomHistory) {
      const ms = Date.parse(iso);
      if (typeof value === 'number' && Number.isFinite(ms)) roomPoints.push([ms, value]);
    }
    const holds = holdIntervals(events, toMs).filter((hold) => hold.to > from.getTime());
    return {
      from: from.getTime(),
      to: toMs,
      series,
      stacked: stackSeries(series),
      holds,
      room: roomPoints,
      limited,
    };
  }

  $effect(() => {
    if (bucket === null) return;
    const span = hours;
    const room = roomSignal;
    const controller = new AbortController();
    const toMs = untrack(() => nowMs) ?? Date.now();
    loadHistory(toMs, span, room, controller.signal)
      .then((data) => {
        history = data;
        historyState = 'ok';
      })
      .catch(() => {
        if (!controller.signal.aborted) historyState = 'error';
      });
    return () => controller.abort();
  });

  const episodes = $derived<Episode[]>(
    history ? buildEpisodes(history.series, { holds: history.holds, endT: history.to }) : [],
  );

  let scrub = $state<Decision | null>(null);
  let scrubTimer: number | null = null;
  let scrubSeq = 0;
  let nowCard = $state<HTMLElement>();
  let changeCard = $state<HTMLElement>();
  let lock = $state<{ now: number; change: number } | null>(null);
  let clipped = $state({ now: false, change: false });

  function oncursor(ms: number | null): void {
    if (scrubTimer !== null) window.clearTimeout(scrubTimer);
    const seq = (scrubSeq += 1);
    if (ms === null) {
      scrub = null;
      lock = null;
      return;
    }
    if (lock === null && nowCard && changeCard)
      lock = { now: nowCard.offsetHeight, change: changeCard.offsetHeight };
    scrubTimer = window.setTimeout(() => {
      decisionNear(ms)
        .then((decision) => {
          if (seq === scrubSeq) scrub = decision;
        })
        .catch(() => undefined);
    }, 120);
  }

  $effect(() => {
    void scrub;
    if (!lock) {
      clipped = { now: false, change: false };
      return;
    }
    void tick().then(() => {
      clipped = {
        now: Boolean(nowCard && nowCard.scrollHeight > nowCard.clientHeight + 1),
        change: Boolean(changeCard && changeCard.scrollHeight > changeCard.clientHeight + 1),
      };
    });
  });

  const lockStyle = (height: number | undefined, clip: boolean): string | undefined =>
    height === undefined
      ? undefined
      : `height: ${height}px; overflow: hidden;${clip ? ' mask-image: linear-gradient(to bottom, #000 calc(100% - 2.5rem), transparent);' : ''}`;

  const base = $derived(at && picked ? picked : ctl.decision);
  const shown = $derived(scrub ?? base);
  const viewingPast = $derived(Boolean(at) && picked !== null);
  const fmt = $derived(numberFormats(settings.language));

  const flip = $derived(shown ? flipModel(shown.record) : null);
  const room = $derived(shown ? roomFacts(shown.record) : null);
  const roomFresh = $derived(
    shown?.record.inputs_used.find((input) => input.source === 'room')?.fresh ?? true,
  );
  const facts = $derived(shown ? decisionFacts(shown.record, fmt) : []);
  const inputs = $derived(shown ? inputViews(shown.record) : []);
  const freshCount = $derived(inputs.filter((input) => input.fresh).length);
  const dwellLeft = $derived.by(() => {
    const value = shown?.record.controller_state['dwell_remaining_s'];
    return typeof value === 'number' ? value : 0;
  });
  const stateMeta = $derived.by(() => {
    if (!shown) return undefined;
    const integral = shown.record.controller_state['integral_k'];
    const parts: string[] = [];
    if (typeof integral === 'number') parts.push(`∫ ${fmt.signed(integral, 1)}`);
    if (dwellLeft > 0) parts.push(t('stateMinutes', { n: Math.ceil(dwellLeft / 60) }));
    const ramp = shown.record.controller_state['ramp_phase'];
    if (typeof ramp === 'string' && ramp !== 'idle') parts.push(tc('rampPhase_', ramp));
    return parts.join(' · ') || undefined;
  });
  const field = (name: string): number | undefined => {
    const value = ctl.config?.fields[name]?.value;
    return typeof value === 'number' ? value : undefined;
  };

  const CATEGORY_ICON: Record<string, IconName> = {
    normal: 'check',
    limited: 'ramp',
    frozen: 'snowflake',
    stopped: 'pause',
    manual: 'hand',
  };
  const CATEGORY_TONE = {
    normal: 'ok',
    limited: 'limited',
    frozen: 'frozen',
    stopped: 'stopped',
    manual: 'manual',
  } as const;
  const category = $derived(shown ? reasonCategory(shown.reason) : 'normal');

  function select(ms: number): void {
    router.navigate('setpoint', [], { at: new Date(ms).toISOString(), range: String(hours) });
  }

  function setRange(next: number): void {
    router.navigate('setpoint', [], { at: at ?? undefined, range: String(next) });
  }

  const nowTitle = $derived(
    scrub
      ? t('setpointAtCursor', { time: formatClock(scrub.at, settings.language) })
      : viewingPast
        ? t('setpointAtTick')
        : t('setpointNow'),
  );
</script>

<h1>{t('setpointTitle')}</h1>

{#if viewingPast}
  <p class="viewing" role="status" data-testid="viewing-past">
    <Icon name="clock" size={18} />
    <span>{t('viewingPast')}</span>
    <a class="hit" href="#/setpoint?range={hours}">{t('backToNow')}</a>
  </p>
{:else if at && pickedMissing}
  <p class="viewing" role="status">
    <Icon name="info" size={18} />
    <span>{t('tickMissing')}</span>
    <a class="hit" href="#/setpoint?range={hours}">{t('backToNow')}</a>
  </p>
{/if}

<div class="grid">
  <Card
    span={7}
    title={nowTitle}
    icon="target"
    testid="setpoint-now"
    help="setpoint.now"
    bind:element={nowCard}
    style={lockStyle(lock?.now, clipped.now)}
  >
    {#snippet actions()}
      {#if shown}
        {#if shown.config_version !== undefined && shown.config_version !== null}
          <span class="wide-only"
            ><Pill tone="neutral" icon="settings"
              >{t('modeConfigLink', { version: shown.config_version })}</Pill
            ></span
          >
        {/if}
        <Pill tone="neutral" icon="clock">{formatDateTime(shown.at, settings.language)}</Pill>
      {/if}
    {/snippet}
    {#if shown}
      <div class="hero" class:scrubbing={scrub !== null}>
        <div class="setpoint">
          <span class="number" data-testid="setpoint-value"
            >{shown.setpoint ?? '–'}<span class="unit">°C</span></span
          >
          <span class="caption">{t('heroCaption')}</span>
        </div>
        <div class="why-col">
          <Pill tone={CATEGORY_TONE[category]} icon={CATEGORY_ICON[category]} size="md"
            >{tc('reason_', shown.reason)}</Pill
          >
          <ReasonSentence decision={shown} detailed />
        </div>
      </div>
      <FactList {facts} />
      <div class="built" data-help="setpoint.waterfall">
        <div class="sub-head">
          <h3>{t('waterfallTitle')}</h3>
          <Why title={t('waterfallTitle')} ariaLabel={t('waterfallHelpLabel')} align="end">
            <p>{t('waterfallHelp')}</p>
            <p>{t('waterfallHelpColours')}</p>
          </Why>
        </div>
        <Waterfall decision={shown} />
      </div>
    {:else if ctl.loaded}
      <p class="muted">{t('noDecision')}</p>
    {:else}
      <p class="muted">{t('loading')}</p>
    {/if}
  </Card>

  <Card
    span={5}
    title={t('changeTitle')}
    icon="trendUp"
    testid="setpoint-change"
    help="setpoint.change"
    bind:element={changeCard}
    style={lockStyle(lock?.change, clipped.change)}
  >
    {#if shown}
      {#if flip}
        <FlipMeter model={flip} dwellLeftS={dwellLeft} />
      {:else}
        <p class="muted">{t('flipNone')}</p>
      {/if}
      {#if room}
        <section class="part" aria-labelledby="room-title">
          <h3 id="room-title">{t('roomTitle')}</h3>
          <RoomSensor facts={room} fresh={roomFresh} />
        </section>
      {/if}
      <div class="more" data-help="setpoint.details">
        <Details
          summary={t('stateTitle')}
          icon="cpu"
          meta={stateMeta}
          id="setpoint-state"
          testid="setpoint-state"
        >
          <div class="state">
            <Pipeline record={shown.record} />
            <StateGauges
              record={shown.record}
              integralLimit={field('control_feedback_integral_limit_k')}
              dwellTotalS={field('control_dwell_s')}
            />
          </div>
        </Details>
        <Details
          summary={t('inputsTitle')}
          icon="chart"
          meta={t('inputsFresh', { fresh: freshCount, n: inputs.length })}
          id="setpoint-inputs"
          testid="setpoint-inputs"
        >
          <InputsTable record={shown.record} />
        </Details>
        <Details
          summary={t('arbiterTitle')}
          icon="upload"
          meta={shown.commands.length > 0 ? shown.commands.length : undefined}
          id="setpoint-arbiter"
          testid="setpoint-arbiter"
        >
          <ArbiterList decision={shown} />
        </Details>
      </div>
    {/if}
  </Card>

  {#if dayshift && dayshiftShown(dayshift)}
    <DayShiftCard shift={dayshift} />
  {/if}

  <Card
    span={12}
    title={t('historyTitle')}
    icon="chart"
    testid="setpoint-history"
    help="setpoint.history"
  >
    {#snippet actions()}
      <Segmented options={rangeOptions} value={hours} onchange={setRange} label={t('rangeLabel')} />
      <Why title={t('historyTitle')} align="end">
        <p>{t('historyHint')}</p>
        <p>{t('historyHelpBands')}</p>
      </Why>
    {/snippet}
    {#if history && history.stacked.points.length > 0}
      <TermHistoryChart
        from={history.from}
        to={history.to}
        stacked={history.stacked}
        room={history.room}
        target={(shown?.record.controller_state['room_target_c'] as number | null) ?? null}
        holds={history.holds}
        now={nowMs}
        selected={viewingPast ? atMs : null}
        onselect={select}
        {oncursor}
      />
      <ReasonStrip segments={history.stacked.reasons} from={history.from} to={history.to} />
      {#if history.limited}
        <p class="muted note">{t('historyLimited')}</p>
      {/if}
    {:else if historyState === 'loading'}
      <p class="muted">{t('chartLoading')}</p>
    {:else if historyState === 'error'}
      <p class="muted">{t('chartError')}</p>
    {:else}
      <EmptyState art="noData" size="small" text={t('chartEmpty')} />
    {/if}
  </Card>

  <Card
    span={12}
    title={t('episodesTitle', {
      range: hours >= 48 ? t('rangeDays', { n: hours / 24 }) : t('rangeHours', { n: hours }),
    })}
    icon="clock"
    testid="setpoint-table-card"
    help="setpoint.episodes"
  >
    {#snippet actions()}
      <Why title={t('episodesTitle', { range: '' })} align="end">
        <p>{t('episodesHelp')}</p>
        {#if hours > 24}<p>{t('episodesCoarse')}</p>{/if}
      </Why>
    {/snippet}
    <DecisionTable
      {episodes}
      decisions={recent}
      selected={viewingPast ? atMs : null}
      range={hours}
      now={nowMs ?? Date.now()}
    />
  </Card>
</div>

<style>
  .viewing {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0 0 var(--space-3);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .hero {
    display: flex;
    gap: var(--space-4);
    align-items: flex-start;
  }
  .hero.scrubbing .number {
    color: var(--accent);
  }
  .setpoint {
    display: grid;
    justify-items: start;
    flex: none;
  }
  .number {
    font-size: var(--fs-hero);
    font-family: var(--font-display);
    font-weight: var(--fw-bold);
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .number .unit {
    font-size: var(--fs-value);
    font-weight: var(--fw-medium);
    color: var(--muted);
    margin-left: 0.15rem;
  }
  .caption {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .why-col {
    display: grid;
    gap: var(--space-2);
    justify-items: start;
    min-width: 0;
  }
  .built {
    display: grid;
    gap: var(--space-3);
    min-width: 0;
  }
  .sub-head {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  h3 {
    margin: 0;
    font-size: var(--fs-body);
    font-weight: var(--fw-semibold);
  }
  .part {
    display: grid;
    gap: var(--space-2);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border);
  }
  .part h3 {
    font-size: var(--fs-caption);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .more {
    display: grid;
    border-top: 1px solid var(--border);
    padding-top: var(--space-1);
  }
  .state {
    display: grid;
    gap: var(--space-3);
  }
  .note {
    font-size: var(--fs-caption);
    margin: 0;
  }
  @container main (max-width: 40rem) {
    .viewing {
      flex-wrap: nowrap;
      gap: 0.4rem;
      padding-block: 0.35rem;
      font-size: var(--fs-caption);
    }
    .viewing span {
      flex: 1;
      min-width: 0;
    }
    .viewing a {
      white-space: nowrap;
    }
    .wide-only {
      display: none;
    }
    .hero {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: var(--space-2) var(--space-3);
      align-items: center;
    }
    .why-col {
      display: contents;
    }
    .why-col > :global(*) {
      justify-self: start;
    }
    .why-col > :global(.reason) {
      grid-column: 1 / -1;
    }
    .number {
      font-size: var(--fs-display-5);
    }
  }
</style>
