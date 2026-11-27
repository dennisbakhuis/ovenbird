<!--
  PumpCard: pump state chip (defrost > hot water > running > idle > off; with hot water hidden a
  hot-water run reads "Pump busy elsewhere" under a gear; a defrost of a known model reads
  "Defrosting · mode 2" with the long form as its title and a caption line saying what the mode
  means for the water pump), power flow with COP,
  water loop and the water setpoint with a link to its explanation. While ovenbird sends, the line
  reads "Water setpoint 29 °C"; in every other state "Would send 29 °C · Pump has 31 °C", both at
  the same weight.

  Props: state (PumpState), electricW, heatW, inletC, outletC, flowLpm (number | null),
  decision (latest Decision | null), reportedC (what the pump has as target), sending (ovenbird
  sends to the pump right now; from the control fact), wouldSendC (what ovenbird would send), lastRun (latest
  compressor run, for the idle card), startsToday, decisionsLoaded (decisions fetched at least
  once). The setpoint waterfall sits folded in a Details at the bottom, on every width.
-->
<script lang="ts">
  import { formatClock, formatDuration, formatNumber } from '$lib/core/format';
  import { BUSY_ICON, hotWater } from '$lib/core/hotWater.svelte';
  import { minus } from '$lib/core/minus';
  import type { IconName } from '$lib/core/icons';
  import type { MessageKey } from '$lib/i18n';
  import type { PumpState, PumpStateKind } from '$lib/pump/pumpState';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { Decision } from '$lib/core/types';
  import PowerFlow from '$components/charts/PowerFlow.svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';
  import Waterfall from '$components/setpoint/Waterfall.svelte';
  import type { LastRun } from './model';

  interface Props {
    state: PumpState;
    electricW: number | null;
    heatW: number | null;
    inletC: number | null;
    outletC: number | null;
    flowLpm: number | null;
    decision: Decision | null;
    reportedC: number | null;
    sending?: boolean;
    wouldSendC?: number | null;
    lastRun?: LastRun | null;
    startsToday?: number | null;
    decisionsLoaded?: boolean;
  }

  let {
    state,
    electricW,
    heatW,
    inletC,
    outletC,
    flowLpm,
    decision,
    reportedC,
    sending = true,
    wouldSendC = null,
    lastRun = null,
    startsToday = null,
    decisionsLoaded = true,
  }: Props = $props();

  type Tone = 'ok' | 'limited' | 'frozen' | 'stopped' | 'manual' | 'unknown';
  const LOOK: Record<PumpStateKind, { key: MessageKey; tone: Tone; icon: IconName }> = {
    defrost: { key: 'pumpStateDefrost', tone: 'frozen', icon: 'snowflake' },
    dhw: { key: 'pumpStateDhw', tone: 'manual', icon: 'droplet' },
    running: { key: 'pumpStateRunning', tone: 'ok', icon: 'flame' },
    idle: { key: 'pumpStateIdle', tone: 'unknown', icon: 'pause' },
    off: { key: 'pumpStateOff', tone: 'stopped', icon: 'power' },
    offline: { key: 'pumpStateOffline', tone: 'stopped', icon: 'warning' },
    unknown: { key: 'pumpStateUnknown', tone: 'unknown', icon: 'info' },
  };

  const locale = $derived(settings.language);
  const look = $derived(
    state.kind === 'dhw' && !hotWater.shown ? { ...LOOK.dhw, icon: BUSY_ICON } : LOOK[state.kind],
  );
  const deice = $derived(state.kind === 'defrost' ? (state.deice ?? null) : null);
  const stateText = $derived(
    deice === null ? t(look.key) : t('pumpStateDefrostMode', { mode: deice }),
  );
  const delta = $derived(inletC !== null && outletC !== null ? outletC - inletC : null);
  const num = (value: number, digits = 1) => minus(formatNumber(value, digits, locale));
  const water = $derived(
    inletC !== null && outletC !== null
      ? t('pumpWater', { inlet: num(inletC), outlet: num(outletC) })
      : '',
  );
  const runLine = $derived.by(() => {
    if (!lastRun) return '';
    const clock = (ms: number) => formatClock(ms, locale);
    const parts = lastRun.running
      ? [t('pumpRunSince', { from: clock(lastRun.from) })]
      : [
          t('pumpLastRun', {
            from: clock(lastRun.from),
            to: clock(lastRun.to),
            len: formatDuration((lastRun.to - lastRun.from) / 1000),
          }),
        ];
    if (startsToday !== null) parts.push(t('pumpStartsToday', { n: startsToday }));
    return parts.join(' · ');
  });
  const loop = $derived(
    [
      water,
      delta !== null && flowLpm !== null
        ? t('pumpWaterDelta', { delta: num(delta), flow: num(flowLpm) })
        : '',
    ]
      .filter(Boolean)
      .join(' · '),
  );
</script>

<Card title={t('homePumpTitle')} icon="pump" span={7} testid="pump-card" help="home.pump">
  {#snippet actions()}
    <span class="state" data-testid="pump-state" data-state={state.kind}>
      <Pill
        tone={look.tone}
        icon={look.icon}
        size="md"
        title={deice === null ? undefined : t(`deiceMode_${deice}`)}
        data-deice={deice ?? undefined}>{stateText}</Pill
      >
      {#if state.frequencyHz !== null && state.kind !== 'idle' && state.kind !== 'off'}
        <span class="hz">{num(state.frequencyHz, 0)} Hz</span>
      {/if}
      {#if state.quiet}<Icon name="moon" size={16} label={t('pumpQuiet')} />{/if}
    </span>
  {/snippet}
  <PowerFlow {electricW} {heatW} compact />
  {#if loop}
    <p class="caption loop">{loop}</p>
  {/if}
  {#if deice !== null}
    <p class="caption deice" data-testid="pump-deice" data-deice={deice}>
      {t(`deiceNote_${deice}`)}
    </p>
  {/if}
  {#if runLine && state.kind !== 'defrost' && state.kind !== 'dhw'}
    <p class="caption runs" data-testid="pump-runs">{runLine}</p>
  {/if}
  <div class="setpoint" data-testid="setpoint-line" data-sending={sending}>
    {#if sending}
      <span class="muted">{t('pumpSetpoint')}</span>
      <strong>{decision?.setpoint != null ? `${num(decision.setpoint)} °C` : '–'}</strong>
      {#if reportedC !== null && decision?.setpoint != null && reportedC !== decision.setpoint}
        <span class="muted">→ {t('pumpReports')} {num(reportedC)} °C</span>
      {/if}
    {:else}
      {@const would = wouldSendC ?? decision?.setpoint ?? null}
      <span class="half" data-testid="setpoint-would">
        <span class="muted">{t('pumpWouldSend')}</span>
        <strong>{would !== null ? `${num(would)} °C` : '–'}</strong>
      </span>
      <span class="half" data-testid="setpoint-has">
        <span class="muted">{t('pumpHas')}</span>
        <strong>{reportedC !== null ? `${num(reportedC)} °C` : '–'}</strong>
      </span>
    {/if}
  </div>
  <div data-help="home.why">
    <Details summary={t('homeWhyTitle')} id="home-why" icon="why" testid="why-card">
      {#if decision}
        <Waterfall {decision} compact />
      {:else if decisionsLoaded}
        <p class="muted">{t('noDecision')}</p>
      {:else}
        <p class="muted">{t('loading')}</p>
      {/if}
      <a href="#/setpoint" class="why hit" data-testid="why-more"
        >{t('pumpWhy')} <Icon name="arrowRight" size={14} /></a
      >
    </Details>
  </div>
</Card>

<style>
  .state {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--muted);
  }
  .hz {
    font-variant-numeric: tabular-nums;
    font-size: var(--fs-body);
  }
  .loop,
  .runs,
  .deice {
    margin: 0;
  }
  @media (--narrow) {
    .runs {
      display: none;
    }
  }
  .setpoint {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-2);
  }
  .half {
    display: inline-flex;
    align-items: baseline;
    gap: var(--space-2);
    margin-right: var(--space-2);
  }
  .setpoint strong {
    font-size: var(--fs-value);
    font-variant-numeric: tabular-nums;
  }
  .why {
    display: inline-flex;
    margin-top: var(--space-2);
    align-items: center;
    gap: 0.15rem;
  }
</style>
