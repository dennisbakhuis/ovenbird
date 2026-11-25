<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import {
    actionKey,
    classifyError,
    type ActionError,
    type ControlStore,
  } from '$lib/core/control.svelte';
  import { firstWriteText, liveFact, refusalFor, sentenceFor } from '$lib/core/controlText';
  import { formatClock } from '$lib/core/format';
  import type { IconName } from '$lib/core/icons';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { modeView, type ModeKey } from '$lib/core/mode';
  import { modeSheet } from '$lib/core/modeSheet.svelte';
  import { hasNotifyAlarm } from '$lib/notify/notify';
  import { notifyHealth } from '$lib/notify/notifyHealth.svelte';
  import { router } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { MessageKey } from '$lib/i18n';
  import Art from '$components/art/Art.svelte';
  import Icon from '$ui/Icon.svelte';
  import PumpPair from './PumpPair.svelte';
  import StoveBanner from '$components/stove/StoveBanner.svelte';
  import StoveStart from '$components/stove/StoveStart.svelte';
  import Why from '$ui/Why.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const MODE_ICON: Record<ModeKey, IconName> = {
    auto: 'play',
    shadow: 'eye',
    paused: 'pause',
    off: 'power',
    manual: 'hand',
    unknown: 'why',
  };
  const TONE_CLASS = { good: 'ok', info: 'manual', warn: 'limited', neutral: 'unknown' } as const;

  const view = $derived(modeView(ctl.control, ctl.decision, ctl.config));
  const fact = $derived(liveFact(ctl, live.snapshot));
  const sentence = $derived(sentenceFor(fact, settings.language, live.clock));
  const onHome = $derived(router.route === 'home');
  const holdText = $derived(
    onHome ? sentenceFor(fact, settings.language, live.clock, true, true) : sentence,
  );
  const alarms = $derived(ctl.control?.alarms ?? []);
  const topAlarm = $derived(
    alarms.find((a) => a.severity === 'critical') ??
      alarms.find((a) => a.severity === 'warning') ??
      alarms[0],
  );
  const alarmTone = $derived(
    topAlarm?.severity === 'critical'
      ? 'stopped'
      : topAlarm?.severity === 'warning'
        ? 'limited'
        : topAlarm
          ? 'manual'
          : 'ok',
  );
  const alarmIcon = $derived<IconName>(
    topAlarm?.severity === 'critical'
      ? 'critical'
      : topAlarm?.severity === 'warning'
        ? 'warning'
        : topAlarm
          ? 'info'
          : 'check',
  );
  const alarmText = $derived(
    alarms.length === 0
      ? t('stripNoAlarms')
      : alarms.length === 1
        ? t('stripAlarmOne')
        : t('stripAlarms', { n: alarms.length }),
  );
  const version = $derived(
    ctl.config?.applied_version ?? ctl.control?.config_version ?? live.configVersion,
  );
  const holdShort = $derived(
    fact.holdLatched || fact.holdUntil === null
      ? t('stripHoldLatchedShort')
      : t('stripHoldUntil', { time: formatClock(fact.holdUntil, settings.language) }),
  );
  const showPair = $derived(!fact.sending && fact.kind !== 'unknown' && fact.kind !== 'off');
  const resumeText = $derived(firstWriteText(ctl.decision, settings.language));
  const notifyFailing = $derived(notifyHealth.failing && !hasNotifyAlarm(alarms));
  const draftText = $derived(
    draft.count === 1 ? t('stripDraftOne') : t('stripDraftMany', { n: draft.count }),
  );

  let confirming = $state(false);
  let busy = $state(false);
  let failure = $state<ActionError | null>(null);

  async function run(action: () => Promise<ActionError | null>): Promise<void> {
    busy = true;
    failure = null;
    try {
      failure = await action();
    } catch (error) {
      failure = classifyError(error);
    }
    busy = false;
    confirming = false;
  }
</script>

<section
  class="strip"
  aria-label={t('statusLabel')}
  data-testid="status-strip"
  data-control={fact.kind}
>
  <Why
    title={t('modeSheetTitle')}
    ariaLabel={`${t('modeSheetTitle')}: ${t(`mode_${view.key}` as MessageKey)}. ${sentence}`}
    bind:open={modeSheet.open}
    triggerClass="mode-chip {TONE_CLASS[fact.tone]}"
    testid="mode-sheet"
    width="24rem"
    triggerAttrs={{ 'data-testid': 'mode-chip', 'data-mode': view.key, 'data-control': fact.kind }}
  >
    {#snippet trigger()}
      <Icon name={MODE_ICON[view.key]} size={16} />
      <span class="mode-short">{t(`modeShort_${view.key}` as MessageKey)}</span>
      {#if t(`mode_${view.key}` as MessageKey) !== t(`modeShort_${view.key}` as MessageKey)}
        <span class="visually-hidden">{t(`mode_${view.key}` as MessageKey)}</span>
      {/if}
      <Icon name="chevronDown" size={14} class="caret" />
    {/snippet}
    <p class="sheet-mode {TONE_CLASS[fact.tone]}">
      <Icon name={MODE_ICON[view.key]} size={18} />
      <strong>{t(`mode_${view.key}` as MessageKey)}</strong>
    </p>
    {#if view.key === 'shadow' || view.key === 'paused'}
      <div class="sheet-art"><Art name="shadow" width="8rem" /></div>
    {/if}
    <p class="sheet-control" data-testid="sheet-control">{sentence}.</p>
    {#if showPair}
      <p class="sheet-pair">
        <PumpPair
          wouldSend={fact.water.wouldSend}
          pumpHas={fact.water.pumpHas}
          testid="sheet-pair"
        />
      </p>
    {/if}
    <p>{t(`modeExplain_${view.key}` as MessageKey)}</p>
    {#if ctl.control?.stove?.enabled}
      <div class="sheet-stove">
        <StoveBanner {ctl} {live} compact testid="sheet-stove" />
        {#if !ctl.control.stove.active}<p class="caption">{t('stoveSheetOff')}</p>{/if}
        <StoveStart {ctl} {live} testid="sheet-stove-start" />
      </div>
    {/if}
    {#if fact.kind === 'refused' && fact.refusals.length > 1}
      <ul class="refusals" data-testid="sheet-refusals">
        {#each fact.refusals as reason (reason)}<li>
            {refusalFor(reason, settings.language)}
          </li>{/each}
      </ul>
    {/if}
    <div class="sheet-actions">
      {#if view.canPause}
        <Button onclick={() => run(() => ctl.pause())} disabled={busy} data-testid="pause">
          <Icon name="pause" size={16} />{t('pause')}
        </Button>
      {:else if view.canResume}
        {#if confirming}
          <span class="confirm">
            <span>{t('resumeConfirm')}</span>
            <span data-testid="resume-first">{resumeText}</span>
            {#if ctl.control?.adapter?.hold}<span>{t('resumeStillHeld')}</span>{/if}
            <span class="row">
              <Button
                type="button"
                variant="primary"
                onclick={() => run(() => ctl.resume())}
                disabled={busy}
                data-testid="resume-confirm"
              >
                {t('resume')}
              </Button>
              <Button onclick={() => (confirming = false)}>{t('cancel')}</Button>
            </span>
          </span>
        {:else}
          <Button onclick={() => (confirming = true)} disabled={busy} data-testid="resume">
            <Icon name="play" size={16} />{t('resume')}
          </Button>
        {/if}
      {/if}
    </div>
    {#if failure !== null}
      <p class="failure" role="alert">{t(actionKey(failure))}</p>
    {/if}
    <ul class="sheet-links">
      {#if version !== null && version !== undefined}
        <li>
          <a
            href="#/settings/versions"
            onclick={() => (modeSheet.open = false)}
            data-testid="config-version"
          >
            {t('modeConfigLink', { version })}<Icon name="chevronRight" size={14} />
          </a>
        </li>
      {/if}
      <li>
        <a href="#/system" onclick={() => (modeSheet.open = false)}>
          {t('modeSystemLink')}<Icon name="chevronRight" size={14} />
        </a>
      </li>
    </ul>
  </Why>

  <ul class="items">
    {#if fact.kind === 'held'}
      <li class="shrink">
        <a class="item limited" href="#/activity/holds" title={sentence} data-testid="strip-hold">
          <Icon name="lock" size={16} />
          <span class="long">{holdText}</span>
          <span class="short" aria-hidden="true">{holdShort}</span>
          <span class="visually-hidden short-label">{sentence}</span>
        </a>
      </li>
    {:else}
      <li class="desk shrink">
        <span class="sentence" title={sentence} data-testid="strip-sentence">{sentence}</span>
      </li>
    {/if}
    <li>
      <a
        class="item {alarmTone}"
        class:quiet={alarms.length === 0}
        href="#/activity"
        title={alarmText}
        data-testid="alarm-count"
      >
        <Icon name={alarmIcon} size={16} />
        <span class="long">{alarmText}</span>
        <span class="short" aria-hidden="true">{alarms.length || ''}</span>
        <span class="visually-hidden short-label">{alarmText}</span>
      </a>
    </li>
    {#if notifyFailing}
      <li>
        <a
          class="item stopped"
          href="#/system"
          title={t('stripNotifyFailing')}
          data-testid="strip-notify"
        >
          <Icon name="bell" size={16} />
          <span class="long">{t('stripNotifyFailing')}</span>
          <span class="short" aria-hidden="true">!</span>
          <span class="visually-hidden short-label">{t('stripNotifyFailing')}</span>
        </a>
      </li>
    {/if}
    {#if draft.count > 0}
      <li>
        <a class="item manual" href="#/settings" title={draftText} data-testid="strip-draft">
          <Icon name="edit" size={16} />
          <span class="long">{draftText}</span>
          <span class="short" aria-hidden="true">{draft.count}</span>
          <span class="visually-hidden short-label">{draftText}</span>
        </a>
      </li>
    {/if}
  </ul>
</section>

<style>
  .strip {
    display: flex;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    min-width: 0;
    flex-wrap: nowrap;
  }
  .strip :global(.mode-chip) {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    min-height: 32px;
    padding: 0.2rem 0.55rem 0.2rem 0.65rem;
    border-radius: var(--radius-pill);
    font-weight: var(--fw-semibold);
    font-size: var(--fs-body);
    flex: none;
    max-width: 50%;
  }
  .strip :global(.mode-chip .caret) {
    opacity: 0.7;
  }
  .strip :global(.mode-chip.ok),
  .sheet-mode.ok {
    background: var(--status-ok-bg);
    color: var(--status-ok);
  }
  .strip :global(.mode-chip.manual),
  .sheet-mode.manual {
    background: var(--status-manual-bg);
    color: var(--status-manual);
  }
  .strip :global(.mode-chip.limited),
  .sheet-mode.limited {
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .strip :global(.mode-chip.unknown),
  .sheet-mode.unknown {
    background: var(--status-unknown-bg);
    color: var(--status-unknown);
  }
  .strip :global(.mode-chip:hover) {
    color: inherit;
    filter: brightness(0.97);
  }
  .mode-short {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .items {
    display: flex;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    list-style: none;
    margin: -3px;
    padding: 3px;
    min-width: 0;
    flex-wrap: nowrap;
    overflow: hidden;
  }
  .items li {
    display: flex;
    min-width: 0;
    flex-shrink: 0;
  }
  .items li.shrink {
    flex-shrink: 1;
  }
  .sentence {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text);
    font-size: var(--fs-body);
  }
  .sheet-stove {
    display: grid;
    gap: var(--space-2);
    margin: var(--space-2) 0;
  }
  .sheet-stove .caption {
    margin: 0;
  }
  .sheet-control {
    font-weight: var(--fw-semibold);
  }
  .sheet-pair {
    padding: 0.4rem var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
  }
  .refusals {
    margin: 0;
    padding-left: 1.2rem;
    color: var(--status-limited);
  }
  .item {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    min-height: 32px;
    padding: 0.15rem 0.6rem;
    border-radius: var(--radius-pill);
    font-size: var(--fs-body);
    font-weight: var(--fw-semibold);
    text-decoration: none;
    white-space: nowrap;
    min-width: 0;
  }
  .item .long {
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .item:hover .long {
    text-decoration: underline;
  }
  .item.ok {
    color: var(--status-ok);
    background: var(--status-ok-bg);
  }
  .item.quiet {
    background: transparent;
    color: var(--muted);
    font-weight: var(--fw-medium);
  }
  .item.limited {
    color: var(--status-limited);
    background: var(--status-limited-bg);
  }
  .item.stopped {
    color: var(--status-stopped);
    background: var(--status-stopped-bg);
  }
  .item.manual {
    color: var(--status-manual);
    background: var(--status-manual-bg);
  }
  .short,
  .short-label {
    display: none;
  }
  .sheet-mode {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
  }
  .sheet-actions {
    margin-top: var(--space-3);
  }
  .sheet-actions :global(.btn) {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
  }
  .confirm {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .row {
    display: flex;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .failure {
    padding: 0.4rem var(--space-3);
    border-radius: var(--radius-control);
    background: var(--err-bg);
    color: var(--err-text);
  }
  .sheet-links {
    list-style: none;
    margin: var(--space-3) 0 0;
    padding: var(--space-2) 0 0;
    border-top: 1px solid var(--border);
  }
  .sheet-links a {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: var(--tap);
    text-decoration: none;
  }
  @media (--narrow) {
    .strip {
      gap: var(--space-2);
    }
    .items {
      gap: var(--space-1);
    }
    .desk {
      display: none !important;
    }
    .item .long {
      display: none;
    }
    .short {
      display: inline;
    }
    .short-label {
      display: block;
    }
    .item {
      min-height: var(--tap);
      min-width: var(--tap);
      justify-content: center;
      padding: 0 0.55rem;
    }
    .strip :global(.mode-chip) {
      min-height: var(--tap);
      max-width: 11rem;
    }
  }
</style>
