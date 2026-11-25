<!--
  RoomSensor: how the controller judged the room value for this decision: the value and sensor
  step, how long it has been held (on-change sensors) or how old it is (periodic), the last proof
  of life and which signal gave it, the cooling authority when it is reduced, and the cross-check.

  Props: facts (RoomFacts from lib/explain), fresh (the room input was usable).
  A11y: a list of icon + text rows; the authority bar has its percentage as text.
-->
<script lang="ts">
  import {
    livenessKind,
    livenessLabel,
    numberFormats,
    type RoomFacts,
  } from '$lib/setpoint/explain';
  import { formatDuration } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  let { facts, fresh = true }: { facts: RoomFacts; fresh?: boolean } = $props();

  const fmt = $derived(numberFormats(settings.language));
  const onChange = $derived(facts.profile === 'on_change');
  const authority = $derived(facts.authority === null ? null : Math.round(facts.authority * 100));
</script>

<ul class="room" data-testid="room-sensor">
  <li>
    <Icon name="thermometer" size={18} />
    <span>
      <strong class="value">{facts.value === null ? '–' : `${fmt.plain(facts.value, 1)} °C`}</strong
      >
      {#if facts.quantumK}
        <span class="muted">{t('roomStep', { step: fmt.plain(facts.quantumK, 1) })}</span>
      {/if}
      {#if onChange && facts.heldS !== null}
        <span class="muted">· {t('roomHeld', { duration: formatDuration(facts.heldS) })}</span>
      {:else if !onChange && facts.aliveS !== null}
        <span class="muted">· {t('roomAge', { duration: formatDuration(facts.aliveS) })}</span>
      {/if}
    </span>
  </li>
  {#if onChange && facts.aliveS !== null}
    <li data-testid="room-alive">
      <i class="dot" class:stale={!fresh} aria-hidden="true"></i>
      <span>
        {#if facts.aliveBy}
          {t('roomAliveBy', {
            signal: livenessKind(livenessLabel(facts.aliveBy, facts.signal), (key) => tOpt(key)),
            duration: formatDuration(facts.aliveS),
          })}
        {:else}
          {t('roomLastReport', { duration: formatDuration(facts.aliveS) })}
        {/if}
        {#if !fresh}<strong class="warn">· {t('roomNotUsable')}</strong>{/if}
      </span>
    </li>
  {/if}
  {#if authority !== null && authority < 100}
    <li data-testid="room-authority">
      <Icon name="trendDown" size={18} />
      <span class="authority">
        <span>{t('roomAuthority', { pct: authority })}</span>
        <span class="bar" aria-hidden="true"><i style:width="{authority}%"></i></span>
      </span>
    </li>
  {/if}
  {#if facts.plausible !== null}
    <li>
      <Icon name={facts.plausible ? 'check' : 'warning'} size={18} />
      <span class:warn={!facts.plausible}>
        {facts.plausible
          ? t('roomCrossOk', {
              k: facts.deviationK === null ? '–' : fmt.plain(Math.abs(facts.deviationK), 1),
            })
          : t('roomCrossBad')}
      </span>
    </li>
  {/if}
</ul>

<style>
  .room {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.35rem;
  }
  li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }
  li > :global(svg) {
    color: var(--muted);
  }
  .value {
    font-variant-numeric: tabular-nums;
  }
  .dot {
    flex: none;
    width: 0.6rem;
    height: 0.6rem;
    margin: 0 0.2rem;
    border-radius: 50%;
    background: var(--status-ok);
  }
  .dot.stale {
    background: var(--status-limited);
  }
  .warn {
    color: var(--status-limited);
  }
  .authority {
    display: grid;
    gap: 0.2rem;
    flex: 1;
  }
  .bar {
    display: block;
    height: 6px;
    border-radius: var(--radius-xs);
    background: var(--surface-2);
    box-shadow: inset 0 0 0 1px var(--border);
    overflow: hidden;
  }
  .bar i {
    display: block;
    height: 100%;
    background: var(--status-limited);
  }
</style>
