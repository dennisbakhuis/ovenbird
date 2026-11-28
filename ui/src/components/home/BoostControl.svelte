<!--
  BoostControl: "Warmer for a while" on Home. Pick how much the room target changes (−1, +0.5, +1,
  +1.5 K) and for how long (1, 2, 4 h), then Start; while a boost runs it shows the target, the
  time left and Stop. Hidden while boost is switched off in the settings. A refusal because away
  is set is explained in words.

  Props: ctl (ControlStore), live (LiveStore, for the service clock).
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import Icon from '$ui/Icon.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import { formatDateTime, formatDuration } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    BOOST_HOURS,
    BOOST_OFFSETS,
    nearestHours,
    nearestOffset,
    secondsLeft,
    signedOffset,
  } from '$lib/home/manual';

  let { ctl, live }: { ctl: ControlStore; live: LiveStore } = $props();

  const boost = $derived(ctl.control?.boost ?? null);
  const away = $derived(ctl.control?.away.active === true);
  const locale = $derived(settings.language);
  let open = $state(false);
  let offset = $state<number | null>(null);
  let hours = $state<number | null>(null);
  let busy = $state(false);
  let failure = $state<string | null>(null);
  const chosenOffset = $derived(offset ?? nearestOffset(boost?.default_k));
  const chosenHours = $derived(hours ?? nearestHours(boost?.default_s));
  const shown = $derived(open || boost?.active === true || failure !== null);
  const left = $derived(secondsLeft(boost?.request?.until, live.clock));

  async function run(action: () => Promise<string | null>): Promise<void> {
    busy = true;
    failure = null;
    failure = await action();
    busy = false;
  }

  const start = () =>
    run(async () => {
      const error = await ctl.boost({ offset_k: chosenOffset, duration_s: chosenHours * 3600 });
      if (error === null) return null;
      if (error === 'conflict') {
        await ctl.refresh();
        return ctl.control?.away.active ? t('homeBoostAway') : t(actionKey(error));
      }
      return t(actionKey(error));
    });

  const stop = () =>
    run(async () => {
      const error = await ctl.endBoost();
      return error === null ? null : t(actionKey(error));
    });
</script>

{#if boost?.enabled}
  <div class="control" data-testid="home-boost" data-active={boost.active}>
    <Button
      class="toggle"
      aria-expanded={shown}
      aria-controls="home-boost-panel"
      onclick={() => (open = !open)}
      data-testid="home-boost-toggle"
    >
      <Icon name="thermometer" size={18} />
      <span class="name">{t('homeBoostTitle')}</span>
      {#if boost.active && boost.request}
        <span class="badge"
          >{signedOffset(boost.shift_k ?? boost.request.offset_k ?? 0, locale)} K</span
        >
      {/if}
      <Icon name={shown ? 'chevronDown' : 'chevronRight'} size={16} class="chev" />
    </Button>
    {#if shown}
      <div class="panel" id="home-boost-panel">
        {#if boost.active && boost.request}
          <p class="line" data-testid="home-boost-active">
            {t('homeBoostActive', {
              offset: signedOffset(boost.shift_k ?? boost.request.offset_k ?? 0, locale),
              until: formatDateTime(boost.request.until, locale, live.clock),
            })}
          </p>
          <p class="muted" data-testid="home-boost-left">
            {t('homeBoostLeft', { left: formatDuration(left, locale) })}
          </p>
          {#if boost.paused === 'stove' || boost.paused === 'summer'}
            <p class="muted" data-testid="home-boost-paused">
              <Icon name="pause" size={16} />{t(
                `homeBoostPaused_${boost.paused}` as 'homeBoostPaused_stove',
              )}
            </p>
          {/if}
          <div class="actions">
            <Button disabled={busy} onclick={stop} data-testid="home-boost-stop">
              {t('homeBoostStop')}
            </Button>
          </div>
        {:else}
          <div class="choice">
            <span class="label">{t('homeBoostHow')}</span>
            <Segmented
              label={t('homeBoostHow')}
              options={BOOST_OFFSETS.map((k) => ({
                value: k,
                label: `${signedOffset(k, locale)} K`,
                testid: `home-boost-offset-${k}`,
              }))}
              value={chosenOffset}
              onchange={(next) => (offset = next)}
              appearance="joined"
              size="sm"
              disabled={away}
            />
          </div>
          <div class="choice">
            <span class="label">{t('homeBoostFor')}</span>
            <Segmented
              label={t('homeBoostFor')}
              options={BOOST_HOURS.map((h) => ({
                value: h,
                label: t('homeBoostHours', { n: h }),
                testid: `home-boost-hours-${h}`,
              }))}
              value={chosenHours}
              onchange={(next) => (hours = next)}
              appearance="joined"
              size="sm"
              disabled={away}
            />
          </div>
          {#if away}
            <p class="muted" data-testid="home-boost-away">{t('homeBoostAway')}</p>
          {/if}
          <div class="actions">
            <Button
              variant="primary"
              disabled={busy || away}
              onclick={start}
              data-testid="home-boost-start"
            >
              {t('homeBoostStart')}
            </Button>
          </div>
        {/if}
        {#if failure}<p class="error" role="alert" data-testid="home-boost-error">{failure}</p>{/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .control {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  .control :global(.toggle) {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    justify-content: flex-start;
    width: 100%;
    min-height: 3.4rem;
    padding-inline: var(--space-3);
  }
  .control :global(.toggle .chev) {
    margin-left: auto;
    color: var(--muted);
  }
  .name {
    font-weight: var(--fw-semibold);
    text-align: left;
  }
  .badge {
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--status-manual-bg);
    color: var(--status-manual);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
    white-space: nowrap;
  }
  .panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
  }
  p {
    margin: 0;
  }
  .line {
    font-weight: var(--fw-semibold);
  }
  .muted {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }
  .choice {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-3);
  }
  .label {
    min-width: 8.5rem;
    color: var(--muted);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
  }
  .error {
    color: var(--err-text);
  }
</style>
