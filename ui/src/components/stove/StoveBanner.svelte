<!--
  StoveBanner: while wood-stove mode is active, what it does, following the control fact: "Wood
  stove: heating backed off by 3 K" while ovenbird sends; otherwise "ovenbird would lower the
  heating by 3 K, but it only watches (is paused, waits, …); nothing is sent". A second line says
  whether the rest of the house is watched (a reference room with a fresh reading), not watched
  (no reference room) or cannot be watched (the reference room has no recent reading, amber).
  Then how it started (detected automatically or by hand), since when, until when for a manual
  episode, and Stop. Stop ends the episode at once; the automatic detection then waits until the
  room has cooled below the exit threshold. Renders nothing without an active episode.

  Props: ctl (ControlStore), live (LiveStore, for the service clock and the control fact),
  compact (inside the mode sheet: no border), testid.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import { liveFact } from '$lib/core/controlText';
  import { formatClock, formatDateTime, formatNumber } from '$lib/core/format';
  import type { MessageKey } from '$lib/i18n';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import { signalName } from '$lib/core/signalView';
  import { stoveHeadlineKey, stoveOrigin, stoveReference } from '$lib/stove/stove';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    ctl: ControlStore;
    live: LiveStore;
    compact?: boolean;
    testid?: string;
  }

  let { ctl, live, compact = false, testid = 'stove-banner' }: Props = $props();

  const stove = $derived(ctl.control?.stove ?? null);
  const origin = $derived(stoveOrigin(stove));
  const locale = $derived(settings.language);
  const backoff = $derived(
    stove?.backoff_k != null ? formatNumber(stove.backoff_k, 1, locale) : '–',
  );
  const fact = $derived(liveFact(ctl, live.snapshot));
  const headline = $derived(
    t(stoveHeadlineKey(fact.kind, fact.sending) as MessageKey, { k: backoff }),
  );
  const refSignal = $derived.by(() => {
    const value = ctl.config?.fields['control_stove_reference_signal']?.value;
    return typeof value === 'string' && value ? value : null;
  });
  const reference = $derived(stoveReference(stove, refSignal));
  const refText = $derived(
    t(`stoveRef_${reference}` as MessageKey, {
      room: refSignal ? signalName(refSignal, null, tOpt) : '',
      value: stove?.reference_c != null ? formatNumber(stove.reference_c, 1, locale) : '–',
    }),
  );
  const detail = $derived.by(() => {
    if (!stove || !origin) return '';
    const time = stove.since ? formatClock(stove.since, locale) : '–';
    if (origin === 'manual') {
      const until = stove.request?.on && stove.request.until ? stove.request.until : null;
      return t('stoveBannerManual', {
        time,
        until: until ? formatDateTime(until, locale, live.clock) : '–',
      });
    }
    return t(origin === 'handover' ? 'stoveBannerHandover' : 'stoveBannerAuto', { time });
  });

  let busy = $state(false);
  let failure = $state<string | null>(null);

  async function stop(): Promise<void> {
    busy = true;
    failure = null;
    const error = await ctl.stove(null, live.serviceNow());
    busy = false;
    if (error !== null) failure = t(actionKey(error));
  }
</script>

{#if stove?.active}
  <div
    class="stove"
    class:compact
    class:idle={!fact.sending && fact.kind !== 'unknown'}
    role="status"
    data-testid={testid}
    data-origin={origin}
    data-control={fact.kind}
  >
    <Icon name="flame" size={20} />
    <div class="text">
      <strong data-testid="{testid}-headline">{headline}</strong>
      {#if ctl.config}
        <span
          class="reference"
          class:warn={reference === 'stale'}
          data-testid="{testid}-reference"
          data-reference={reference}
          >{#if reference === 'stale'}<Icon name="warning" size={14} />{/if}{refText}</span
        >
      {/if}
      <span class="detail">{detail}</span>
      {#if failure}<span class="error" role="alert">{failure}</span>{/if}
    </div>
    <Button
      class="stove-stop"
      onclick={stop}
      disabled={busy}
      aria-label={t('stoveStopLabel')}
      data-testid="{testid}-stop"
    >
      {t('stoveStop')}
    </Button>
  </div>
{/if}

<style>
  .stove {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--status-limited);
    border-radius: var(--radius);
    background: var(--status-limited-bg);
    color: var(--text);
  }
  .stove > :global(.icon) {
    flex: none;
    color: var(--status-limited);
  }
  .stove.compact {
    padding: var(--space-2);
  }
  .text {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    gap: 0.1rem;
  }
  .stove.idle {
    border-color: var(--status-manual);
    background: var(--status-manual-bg);
  }
  .stove.idle > :global(.icon) {
    color: var(--status-manual);
  }
  .detail,
  .reference {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .reference.warn {
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .reference :global(.icon) {
    vertical-align: -2px;
    margin-right: var(--space-1);
  }
  .error {
    color: var(--err-text);
    font-size: var(--fs-caption);
  }
  :global(.stove-stop) {
    flex: none;
  }
</style>
