<script lang="ts">
  import Select from '$ui/Select.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import { ApiError, pumpRefusal } from '$lib/core/api';
  import { actorText } from '$lib/activity/audit';
  import { formatAge, formatDateTime, formatDuration } from '$lib/core/format';
  import { humanizeLabel } from '$lib/pump/pumpStats';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { PumpSetting } from '$lib/core/types';
  import CommandProgress from './CommandProgress.svelte';
  import Modal from '$ui/Modal.svelte';
  import Pill from '$ui/Pill.svelte';
  import Why from '$ui/Why.svelte';

  interface Props {
    setting: PumpSetting;
    writable: boolean;
    refusal?: string | null;
    admin: boolean | null;
    onwrite: (id: string, value: number, expect: number | null) => Promise<void>;
  }

  let { setting, writable, refusal = null, admin, onwrite }: Props = $props();

  const locale = $derived(settings.language);
  const label = $derived(tOpt(`pumpSetting_${setting.id}`) ?? humanizeLabel(setting.id));
  const effect = $derived(tOpt(`pumpEffect_${setting.id}`));
  const owner = $derived(tOpt(`pumpOwner_${setting.owner}`) ?? setting.owner);
  const current = $derived(typeof setting.value === 'number' ? setting.value : null);
  const isMode = $derived(setting.id === 'pump_flowrate_mode');
  const canEdit = $derived(setting.access === 'write' && setting.supported);
  const FINISHED = ['verified', 'failed', 'refused', 'dropped'];

  let open = $state(false);
  let draftText = $state('');
  let typed = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let submitted = $state<number | null>(null);

  const parsed = $derived(draftText.trim() === '' ? NaN : Number(draftText));
  const rangeError = $derived(
    Number.isNaN(parsed)
      ? null
      : !Number.isInteger(parsed)
        ? t('pumpNotInteger')
        : parsed < (setting.min ?? -Infinity) || parsed > (setting.max ?? Infinity)
          ? t('pumpOutOfRange', { min: setting.min ?? '', max: setting.max ?? '' })
          : null,
  );
  const valid = $derived(Number.isInteger(parsed) && rangeError === null && parsed !== current);
  const confirmed = $derived(valid && typed.trim() === String(parsed));
  const tracked = $derived(submitted !== null);
  const status = $derived<string | null>(
    submitted !== null && setting.last_write?.to === submitted
      ? (setting.last_write.status ?? null)
      : submitted !== null
        ? 'queued'
        : null,
  );
  const finished = $derived(tracked && (status === null || FINISHED.includes(status)));
  const lastStatus = $derived(
    setting.last_write?.status
      ? (tOpt(`cmd_${setting.last_write.status}`) ?? setting.last_write.status)
      : t('pumpStatusUnknown'),
  );

  function modeText(value: number): string {
    return t(value === 1 ? 'pumpFlowMode1' : 'pumpFlowMode0');
  }

  /**
   * A setting value for people: the translated catalogue label for enums (no raw number), the
   * number with its unit otherwise.
   */
  function show(
    value: number | string | boolean | null | undefined,
    labelId = setting.label,
  ): string {
    if (value === null || value === undefined) return '–';
    if (labelId && value === setting.value)
      return tOpt(`pumpLabel_${labelId}`) ?? humanizeLabel(labelId);
    if (isMode && typeof value === 'number') return modeText(value);
    const text =
      typeof value === 'number' ? new Intl.NumberFormat(locale).format(value) : String(value);
    return `${text}${setting.unit ? ` ${setting.unit}` : ''}`;
  }

  function startEdit(): void {
    draftText = current === null ? '' : String(current);
    typed = '';
    error = null;
    open = true;
  }

  function refusalText(caught: ApiError): string {
    const refused = pumpRefusal(caught);
    const known = refused ? tOpt(`pumpRefusal_${refused.code}`) : undefined;
    if (known) {
      const wait = refused?.params?.['retry_after'];
      return typeof wait === 'number'
        ? `${known} ${t('pumpRetryAfter', { wait: formatDuration(wait) })}`
        : known;
    }
    if (caught.status === 409) return t('pumpErr409');
    if (caught.status === 422) return t('pumpErr422');
    if (caught.status === 429) return t('pumpErr429');
    if (caught.status === 401) return t('actionUnauthorized');
    if (caught.status === 403) return t('actionForbidden');
    if (caught.status === 413) return t('actionTooLarge');
    if (caught.status === 415) return t('actionUnsupported');
    return t('actionFailed');
  }

  async function confirm(): Promise<void> {
    if (!confirmed) return;
    busy = true;
    error = null;
    try {
      await onwrite(setting.id, parsed, current);
      submitted = parsed;
      open = false;
    } catch (caught) {
      error = caught instanceof ApiError ? refusalText(caught) : t('actionFailed');
    }
    busy = false;
  }
</script>

<div class="row" class:read={!canEdit} data-testid="pump-row-{setting.id}">
  <div class="name">
    <strong>{label}</strong>
    <Why title={label} testid="pump-why-{setting.id}">
      {#if effect}<p>{effect}</p>{/if}
      <p class="muted">{t('pumpSignal')}: <code>{setting.signal}</code></p>
    </Why>
    {#if !canEdit}<Pill tone={setting.owner === 'controller' ? 'manual' : 'unknown'}>{owner}</Pill
      >{/if}
  </div>
  <div class="value">
    <span class="current" data-testid="pump-value-{setting.id}">{show(setting.value)}</span>
    {#if setting.age !== null && setting.age !== undefined}
      <span class="muted age" class:stale={!setting.fresh}
        >{setting.fresh ? t('pumpAge', { age: formatAge(setting.age) }) : t('pumpStale')}</span
      >
    {/if}
  </div>
  {#if canEdit}
    <div class="actions">
      <Button
        onclick={startEdit}
        disabled={!writable || admin === false || busy}
        title={refusal ?? undefined}
        data-testid="pump-edit-{setting.id}"
      >
        {t('pumpEdit')}
      </Button>
    </div>
  {/if}
  {#if canEdit && admin === false}
    <p class="note muted" data-testid="pump-not-admin">{t('pumpNotAdmin')}</p>
  {:else if canEdit && !writable && refusal}
    <p class="note muted">{t('pumpRefused', { reason: refusal })}</p>
  {/if}
  {#if tracked}
    <div class="status" data-testid="pump-status-{setting.id}">
      <CommandProgress {status} />
      {#if finished}
        <Button variant="link" class="pump-link" onclick={() => (submitted = null)}
          >{t('pumpDismiss')}</Button
        >
      {/if}
    </div>
  {:else if canEdit && setting.last_write}
    <p class="note muted" data-testid="pump-last-{setting.id}">
      {t('pumpLastWrite', {
        from: setting.last_write.from ?? '–',
        to: setting.last_write.to ?? '–',
        at: formatDateTime(setting.last_write.at, locale),
        by: actorText(setting.last_write.by),
        status: lastStatus,
      })}
    </p>
  {/if}
</div>

{#if open}
  <Modal
    title={t('pumpDialogTitle', { name: label })}
    onclose={() => (open = false)}
    testid="pump-dialog"
  >
    <p>
      <strong>{t('pumpCurrentToNew')}</strong>
    </p>
    <p class="change" data-testid="pump-change">
      {show(setting.value)} →
      <strong>{Number.isNaN(parsed) ? '…' : show(parsed, null)}</strong>
    </p>
    <label class="field">
      <span>{t('pumpNewValue')}</span>
      {#if isMode}
        <Select
          block={false}
          value={draftText}
          onchange={(e) => (draftText = e.currentTarget.value)}
          data-testid="pump-input"
        >
          <option value="0">{t('pumpFlowMode0')}</option>
          <option value="1">{t('pumpFlowMode1')}</option>
        </Select>
      {:else}
        <TextInput
          block={false}
          type="number"
          inputmode="numeric"
          step="1"
          min={setting.min}
          max={setting.max}
          value={draftText}
          oninput={(e) => (draftText = e.currentTarget.value)}
          data-testid="pump-input"
        />
      {/if}
    </label>
    <p class="muted">{t('pumpRange', { min: setting.min ?? '', max: setting.max ?? '' })}</p>
    {#if rangeError}<p class="err" role="alert">{rangeError}</p>{/if}
    <p>{tOpt(`pumpEffect_${setting.id}`) ?? ''}</p>
    <label class="field">
      <span>{t('pumpTypeToConfirm', { value: Number.isNaN(parsed) ? '…' : parsed })}</span>
      <TextInput
        block={false}
        type="text"
        inputmode="numeric"
        autocomplete="off"
        bind:value={typed}
        data-testid="pump-confirm-input"
      />
    </label>
    {#if error}<p class="err" role="alert" data-testid="pump-error">{error}</p>{/if}
    {#snippet footer()}
      <Button onclick={() => (open = false)}>{t('cancel')}</Button>
      <Button
        type="button"
        variant="primary"
        disabled={!confirmed || busy}
        onclick={confirm}
        data-testid="pump-confirm"
      >
        {t('pumpWrite')}
      </Button>
    {/snippet}
  </Modal>
{/if}

<style>
  .row {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 1.5fr) auto;
    gap: var(--space-1) var(--space-4);
    align-items: center;
    padding: 0.6rem 0;
    border-bottom: 1px solid var(--border);
  }
  .row.read {
    grid-template-columns: minmax(0, 2fr) minmax(0, 1.5fr);
    padding: 0.4rem 0;
  }
  .row:last-child {
    border-bottom: 0;
  }
  .name {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) 0.4rem;
    min-width: 0;
  }
  .row:not(.read) .name {
    flex-wrap: nowrap;
  }
  .row:not(.read) .name strong {
    min-width: 0;
  }
  .value {
    display: flex;
    flex-direction: column;
    font-variant-numeric: tabular-nums;
  }
  .current {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
  }
  .age {
    font-size: var(--fs-caption);
  }
  .age.stale {
    color: var(--status-limited);
  }
  .note,
  .status {
    grid-column: 1 / -1;
    margin: 0;
    font-size: var(--fs-body);
  }
  .status {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
  }
  :global(.pump-link) {
    text-decoration: underline;
    min-height: var(--tap);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin: var(--space-3) 0;
  }
  .change {
    font-size: var(--fs-value);
    margin: var(--space-1) 0;
  }
  .err {
    color: var(--err-text);
    background: var(--err-bg);
    padding: 0.4rem 0.6rem;
    border-radius: var(--radius-sm);
  }
  @media (--narrow) {
    .row {
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .row:not(.read) .value {
      grid-column: 1;
      grid-row: 2;
    }
    .row .actions {
      grid-column: 2;
      grid-row: 1 / span 2;
    }
  }
</style>
