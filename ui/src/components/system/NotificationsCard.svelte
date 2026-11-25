<!--
  NotificationsCard: whether alerts reach anyone when no page is open. ntfy (configured, server,
  minimum severity, last sent, last error, last test) and the external dead-man ping (configured,
  last success, healthy or why not), one verdict line on top, and "Send test" (operate role).
  Both channels are set in the environment or the add-on options, never in Settings.

  Props: status (NotificationStatus; null when the service does not offer it, undefined while
  loading), failed (the last load failed), ontest() -> null or the failure (kind, seconds to wait
  after a 429).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import type { NotificationStatus } from '$lib/system/about';
  import type { FailureKind } from '$lib/core/api';
  import type { TestFailure } from '$lib/notify/notify';
  import { formatDateTime } from '$lib/core/format';
  import { notifyVerdict } from '$lib/notify/notify';
  import { settings, t } from '$lib/core/settings.svelte';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';

  interface Props {
    status: NotificationStatus | null | undefined;
    failed?: boolean;
    ontest: () => Promise<TestFailure | null>;
  }

  let { status, failed = false, ontest }: Props = $props();

  let busy = $state(false);
  let outcome = $state<'sent' | 'failed' | FailureKind | null>(null);
  let retryS = $state<number | null>(null);

  const when = (iso: string | null | undefined) =>
    iso ? formatDateTime(iso, settings.language) : '–';
  const errorText = (
    value: { at: string; error: string } | string | null | undefined,
  ): string | null =>
    value === null || value === undefined ? null : typeof value === 'string' ? value : value.error;

  const verdict = $derived(notifyVerdict(status));

  async function test(): Promise<void> {
    busy = true;
    outcome = null;
    const failure = await ontest();
    busy = false;
    if (failure !== null) {
      outcome = failure.kind;
      retryS = failure.retryS;
      return;
    }
    outcome = status?.ntfy.last_test?.ok === false ? 'failed' : 'sent';
  }

  const outcomeText = $derived.by(() => {
    switch (outcome) {
      case null:
        return null;
      case 'sent':
        return t('notifyTestSent');
      case 'failed':
        return t('notifyTestFailed', {
          error: status?.ntfy.last_test?.error ?? '–',
        });
      case 'conflict':
        return t('notifyTestNotConfigured');
      case 'forbidden':
      case 'unauthorized':
        return t('notifyTestForbidden');
      case 'missing':
        return t('notifyMissing');
      case 'rate_limited':
        return retryS === null ? t('notifyTestRateNoTime') : t('notifyTestRate', { s: retryS });
      default:
        return t('actionFailed');
    }
  });
</script>

<Card title={t('notifyTitle')} icon="bell" testid="notify-card" help="system.notifications">
  {#if status === undefined}
    <p class="muted">{failed ? t('systemLoadFailed') : t('loading')}</p>
  {:else if status === null}
    <p class="muted" data-testid="notify-missing">{t('notifyMissing')}</p>
  {:else}
    {#if verdict}
      <p class="verdict" data-testid="notify-verdict" data-tone={verdict.tone}>
        <Pill tone={verdict.tone} icon={verdict.tone === 'good' ? 'check' : 'warning'}>
          {t(
            verdict.tone === 'good'
              ? 'notifyOk'
              : verdict.tone === 'warn'
                ? 'notifyWarn'
                : 'notifyBad',
          )}
        </Pill>
        <span>{t(verdict.key)}</span>
      </p>
    {/if}
    <dl class="facts">
      <dt>{t('notifyNtfy')}</dt>
      <dd data-testid="notify-ntfy">
        {#if status.ntfy.configured}
          {t('notifyConfiguredAt', { server: status.ntfy.server ?? '–' })}
          <span class="muted">
            · {t('notifyMinSeverity', {
              severity: t(`severity_${status.ntfy.min_severity}` as 'severity_warning'),
            })}</span
          >
        {:else}
          {t('notifyNotConfigured')}
        {/if}
      </dd>
      {#if status.ntfy.configured}
        <dt>{t('notifyLastSent')}</dt>
        <dd>
          {#if status.ntfy.last_sent}
            {when(status.ntfy.last_sent.at)}
            <span class="muted">· {status.ntfy.last_sent.title}</span>
          {:else}
            {t('notifyNever')}
          {/if}
        </dd>
        <dt>{t('notifyLastTest')}</dt>
        <dd data-testid="notify-last-test">
          {#if status.ntfy.last_test}
            {when(status.ntfy.last_test.at)} ·
            {status.ntfy.last_test.ok ? t('notifyTestOk') : t('notifyTestBad')}
            {#if status.ntfy.last_test.error}<span class="muted">
                · {status.ntfy.last_test.error}</span
              >{/if}
          {:else}
            {t('notifyNever')}
          {/if}
        </dd>
        {#if errorText(status.ntfy.last_error)}
          <dt>{t('notifyLastError')}</dt>
          <dd class="err-text" data-testid="notify-last-error">
            {#if typeof status.ntfy.last_error === 'object' && status.ntfy.last_error}{when(
                status.ntfy.last_error.at,
              )} ·
            {/if}{errorText(status.ntfy.last_error)}
          </dd>
        {/if}
        {#if status.health?.state === 'failing' && status.health.reason}
          <dt>{t('notifyDelivery')}</dt>
          <dd class="err-text" data-testid="notify-delivery">
            {status.health.reason}{#if status.health.pending?.length}
              <span class="block muted"
                >{t('notifyPending', { n: status.health.pending.length })}</span
              >{/if}
          </dd>
        {/if}
      {/if}
      <dt>{t('notifyDeadman')}</dt>
      <dd data-testid="notify-deadman">
        {#if status.deadman.configured}
          {status.deadman.healthy ? t('notifyDeadmanOk') : t('notifyDeadmanBad')}
          <span class="muted">
            · {t('notifyDeadmanAt', {
              server: status.deadman.server ?? '–',
              last: when(status.deadman.last_ok),
            })}</span
          >
          {#if !status.deadman.healthy && status.deadman.unhealthy_reason}
            <span class="block err-text">{status.deadman.unhealthy_reason}</span>
          {/if}
        {:else}
          {t('notifyDeadmanOff')}
        {/if}
      </dd>
    </dl>
    <ActionRow center loose class="notify-actions">
      <Button onclick={test} disabled={busy || !status.ntfy.configured} data-testid="notify-test">
        <Icon name="bell" size={16} />{t('notifySendTest')}
      </Button>
      {#if outcomeText}
        <p
          class="outcome"
          class:bad={outcome !== 'sent'}
          role="status"
          data-testid="notify-test-outcome"
        >
          {outcomeText}
        </p>
      {/if}
    </ActionRow>
    <p class="caption muted">{t('notifyWhere')}</p>
  {/if}
</Card>

<style>
  p {
    margin: 0;
  }
  .verdict {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-3);
    font-weight: var(--fw-semibold);
  }
  .facts {
    display: grid;
    grid-template-columns: minmax(7rem, max-content) minmax(0, 1fr);
    gap: var(--space-1) var(--space-3);
    margin: 0 0 var(--space-3);
  }
  dt {
    color: var(--muted);
  }
  dd {
    margin: 0;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .block {
    display: block;
  }
  .err-text {
    color: var(--err-text);
  }
  :global(.notify-actions) {
    margin-bottom: var(--space-2);
  }
  .outcome {
    font-weight: var(--fw-semibold);
    color: var(--status-ok);
  }
  .outcome.bad {
    color: var(--err-text);
  }
  @container main (max-width: 30rem) {
    .facts {
      grid-template-columns: minmax(0, 1fr);
      gap: 0 var(--space-3);
    }
    dd {
      margin-bottom: var(--space-2);
    }
  }
</style>
