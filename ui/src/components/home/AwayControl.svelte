<!--
  AwayControl: "Away" on Home. Pick the room target while away and when you are back (a date and
  a time), then Set away. While it runs it shows the target, the end, when comfort starts again
  and "I’m back" to end it now. Hidden while away is switched off in the settings.

  Props: ctl (ControlStore), live (LiveStore, for the service clock).
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import DateInput from '$ui/DateInput.svelte';
  import Icon from '$ui/Icon.svelte';
  import Stepper from '$ui/Stepper.svelte';
  import TimeInput from '$ui/TimeInput.svelte';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import { awayProblem, awayUntil, defaultAwayEnd } from '$lib/home/manual';
  import { untrack } from 'svelte';

  let { ctl, live }: { ctl: ControlStore; live: LiveStore } = $props();

  const away = $derived(ctl.control?.away ?? null);
  const locale = $derived(settings.language);
  const initial = untrack(() => defaultAwayEnd(live.serviceNow()));
  let open = $state(false);
  let date = $state(initial.date);
  let time = $state(initial.time);
  let target = $state<number | null>(null);
  let busy = $state(false);
  let failure = $state<string | null>(null);

  const shown = $derived(open || away?.active === true || failure !== null);
  const chosenTarget = $derived(target ?? away?.default_target_c ?? 16);
  const untilIso = $derived(awayUntil(date, time));
  const leadS = $derived(away?.default_lead_s ?? 0);
  const problem = $derived(
    untilIso === null ? null : awayProblem(Date.parse(untilIso), live.clock, leadS),
  );
  const problemText = $derived(
    problem === 'too_soon'
      ? t('homeAwayTooSoon', { hours: formatNumber(leadS / 3600, 1, locale) })
      : problem === 'too_far'
        ? t('homeAwayTooFar')
        : null,
  );

  async function run(action: () => Promise<string | null>): Promise<void> {
    busy = true;
    failure = null;
    failure = await action();
    busy = false;
  }

  const set = () =>
    run(async () => {
      if (untilIso === null) return null;
      const error = await ctl.away({ until: untilIso, target_c: chosenTarget });
      return error === null ? null : t(actionKey(error));
    });

  const end = () =>
    run(async () => {
      const error = await ctl.endAway();
      return error === null ? null : t(actionKey(error));
    });
</script>

{#if away?.enabled}
  <div
    class="control"
    data-testid="home-away"
    data-active={away.active}
    data-phase={away.phase ?? undefined}
  >
    <Button
      class="toggle"
      aria-expanded={shown}
      aria-controls="home-away-panel"
      onclick={() => (open = !open)}
      data-testid="home-away-toggle"
    >
      <Icon name="home" size={18} />
      <span class="name">{t('homeAwayTitle')}</span>
      {#if away.active}
        <span class="badge">{formatDateTime(away.until, locale, live.clock)}</span>
      {/if}
      <Icon name={shown ? 'chevronDown' : 'chevronRight'} size={16} class="chev" />
    </Button>
    {#if shown}
      <div class="panel" id="home-away-panel">
        {#if away.active}
          <p class="line" data-testid="home-away-active">
            {away.phase === 'returning'
              ? t('homeAwayReturning')
              : t('homeAwayActive', { until: formatDateTime(away.until, locale, live.clock) })}
          </p>
          <p class="muted" data-testid="home-away-detail">
            {t('homeAwayTargetLine', { target: formatNumber(away.target_c ?? 0, 1, locale) })} ·
            {t('homeAwayComfortFrom', {
              time: formatDateTime(away.comfort_from, locale, live.clock),
            })}
          </p>
          {#if away.paused === 'stove' || away.paused === 'summer'}
            <p class="muted" data-testid="home-away-paused">
              <Icon name="pause" size={16} />{t(
                `homeAwayPaused_${away.paused}` as 'homeAwayPaused_stove',
              )}
            </p>
          {/if}
          <div class="actions">
            <Button disabled={busy} onclick={end} data-testid="home-away-end"
              >{t('homeAwayEnd')}</Button
            >
          </div>
        {:else}
          <div class="choice">
            <span class="label">{t('homeAwayTarget')}</span>
            <Stepper
              value={chosenTarget}
              step={0.5}
              min={10}
              max={20}
              unit="°C"
              label={t('homeAwayTarget')}
              onchange={(next) => (target = next)}
              testid="home-away-target"
            />
          </div>
          <div class="choice">
            <span class="label">{t('homeAwayDate')}</span>
            <span class="when">
              <DateInput
                value={date}
                onchange={(next) => (date = next)}
                invalid={problem !== null}
                aria-label={t('homeAwayDate')}
                data-testid="home-away-date"
              />
              <span class="muted">{t('homeAwayTime')}</span>
              <TimeInput
                value={time}
                onchange={(next) => (time = next)}
                invalid={problem !== null}
                aria-label={t('homeAwayTime')}
                data-testid="home-away-time"
              />
            </span>
          </div>
          {#if problemText}<p class="problem" data-testid="home-away-problem">{problemText}</p>{/if}
          <p class="muted note">{t('homeAwayNote')}</p>
          <div class="actions">
            <Button
              variant="primary"
              disabled={busy || untilIso === null || problem !== null}
              onclick={set}
              data-testid="home-away-set"
            >
              {t('homeAwaySet')}
            </Button>
          </div>
        {/if}
        {#if failure}<p class="error" role="alert" data-testid="home-away-error">{failure}</p>{/if}
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
    color: var(--muted);
  }
  p.muted {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }
  .note {
    font-size: var(--fs-caption);
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
  .when {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
  }
  .problem,
  .error {
    color: var(--err-text);
  }
</style>
