<!--
  HoldCard: the current command hold with a countdown to its end and the release flow.

  Props: adapter, admin, onrelease(reason) -> failure kind or null, startedAt (when the hold
  began, for the countdown bar), compact (one line with a small release button; for Home),
  windowH (escalation window in hours, for "2 holds in the last 12 h"), detail (the hold's alarm
  `detail`: when it carries forensics, the card says which setting changed, what ovenbird set,
  what the pump reports since when, what it keeps and what happens when the hold ends).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import { onMount } from 'svelte';
  import { clockNow, formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import { holdEnd, holdForensics, settingUnit } from '$lib/activity/holdDetail';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import type { AdapterStatus } from '$lib/core/types';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';

  interface Props {
    adapter: AdapterStatus | null;
    admin: boolean | null;
    onrelease: (reason: string) => Promise<string | null>;
    startedAt?: string | null;
    compact?: boolean;
    windowH?: number;
    detail?: Record<string, unknown> | null;
  }

  let {
    adapter,
    admin,
    onrelease,
    startedAt = null,
    compact = false,
    windowH = 12,
    detail = null,
  }: Props = $props();

  let confirming = $state(false);
  let reason = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let now = $state(clockNow());

  onMount(() => {
    const timer = window.setInterval(() => (now = clockNow()), 15_000);
    return () => window.clearInterval(timer);
  });

  const hold = $derived(adapter?.hold ?? null);
  const holdKind = $derived(hold === null ? null : adapter?.hold_latched ? 'latched' : 'timed');
  const endMs = $derived(adapter?.hold_until ? Date.parse(adapter.hold_until) : null);
  const remainingS = $derived(endMs === null ? null : Math.max(0, (endMs - now) / 1000));
  const progress = $derived.by(() => {
    if (endMs === null || startedAt === null) return null;
    const start = Date.parse(startedAt);
    if (!Number.isFinite(start) || endMs <= start) return null;
    return Math.min(1, Math.max(0, (now - start) / (endMs - start)));
  });

  const forensics = $derived(hold === null ? null : holdForensics(detail));
  const unit = $derived(settingUnit(forensics?.setting ?? null));
  const value = (v: number | null) =>
    v === null ? t('holdValueUnknown') : `${formatNumber(v, 1, settings.language)}${unit}`;
  const endKind = $derived(forensics ? holdEnd(forensics, adapter?.hold_latched ?? false) : null);
  const endAt = $derived(adapter?.hold_until ?? forensics?.holdUntil ?? null);

  async function release(): Promise<void> {
    busy = true;
    error = null;
    const failure = await onrelease(reason.trim());
    busy = false;
    if (failure === null) {
      confirming = false;
      reason = '';
    } else {
      error = failure;
    }
  }
</script>

<section class="hold" class:compact data-testid="hold-card" aria-label={t('holdTitle')}>
  {#if adapter === null}
    <p class="muted">{t('holdNoAdapter')}</p>
  {:else if hold === null}
    <p class="muted none" data-testid="no-hold">
      <Icon name="check" size={16} />
      {t('holdNone')}
    </p>
  {:else}
    <div class="head">
      <Pill tone="warn" icon="pause">{t('holdActive')}</Pill>
      <strong>{tc('holdReason_', hold)}</strong>
      {#if compact && remainingS !== null}
        <span class="caption">{t('holdRemaining', { time: formatDuration(remainingS) })}</span>
      {/if}
    </div>
    {#if !compact}
      <p class="when">
        {#if holdKind === 'latched'}
          <Icon name="lock" size={16} />
          {t('holdLatched')}
        {:else if adapter.hold_until}
          {t('holdUntil', { when: formatDateTime(adapter.hold_until, settings.language) })}
          {#if remainingS !== null}
            <strong>{t('holdRemaining', { time: formatDuration(remainingS) })}</strong>
          {/if}
        {/if}
      </p>
      {#if progress !== null}
        <div
          class="bar"
          role="progressbar"
          aria-label={t('holdCountdown')}
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow={Math.round(progress * 100)}
        >
          <span style:width="{progress * 100}%"></span>
        </div>
      {/if}
      {#if forensics}
        <dl class="forensics" data-testid="hold-forensics">
          <dt>{t('holdSetting')}</dt>
          <dd>
            {forensics.setting
              ? (tOpt(`kind_${forensics.setting}`) ?? forensics.setting)
              : t('holdValueUnknown')}
            {#if forensics.register}<code class="raw-id">{forensics.register}</code>{/if}
          </dd>
          <dt>{t('holdOvenbirdSet')}</dt>
          <dd data-testid="hold-ovenbird">{value(forensics.ovenbirdValue)}</dd>
          <dt>{t('holdPumpReports')}</dt>
          <dd data-testid="hold-seen">
            {forensics.seenSince
              ? t('holdSeenSince', {
                  value: value(forensics.seenValue),
                  when: formatDateTime(forensics.seenSince, settings.language),
                })
              : value(forensics.seenValue)}
          </dd>
          <dt>{t('holdPumpKeeps')}</dt>
          <dd data-testid="hold-keeps">
            {forensics.pumpKeeps !== null
              ? value(forensics.pumpKeeps)
              : forensics.correction !== null
                ? t('holdCorrection', { value: value(forensics.correction) })
                : t('holdValueUnknown')}
          </dd>
          {#if endKind}
            <dt>{t('holdAtEnd')}</dt>
            <dd data-testid="hold-end">
              {endKind === 'await_release'
                ? t('holdEndAwait')
                : endAt
                  ? t('holdEndWriteAt', {
                      when: formatDateTime(endAt, settings.language),
                      value: value(forensics.controllerWants ?? forensics.ovenbirdValue),
                    })
                  : t('holdEndWrite', {
                      value: value(forensics.controllerWants ?? forensics.ovenbirdValue),
                    })}
            </dd>
          {/if}
        </dl>
      {/if}
      <p class="muted">
        {t(adapter.hold_incidents === 1 ? 'holdIncidentsOne' : 'holdIncidents', {
          n: adapter.hold_incidents,
          hours: Math.round(windowH),
        })}
      </p>
      {#if adapter.safety_hold.length > 0}
        <p class="muted">
          {t('holdSafety', { codes: adapter.safety_hold.map((c) => tc('alarm_', c)).join(', ') })}
        </p>
      {/if}
    {/if}

    {#if admin === false}
      <p class="muted" data-testid="hold-not-admin">{t('holdAdminOnly')}</p>
      <Button disabled>{t('holdRelease')}</Button>
    {:else if !confirming}
      <ActionRow>
        <Button onclick={() => (confirming = true)}>{t('holdRelease')}</Button>
      </ActionRow>
    {:else}
      <form
        onsubmit={(event) => {
          event.preventDefault();
          void release();
        }}
      >
        <label>
          <span>{t('holdReasonLabel')}</span>
          <TextInput
            type="text"
            maxlength={200}
            bind:value={reason}
            placeholder={t('holdReasonPlaceholder')}
          />
        </label>
        <ActionRow>
          <Button type="submit" variant="primary" disabled={busy}>{t('holdConfirm')}</Button>
          <Button onclick={() => (confirming = false)} disabled={busy}>{t('cancel')}</Button>
        </ActionRow>
      </form>
    {/if}
    {#if error !== null}
      <InlineMessage tone="error" size="md" class="hold-error">
        {t(
          error === 'forbidden'
            ? 'holdErrForbidden'
            : error === 'conflict'
              ? 'holdErrConflict'
              : 'holdErrFailed',
        )}
      </InlineMessage>
    {/if}
  {/if}
</section>

<style>
  .hold {
    display: grid;
    gap: var(--space-2);
  }
  .hold p {
    margin: 0;
  }
  .none {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--status-ok);
  }
  .head {
    display: flex;
    gap: var(--space-2) var(--space-3);
    align-items: center;
    flex-wrap: wrap;
  }
  .when {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }
  .forensics {
    display: grid;
    grid-template-columns: minmax(8rem, max-content) minmax(0, 1fr);
    gap: var(--space-1) var(--space-3);
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
    background: var(--surface-2);
  }
  .forensics dt {
    color: var(--muted);
  }
  .forensics dd {
    margin: 0;
    min-width: 0;
    font-variant-numeric: tabular-nums;
  }
  .raw-id {
    margin-left: var(--space-2);
    color: var(--muted);
    font-size: var(--fs-caption);
    overflow-wrap: anywhere;
  }
  @container main (max-width: 30rem) {
    .forensics {
      grid-template-columns: minmax(0, 1fr);
      gap: 0;
    }
    .forensics dd {
      margin-bottom: var(--space-2);
    }
  }
  .bar {
    height: 0.5rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    border: 1px solid var(--border);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--status-limited);
  }
  form {
    display: grid;
    gap: var(--space-3);
    margin-top: var(--space-1);
  }
  label {
    display: grid;
    gap: var(--space-1);
    font-size: var(--fs-body);
  }
  .compact .head {
    flex-wrap: nowrap;
  }
  :global(.hold-error) {
    margin: 1em 0;
  }
</style>
