<!--
  DraftBar: the unsaved-changes bar of the Settings and House pages, fixed at the bottom of the window
  (above the phone navigation). Shows "1 change", the last validation result without flicker
  (the previous result stays while a new check runs), Discard and Review. Opens the review
  dialog and applies; "Version N saved / is now active" goes to the page banner.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import {
    applyConfig,
    ApiError,
    failureKind,
    isForbidden,
    isMissing,
    previewConfig,
    validateConfig,
  } from '$lib/core/api';
  import { cfg } from '$lib/core/cfg.svelte';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import { liveFact, notSendingNote } from '$lib/core/controlText';
  import { draft } from '$lib/core/draft.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { reviewRequest } from '$lib/core/reviewRequest.svelte';
  import { router } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { PreviewResult } from '$lib/core/types';
  import { dismiss, notify } from '$ui/Banner.svelte';
  import Icon from '$ui/Icon.svelte';
  import PreviewDialog from '$components/settings/PreviewDialog.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  let open = $state(false);
  let loading = $state(false);
  let result = $state<PreviewResult | null>(null);
  let previewError = $state<'missing' | 'forbidden' | 'failed' | null>(null);
  let applying = $state(false);
  let applyError = $state<string | null>(null);
  let appliedVersion = $state<number | null>(null);
  let announced = $state(false);
  let noticeId: number | null = null;
  let status = $state<'pending' | 'ok' | 'bad'>('pending');

  const onSettings = $derived(router.route === 'settings' || router.route === 'house');
  const stale = $derived(draft.isStale(ctl.config));
  const errorCount = $derived(cfg.validation?.errors.length ?? 0);
  const entries = $derived(draft.diff(ctl.config));
  const active = $derived(
    appliedVersion !== null &&
      ((ctl.decision?.config_version ?? 0) >= appliedVersion ||
        (live.configVersion ?? 0) >= appliedVersion),
  );

  $effect(() => {
    if (cfg.validating) return;
    status = cfg.validation === null ? 'pending' : errorCount > 0 ? 'bad' : 'ok';
  });

  const withNote = (text: string): string => {
    const note = notSendingNote(liveFact(ctl, live.snapshot), settings.language, live.clock);
    return note ? `${text} ${note}` : text;
  };

  $effect(() => {
    if (appliedVersion === null || !active || announced) return;
    announced = true;
    if (noticeId !== null) dismiss(noticeId);
    noticeId = notify(withNote(t('appliedActive', { version: appliedVersion })), {
      testid: 'apply-notice',
    });
  });

  $effect(() => {
    if (!reviewRequest.pending) return;
    reviewRequest.pending = false;
    void review();
  });

  async function review(): Promise<void> {
    open = true;
    loading = true;
    result = null;
    previewError = null;
    applyError = null;
    try {
      result = await previewConfig(draft.changes);
    } catch (error) {
      if (isMissing(error)) {
        previewError = 'missing';
        try {
          result = await validateConfig(draft.changes);
        } catch (checkError) {
          previewError = isForbidden(checkError) ? 'forbidden' : 'failed';
        }
      } else {
        previewError = isForbidden(error) ? 'forbidden' : 'failed';
      }
    }
    loading = false;
  }

  async function apply(comment: string, acknowledge: string[]): Promise<void> {
    const config = ctl.config;
    if (!config) return;
    applying = true;
    applyError = null;
    try {
      const done = await applyConfig({
        base_version: draft.base ?? config.version,
        changes: { ...draft.changes },
        comment,
        acknowledge,
      });
      ctl.config = done.config;
      draft.clear();
      open = false;
      announced = false;
      if (noticeId !== null) dismiss(noticeId);
      noticeId = notify(withNote(t('appliedPending', { version: done.version })), {
        testid: 'apply-notice',
      });
      appliedVersion = done.version;
      void ctl.refresh();
    } catch (error) {
      const kind = failureKind(error);
      if (kind === 'forbidden' || kind === 'unauthorized') ctl.admin = false;
      if (kind === 'conflict') {
        applyError = t('previewConflict');
        void ctl.refresh();
      } else if (error instanceof ApiError && error.status === 422) {
        const body = error.body as Partial<PreviewResult> | null;
        result = {
          valid: false,
          errors: body?.errors ?? [],
          warnings: body?.warnings ?? [],
          effective: {},
        };
        applyError = t('previewRefused');
      } else if (kind === 'rate_limited') {
        applyError = t('previewRateLimited');
      } else {
        applyError = t(actionKey(kind));
      }
    }
    applying = false;
  }

  function rebase(): void {
    if (ctl.config) draft.prune(ctl.config);
    void review();
  }
</script>

{#if draft.count > 0 && onSettings}
  <div
    class="bar"
    role="region"
    aria-label={t('draftBarLabel')}
    aria-busy={cfg.validating}
    data-testid="draft-bar"
  >
    <div class="inner">
      <div class="info">
        <span class="count" data-testid="draft-count">
          <span class="dot" aria-hidden="true"></span>
          {draft.count === 1 ? t('draftCountOne') : t('draftCount', { n: draft.count })}
        </span>
        <span class="status {status}" class:busy={cfg.validating} data-testid="draft-status">
          {#if status === 'bad'}
            <Icon name="critical" size={16} /><span data-testid="draft-errors"
              >{t('draftErrors', { n: errorCount })}</span
            >
          {:else if status === 'ok'}
            <Icon name="check" size={16} />{t('draftValid')}
          {:else}
            <Icon name="clock" size={16} />{t('draftValidating')}
          {/if}
        </span>
        {#if draft.origin}<span class="origin" data-testid="draft-origin"
            ><Icon name="home" size={16} />{draft.origin.kind === 'house'
              ? t('houseSuggestedLabel')
              : draft.origin.label}</span
          >{/if}
        {#if stale}<span class="stale" data-testid="draft-stale"
            ><Icon name="warning" size={16} />{t('draftStaleShort')}</span
          >{/if}
      </div>
      <div class="actions">
        <Button variant="ghost" onclick={() => draft.clear()} data-testid="draft-discard">
          {t('draftDiscard')}
        </Button>
        <Button type="button" variant="primary" onclick={review} data-testid="draft-review">
          <span class="long">{t('draftReview')}</span><span class="short" aria-hidden="true"
            >{t('draftReviewShort')}</span
          >
        </Button>
      </div>
    </div>
  </div>
{/if}

{#if open}
  <PreviewDialog
    diff={entries}
    schema={cfg.schema}
    {result}
    {loading}
    error={previewError}
    admin={ctl.admin}
    {applying}
    {applyError}
    {stale}
    defaultComment={draft.origin?.comment ?? ''}
    onapply={apply}
    onrebase={rebase}
    onclose={() => (open = false)}
  />
{/if}

<style>
  .bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: var(--z-bar);
    background: color-mix(in srgb, var(--accent) 10%, var(--surface));
    border-top: 2px solid var(--accent);
    box-shadow: var(--shadow-raised);
    padding-bottom: env(safe-area-inset-bottom);
  }
  .inner {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-4);
    max-width: var(--page-max);
    margin: 0 auto;
    padding: var(--space-2) var(--space-5);
  }
  .info {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    align-items: center;
    min-width: 0;
  }
  .count {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-weight: var(--fw-bold);
  }
  .dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--accent);
  }
  .origin {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.05rem var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--status-manual-bg);
    color: var(--status-manual);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
    transition: opacity 0.2s;
  }
  .status.busy {
    opacity: 0.6;
  }
  .status.ok {
    color: var(--status-ok);
  }
  .status.bad {
    color: var(--status-stopped);
  }
  .status.pending {
    color: var(--muted);
  }
  .stale {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.05rem var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--warn-bg);
    color: var(--warn-text);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
  }
  .actions {
    display: flex;
    gap: var(--space-2);
    margin-left: auto;
  }
  .actions :global(.btn) {
    min-height: var(--tap);
  }
  .short {
    display: none;
  }
  .status,
  .count {
    white-space: nowrap;
  }
  @media (--narrow) {
    .bar {
      bottom: calc(57px + env(safe-area-inset-bottom));
      padding-bottom: 0;
    }
    .inner {
      padding: var(--space-2) var(--space-3);
      flex-wrap: nowrap;
    }
    .info {
      flex-direction: column;
      align-items: flex-start;
      gap: 0;
    }
    .long {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }
    .short {
      display: inline;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .status {
      transition: none;
    }
  }
</style>
