<script lang="ts">
  import Checkbox from '$ui/Checkbox.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import { ApiError, failureKind, fetchVersion, rollbackConfig } from '$lib/core/api';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import { issueText } from '$lib/settings/issues';
  import { rollbackDiff } from '$lib/core/rollback';
  import { t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema, ValidationIssue } from '$lib/core/types';
  import DiffTable from './DiffTable.svelte';
  import Modal from '$ui/Modal.svelte';

  interface Props {
    version: number;
    ctl: ControlStore;
    schema: ConfigSchema;
    config: ConfigDoc;
    ondone: (version: number) => void;
    onclose: () => void;
  }

  let { version, ctl, schema, config, ondone, onclose }: Props = $props();

  let entries = $state<ReturnType<typeof rollbackDiff> | null>(null);
  let loadError = $state<string | null>(null);
  let comment = $state('');
  let acknowledged = $state<string[]>([]);
  let errors = $state<ValidationIssue[]>([]);
  let warnings = $state<ValidationIssue[]>([]);
  let failure = $state<string | null>(null);
  let busy = $state(false);

  $effect(() => {
    void (async () => {
      try {
        const full = await fetchVersion(version);
        entries = rollbackDiff(full.values ?? {}, config, schema);
      } catch (error) {
        loadError = t(actionKey(failureKind(error)));
      }
    })();
  });

  const describe = (issue: ValidationIssue) =>
    issueText(issue, issue.field ? schema.fields[issue.field] : undefined, tOpt);
  const fieldName = (field: string | null) =>
    field === null ? null : (tOpt(`cfg.${field}.label`) ?? field);
  const warningCodes = $derived([...new Set(warnings.map((w) => w.code))]);
  const pending = $derived(warningCodes.filter((code) => !acknowledged.includes(code)));
  const canApply = $derived(
    !busy &&
      entries !== null &&
      entries.length > 0 &&
      errors.length === 0 &&
      pending.length === 0 &&
      ctl.admin !== false,
  );

  function toggle(code: string, on: boolean): void {
    acknowledged = on ? [...acknowledged, code] : acknowledged.filter((c) => c !== code);
  }

  async function run(): Promise<void> {
    busy = true;
    failure = null;
    try {
      const done = await rollbackConfig({
        version,
        base_version: config.version,
        comment: comment.trim(),
        acknowledge: acknowledged,
      });
      ctl.config = done.config;
      ctl.admin = true;
      void ctl.refresh();
      ondone(done.version);
    } catch (error) {
      const kind = failureKind(error);
      if (kind === 'forbidden' || kind === 'unauthorized') ctl.admin = false;
      if (error instanceof ApiError && error.status === 422) {
        const body = error.body as { errors?: ValidationIssue[]; warnings?: ValidationIssue[] };
        errors = body?.errors ?? [];
        warnings = body?.warnings ?? [];
        failure = t('previewRefused');
      } else if (kind === 'conflict') {
        failure = t('previewConflict');
        void ctl.refresh();
      } else if (kind === 'rate_limited') {
        failure = t('previewRateLimited');
      } else {
        failure = t(actionKey(kind));
      }
    }
    busy = false;
  }
</script>

<Modal title={t('rollbackTitle', { version })} {onclose} testid="rollback-dialog">
  {#if loadError}
    <p class="notice error" role="alert">{loadError}</p>
  {:else if entries === null}
    <p class="muted" role="status">{t('loading')}</p>
  {:else if entries.length === 0}
    <p class="notice" data-testid="rollback-same">{t('rollbackSame', { version })}</p>
  {:else}
    <p>{t('rollbackIntro', { version })}</p>
    <DiffTable {entries} {schema} />
  {/if}

  {#if errors.length > 0}
    <section class="problems" data-testid="rollback-errors">
      <ul>
        {#each errors as issue, i (i)}
          <li class="error">
            {#if fieldName(issue.field)}<strong>{fieldName(issue.field)}</strong>:
            {/if}{describe(issue)}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if warnings.length > 0}
    <section class="problems" data-testid="rollback-warnings">
      <ul>
        {#each warnings as issue, i (i)}
          <li class="warn">
            {#if fieldName(issue.field)}<strong>{fieldName(issue.field)}</strong>:
            {/if}{describe(issue)}
          </li>
        {/each}
      </ul>
      {#each warningCodes as code (code)}
        <Checkbox
          class="rollback-ack"
          checked={acknowledged.includes(code)}
          onchange={(e) => toggle(code, e.currentTarget.checked)}
          data-testid="rollback-ack-{code}"
          >{t('previewAcknowledge', {
            warning: describe(warnings.find((w) => w.code === code)!),
          })}</Checkbox
        >
      {/each}
    </section>
  {/if}

  <label class="comment">
    <span>{t('previewComment')}</span>
    <TextInput type="text" maxlength={200} bind:value={comment} data-testid="rollback-comment" />
  </label>

  {#if failure}<p class="notice error" role="alert">{failure}</p>{/if}

  {#snippet footer()}
    {#if ctl.admin === false}
      <span class="muted why">{t('previewNotAdmin')}</span>
    {/if}
    <Button onclick={onclose}>{t('cancel')}</Button>
    <Button
      type="button"
      variant="primary"
      disabled={!canApply}
      onclick={run}
      data-testid="rollback-confirm"
    >
      {busy ? t('previewApplying') : t('rollbackConfirm')}
    </Button>
  {/snippet}
</Modal>

<style>
  .problems ul {
    margin: var(--space-2) 0;
    padding-left: 1.2rem;
  }
  .error {
    color: var(--err-text);
  }
  .warn {
    color: var(--warn-text);
  }
  .notice {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-control);
    background: var(--warn-bg);
    color: var(--warn-text);
  }
  .notice.error {
    background: var(--err-bg);
    color: var(--err-text);
  }
  :global(.rollback-ack) {
    display: flex;
    gap: 0.6rem;
    align-items: center;
    min-height: 44px;
  }
  .comment {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    margin-top: var(--space-4);
  }
  .why {
    flex: 1;
    align-self: center;
    font-size: var(--fs-md);
  }
</style>
