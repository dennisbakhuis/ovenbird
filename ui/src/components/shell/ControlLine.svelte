<!--
  ControlLine: the persistent line under the status strip. In every state in which ovenbird does
  not send (Shadow next to another controller, paused, a hold, a refused publish condition, off)
  it says so and shows what ovenbird would send next to what the pump has, at equal weight; on a
  phone it also carries the control sentence, which the strip has no room for. A second row shows
  the service's date and time when its clock differs from this device's by more than 5 minutes.
  While ovenbird only watches next to another controller, a "Compare" link opens the shadow view.
  Renders nothing in the normal case. On Home the reason of a hold is left out: the verdict right
  below names it.

  Props: live (LiveStore), ctl (ControlStore).
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { liveFact, sentenceFor } from '$lib/core/controlText';
  import { formatDateTime } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { modeSheet } from '$lib/core/modeSheet.svelte';
  import { router } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';
  import PumpPair from './PumpPair.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const SKEW_MS = 5 * 60_000;

  const fact = $derived(liveFact(ctl, live.snapshot));
  const sentence = $derived(
    sentenceFor(fact, settings.language, live.clock, true, router.route === 'home'),
  );
  const show = $derived(ctl.loaded && !fact.sending && fact.kind !== 'unknown');
  const skewed = $derived(live.snapshot !== null && Math.abs(live.clock - live.now) > SKEW_MS);
  const serviceTime = $derived(formatDateTime(live.clock, settings.language, live.now));
  const deviceTime = $derived(formatDateTime(live.now, settings.language, live.now));
</script>

{#if show || skewed}
  <div class="lines">
    {#if show}
      <div
        class="line tone-{fact.tone}"
        role="status"
        data-testid="control-line"
        data-control={fact.kind}
      >
        <Button
          variant="bare"
          class="ctl-open"
          title={t('controlMore')}
          onclick={() => (modeSheet.open = true)}
        >
          <Icon
            name={fact.kind === 'paused' ? 'pause' : fact.kind === 'watching' ? 'eye' : 'lock'}
            size={16}
          />
          <span class="sentence">{sentence}</span>
          <span class="lead">{t('controlNotSent')}</span>
          {#if fact.kind !== 'off'}
            <PumpPair
              wouldSend={fact.water.wouldSend}
              pumpHas={fact.water.pumpHas}
              testid="line-pair"
            />
          {/if}
          <Icon name="chevronRight" size={16} class="chev" />
        </Button>
        {#if fact.kind === 'watching'}
          <a
            class="compare"
            href="#/system/shadow"
            title={t('controlCompareTitle')}
            data-testid="control-compare"
          >
            <Icon name="chart" size={16} />
            <span>{t('controlCompare')}</span>
          </a>
        {/if}
      </div>
    {/if}
    {#if skewed}
      <div
        class="line clock"
        data-testid="service-clock"
        title={t('serviceClockTitle', { device: deviceTime })}
      >
        <Icon name="clock" size={16} />
        <span>{t('serviceClock', { time: serviceTime })}</span>
      </div>
    {/if}
  </div>
{/if}

<style>
  .lines {
    display: grid;
    gap: 1px;
    background: var(--border);
    border-bottom: 1px solid var(--border);
  }
  .line {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-4);
    font-size: var(--fs-body);
    background: var(--surface);
  }
  .tone-warn {
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .tone-info {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  .tone-neutral {
    background: var(--status-unknown-bg);
    color: var(--status-unknown);
  }
  .clock {
    background: var(--status-frozen-bg);
    color: var(--status-frozen);
    font-weight: var(--fw-semibold);
    min-height: 32px;
  }
  :global(.ctl-open) {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.15rem var(--space-3);
    flex: 1;
    min-width: 0;
    min-height: 32px;
    padding: 0;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  :global(.ctl-open):hover .lead {
    text-decoration: underline;
  }
  :global(.ctl-open) :global(.chev) {
    margin-left: auto;
    opacity: 0.8;
  }
  .compare {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    min-height: 32px;
    padding: 0 0.6rem;
    border: 1px solid currentColor;
    border-radius: var(--radius-pill);
    color: inherit;
    font-weight: var(--fw-semibold);
    text-decoration: none;
    white-space: nowrap;
  }
  .compare:hover {
    background: color-mix(in srgb, currentColor 10%, transparent);
  }
  .sentence {
    display: none;
    font-weight: var(--fw-semibold);
  }
  .lead {
    font-weight: var(--fw-semibold);
  }
  @media (--narrow) {
    .line {
      padding: 0 var(--space-3);
    }
    .compare {
      min-height: var(--tap);
      padding: 0 var(--space-2);
      font-size: var(--fs-caption);
    }
    :global(.ctl-open) {
      display: block;
      min-height: var(--tap);
      padding: 0.2rem 1.25rem 0.2rem 0;
      position: relative;
      font-size: var(--fs-caption);
      line-height: 1.3;
    }
    :global(.ctl-open) :global(.pair) {
      display: inline;
    }
    :global(.ctl-open) :global(.pair .half) {
      margin-right: var(--space-2);
    }
    :global(.ctl-open) > :global(.icon:first-child) {
      display: none;
    }
    :global(.ctl-open) :global(.chev) {
      position: absolute;
      right: 0;
      top: 50%;
      transform: translateY(-50%);
    }
    .sentence {
      display: inline;
      margin-right: var(--space-2);
    }
    .sentence::after {
      content: ' ·';
    }
    .lead {
      display: none;
    }
  }
</style>
