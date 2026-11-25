<!--
  StateGauges: the controller's memory at this decision as small gauges: the integrator as a
  marker inside its ± limit (with a lock when frozen and why), the wait time as a countdown ring,
  the start-ramp phase and the filtered outside temperature the curve uses (with the chosen
  outside sensor it came from, or the pump's sensor when that one fell back).

  Props: record (DecisionRecord); integralLimit (K, default 3); dwellTotalS (s, default 900).
  A11y: every gauge has its value as text next to it; the graphics are aria-hidden.
-->
<script lang="ts">
  import { curveOutside, numberFormats } from '$lib/setpoint/explain';
  import { signalName } from '$lib/core/signalView';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import type { DecisionRecord } from '$lib/core/types';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    record: DecisionRecord;
    integralLimit?: number;
    dwellTotalS?: number;
  }

  const frozenLabel = (name: string) => tOpt(`frozenBy_${name}`) ?? tc('reason_', name);

  let { record, integralLimit = 3, dwellTotalS = 900 }: Props = $props();

  const fmt = $derived(numberFormats(settings.language));
  const num = (key: string): number | null => {
    const value = record.controller_state[key];
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  };
  const str = (key: string): string | null => {
    const value = record.controller_state[key];
    return typeof value === 'string' && value !== '' ? value : null;
  };

  const integral = $derived(num('integral_k'));
  const limit = $derived(Math.max(integralLimit, Math.abs(integral ?? 0), 0.1));
  const marker = $derived(integral === null ? 50 : 50 + (integral / limit) * 50);
  const frozen = $derived((str('frozen_by') ?? '').split(',').filter(Boolean));
  const dwell = $derived(num('dwell_remaining_s') ?? 0);
  const dwellShare = $derived(Math.min(1, Math.max(0, dwell / Math.max(dwellTotalS, 1))));
  const ramp = $derived(str('ramp_phase') ?? 'idle');
  const outside = $derived(num('outside_filtered_c'));
  const chosen = $derived(curveOutside(record));
  const R = 9;
  const C = 2 * Math.PI * R;
</script>

<div class="gauges" data-testid="controller-state">
  <div class="gauge integrator">
    <span class="label">{t('stateIntegral')}</span>
    <span class="value">
      {integral === null ? '–' : fmt.signed(integral, 1)}
      {#if frozen.length > 0}
        <span class="frozen" title={frozen.map((name) => frozenLabel(name)).join(', ')}>
          <Icon name="lock" size={14} />{frozen.map((name) => frozenLabel(name)).join(', ')}
        </span>
      {/if}
    </span>
    <span class="bar" aria-hidden="true">
      <i class="zero"></i>
      <i class="fill" style:left="{Math.min(50, marker)}%" style:width="{Math.abs(marker - 50)}%"
      ></i>
      <i class="mark" style:left="{marker}%"></i>
    </span>
    <span class="ends" aria-hidden="true"
      ><span>{fmt.signed(-limit, 0)}</span><span>{fmt.signed(limit, 0)}</span></span
    >
  </div>

  <div class="gauge">
    <span class="label">{t('stateDwell')}</span>
    <span class="value ring-row">
      <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r={R} class="ring-track" />
        <circle
          cx="12"
          cy="12"
          r={R}
          class="ring"
          stroke-dasharray="{C * dwellShare} {C}"
          transform="rotate(-90 12 12)"
        />
      </svg>
      {dwell > 0 ? t('stateMinutes', { n: Math.ceil(dwell / 60) }) : t('stateFree')}
    </span>
  </div>

  <div class="gauge">
    <span class="label">{t('stateRamp')}</span>
    <span class="value" class:active={ramp !== 'idle'}>
      <Icon name="ramp" size={16} />{tc('rampPhase_', ramp)}
    </span>
  </div>

  <div class="gauge">
    <span class="label">{t('stateOutside')}</span>
    <span class="value"
      ><Icon name="thermometer" size={16} />{outside === null
        ? '–'
        : `${fmt.plain(outside, 1)} °C`}</span
    >
    {#if chosen}
      <span class="source" class:fallback={chosen.fallback} data-testid="state-outside-source"
        >{chosen.fallback
          ? t('stateOutsideFallback')
          : t('stateOutsideFrom', { name: signalName(chosen.signal, null, tOpt) })}</span
      >
    {/if}
  </div>
</div>

<style>
  .source {
    font-size: var(--fs-caption);
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .source.fallback {
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .gauges {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--space-3) var(--space-4);
  }
  .integrator {
    grid-column: 1 / -1;
  }
  .gauge {
    display: grid;
    gap: 0.2rem;
    min-width: 0;
  }
  .label {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .value {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem;
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
  .value :global(svg) {
    color: var(--muted);
  }
  .value.active,
  .value.active :global(svg) {
    color: var(--status-limited);
  }
  .frozen {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    font-weight: var(--fw-regular);
    font-size: var(--fs-caption);
    color: var(--status-frozen);
  }
  .frozen :global(svg) {
    color: var(--status-frozen);
  }
  .bar {
    position: relative;
    height: 8px;
    border-radius: var(--radius-s);
    background: var(--surface-2);
    box-shadow: inset 0 0 0 1px var(--border);
  }
  .bar i {
    position: absolute;
    top: 0;
    bottom: 0;
  }
  .zero {
    left: 50%;
    width: 1px;
    background: var(--muted);
  }
  .fill {
    background: color-mix(in srgb, var(--band-feedback) 45%, transparent);
    border-radius: var(--radius-s);
  }
  .mark {
    width: 4px;
    margin-left: -2px;
    top: -3px !important;
    bottom: -3px !important;
    border-radius: var(--radius-2xs);
    background: var(--band-feedback);
  }
  .ends {
    display: flex;
    justify-content: space-between;
    font-size: var(--fs-2xs);
    color: var(--muted);
  }
  .ring-track {
    fill: none;
    stroke: var(--surface-2);
    stroke-width: 3;
  }
  .ring {
    fill: none;
    stroke: var(--status-limited);
    stroke-width: 3;
    stroke-linecap: round;
  }
  @container main (max-width: 22rem) {
    .gauges {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
