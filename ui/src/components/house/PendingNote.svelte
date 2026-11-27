<!--
  PendingNote: a short note that the house settings in the draft, or changed since the model was
  made, apply at the next learner run, with a Run now button that starts one through the
  learner's own endpoint. Shown only while there is something to wait for.

  Props: changedSince (a stored change is newer than the model), showRun (false where the run card
  itself is on the page), onstarted (called after a run was started).
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { t } from '$lib/core/settings.svelte';
  import { refusalOf, startRun } from '$lib/house/run';
  import { FIT_FIELDS } from '$lib/house/settings';

  interface Props {
    changedSince?: boolean;
    showRun?: boolean;
    onstarted?: () => void;
  }

  let { changedSince = false, showRun = true, onstarted }: Props = $props();

  const inDraft = $derived(Object.keys(draft.changes).some((id) => FIT_FIELDS.has(id)));
  let busy = $state(false);
  let started = $state(false);
  let error = $state<string | null>(null);

  async function run(): Promise<void> {
    busy = true;
    error = null;
    try {
      await startRun();
      started = true;
      onstarted?.();
    } catch (failure) {
      error = t(`houseRunRefused_${refusalOf(failure)}`);
    }
    busy = false;
  }
</script>

{#if inDraft || changedSince}
  <div class="pending" data-testid="house-pending" data-source={inDraft ? 'draft' : 'stored'}>
    <p>{inDraft ? t('houseNextRunDraft') : t('houseNextRunChanged')}</p>
    {#if showRun && !inDraft && !started}
      <Button size="sm" onclick={run} {busy} data-testid="house-pending-run">
        {t('houseNextRunNow')}
      </Button>
    {/if}
    {#if started}<p class="muted">{t('houseRunPill_running')}</p>{/if}
    {#if error}<InlineMessage tone="error" icon>{error}</InlineMessage>{/if}
  </div>
{/if}

<style>
  .pending {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin-top: var(--space-3);
  }
  p {
    margin: 0;
  }
</style>
