<!--
  ModeCard: the control mode as a three-step ladder (Off, Shadow, Auto) with the configured
  ceiling marked by a lock, Pause/Resume, and the explanation behind a Why popover.

  Props: ctl (ControlStore), live (LiveStore, optional: the service clock and the pump's target).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Card from '$ui/Card.svelte';
  import Button from '$ui/Button.svelte';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import { firstWriteText, liveFact, refusalFor, sentenceFor } from '$lib/core/controlText';
  import { clockNow, formatDateTime } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { modeView } from '$lib/core/mode';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { Mode } from '$lib/core/types';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import Why from '$ui/Why.svelte';

  let { ctl, live = null }: { ctl: ControlStore; live?: LiveStore | null } = $props();

  const STEPS: Mode[] = ['off', 'shadow', 'auto'];

  const view = $derived(modeView(ctl.control, ctl.decision, ctl.config));
  const fact = $derived(liveFact(ctl, live?.snapshot ?? null));
  const sentence = $derived(sentenceFor(fact, settings.language, live?.clock ?? clockNow()));
  const refusals = $derived(
    (ctl.control?.refusals ?? []).map((reason) => refusalFor(reason, settings.language)),
  );
  const config = $derived(ctl.config);
  const ceiling = $derived(config?.mode.configured ?? null);
  const current = $derived<Mode | null>(
    view.key === 'paused'
      ? 'shadow'
      : view.key === 'unknown' || view.key === 'manual'
        ? null
        : view.key,
  );

  let confirmingResume = $state(false);
  let busy = $state(false);
  let failure = $state<string | null>(null);

  async function act(action: 'pause' | 'resume'): Promise<void> {
    busy = true;
    failure = null;
    const error = await (action === 'pause' ? ctl.pause() : ctl.resume());
    busy = false;
    confirmingResume = false;
    if (error !== null) failure = t(actionKey(error));
  }
</script>

<Card bare class="mode-card-mode" data-testid="mode-card" data-mode={view.key}>
  <header>
    <h2>{t('modeCardTitle')}</h2>
    <Why title={t('modeCardTitle')} testid="mode-why">
      <p>{t('modeHelp')}</p>
    </Why>
  </header>

  <p class="current tone-{fact.tone}" data-testid="mode-current">
    <strong>{t(`mode_${view.key}` as 'mode_auto')}</strong>
  </p>
  <p class="control" data-testid="mode-control" data-control={fact.kind}>{sentence}.</p>

  <ol class="ladder" aria-label={t('modeLadder')}>
    {#each STEPS as step (step)}
      <li aria-current={current === step ? 'step' : undefined} class:on={current === step}>
        <span class="dot"></span>
        <span class="name">{t(`modeName_${step}` as 'modeName_auto')}</span>
        {#if ceiling === step}
          <Icon name="lock" size={14} label={t('modeCeiling')} />
        {/if}
      </li>
    {/each}
  </ol>

  <ActionRow center>
    {#if view.canPause}
      <Button data-testid="mode-pause" disabled={busy} onclick={() => act('pause')}>
        <Icon name="pause" size={16} />
        {t('modePause')}
      </Button>
    {:else if view.canResume}
      {#if confirmingResume}
        <span class="first" data-testid="mode-resume-first"
          >{firstWriteText(ctl.decision, settings.language)}</span
        >
        <Button
          type="button"
          variant="primary"
          data-testid="mode-resume-confirm"
          disabled={busy}
          onclick={() => act('resume')}
        >
          {t('modeResumeConfirm')}
        </Button>
        <Button onclick={() => (confirmingResume = false)}>{t('cancel')}</Button>
      {:else}
        <Button data-testid="mode-resume" onclick={() => (confirmingResume = true)}>
          <Icon name="play" size={16} />
          {t('modeResume')}
        </Button>
      {/if}
    {/if}
    {#if refusals.length > 0}
      <span class="caption">{t('modeRefusals', { list: refusals.join('; ') })}</span>
    {/if}
  </ActionRow>
  {#if failure}<InlineMessage tone="error" size="md">{failure}</InlineMessage>{/if}
  {#if config?.reset_pending || ctl.control?.reset_pending}
    <p class="muted" data-testid="mode-reset-pending">{t('resetPending')}</p>
  {/if}

  <Details summary={t('modeDetails')} id="system-mode-details">
    <dl class="facts">
      {#if config}
        <div>
          <dt>{t('modeConfigured')}</dt>
          <dd>{t(`modeName_${config.mode.configured}` as 'modeName_auto')}</dd>
        </div>
        <div>
          <dt>{t('modeEffective')}</dt>
          <dd>{t(`modeName_${config.mode.effective}` as 'modeName_auto')}</dd>
        </div>
        <div>
          <dt>{t('modeConfigVersion')}</dt>
          <dd>v{config.applied_version}</dd>
        </div>
        {#if config.updated_at}
          <div>
            <dt>{t('modeConfigUpdated')}</dt>
            <dd>{formatDateTime(config.updated_at, settings.language)}</dd>
          </div>
        {/if}
      {/if}
      {#if ctl.control}
        <div>
          <dt>{t('modePublishing')}</dt>
          <dd>{ctl.control.publishing ? t('yes') : t('no')}</dd>
        </div>
        <div>
          <dt>{t('modeTicks')}</dt>
          <dd>{ctl.control.ticks}</dd>
        </div>
      {/if}
    </dl>
  </Details>
</Card>

<style>
  :global(.mode-card-mode) {
    display: grid;
    gap: var(--space-3);
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  h2 {
    margin: 0;
    font-size: var(--fs-emph);
  }
  .current {
    margin: 0;
    font-size: var(--fs-value);
  }
  .control {
    margin: 0;
    font-weight: var(--fw-semibold);
  }
  .first {
    flex-basis: 100%;
  }
  .tone-good {
    color: var(--status-ok);
  }
  .tone-warn {
    color: var(--status-limited);
  }
  .tone-info {
    color: var(--status-manual);
  }
  .ladder {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .ladder li {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-2);
    color: var(--muted);
    background: var(--surface-2);
    border-left: 1px solid var(--border);
  }
  .ladder li:first-child {
    border-left: none;
  }
  .ladder li.on {
    background: var(--status-manual-bg);
    color: var(--text);
    font-weight: var(--fw-bold);
  }
  .dot {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    border: 2px solid currentColor;
  }
  .on .dot {
    background: currentColor;
  }
  .facts {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
    gap: var(--space-3) var(--space-5);
    margin: 0;
  }
  .facts dt {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .facts dd {
    margin: 0;
    font-weight: var(--fw-semibold);
  }
</style>
