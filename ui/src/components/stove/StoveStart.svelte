<!--
  StoveStart: "Stove on…" starts wood-stove mode by hand. The button unfolds the duration choices
  (2, 4, 8 h) in place; picking one sends `POST control/stove` with `until` on the service clock.
  Renders nothing while wood-stove mode is not enabled or an episode already runs.

  Props: ctl (ControlStore), live (LiveStore, for the service clock), testid (prefix, default
  "stove-start"), compact (smaller button for a card footer).
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { actionKey, type ControlStore } from '$lib/core/control.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { t } from '$lib/core/settings.svelte';
  import { canStartStove, STOVE_HOURS } from '$lib/stove/stove';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    ctl: ControlStore;
    live: LiveStore;
    testid?: string;
    compact?: boolean;
  }

  let { ctl, live, testid = 'stove-start', compact = false }: Props = $props();

  const show = $derived(canStartStove(ctl.control?.stove));
  let open = $state(false);
  let busy = $state(false);
  let failure = $state<string | null>(null);
  const groupId = $derived(`${testid}-choices`);

  async function start(hours: number): Promise<void> {
    busy = true;
    failure = null;
    const error = await ctl.stove(hours, live.serviceNow());
    busy = false;
    if (error === null) open = false;
    else failure = error === 'conflict' ? t('stoveNotEnabled') : t(actionKey(error));
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      open = false;
    }
  }
</script>

{#if show}
  <div class="stove-start" class:compact role="presentation" {onkeydown}>
    <Button
      class="stove-trigger"
      aria-expanded={open}
      aria-controls={groupId}
      onclick={() => (open = !open)}
      data-testid={testid}
    >
      <Icon name="flame" size={16} />{t('stoveOn')}
    </Button>
    {#if open}
      <div class="choices" id={groupId} role="group" aria-label={t('stoveOnFor')}>
        <span class="muted">{t('stoveOnFor')}</span>
        {#each STOVE_HOURS as hours (hours)}
          <Button
            disabled={busy}
            aria-label={t('stoveHoursLabel', { n: hours })}
            onclick={() => start(hours)}
            data-testid="{testid}-{hours}"
          >
            {t('stoveHours', { n: hours })}
          </Button>
        {/each}
      </div>
    {/if}
    {#if failure}<p class="error" role="alert">{failure}</p>{/if}
  </div>
{/if}

<style>
  .stove-start {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  :global(.stove-trigger) {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .compact :global(.stove-trigger) {
    min-height: 36px;
    padding: 0.2rem 0.7rem;
  }
  .choices {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .choices :global(.btn) {
    min-width: 3.4rem;
  }
  .error {
    flex-basis: 100%;
    margin: 0;
    color: var(--err-text);
  }
  @media (--narrow), (pointer: coarse) {
    .compact :global(.stove-trigger) {
      min-height: var(--tap);
    }
  }
</style>
