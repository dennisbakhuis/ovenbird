<!--
  ArbiterList: what the decision asked of the pump and what was done: per intent kind the wanted
  and the reported value with the arbiter's action, then any commands sent for this tick.

  Props: decision (Decision).
  A11y: a list with every value and action as text; action icons are decorative.
-->
<script lang="ts">
  import type { IconName } from '$lib/core/icons';
  import { t, tc } from '$lib/core/settings.svelte';
  import type { Decision } from '$lib/core/types';
  import Icon from '$ui/Icon.svelte';

  let { decision }: { decision: Decision } = $props();

  const ACTION_ICON: Record<string, IconName> = {
    none: 'check',
    send: 'upload',
    skip: 'pause',
  };
</script>

{#if decision.arbiter.length === 0 && decision.commands.length === 0}
  <p class="muted empty">{t('arbiterEmpty')}</p>
{:else}
  <ul class="arbiter" data-testid="arbiter-list">
    {#each decision.arbiter as entry (entry.kind)}
      <li class={entry.action}>
        <Icon name={ACTION_ICON[entry.action] ?? 'info'} size={16} />
        <span class="kind">{tc('kind_', entry.kind)}</span>
        <span class="values"
          >{t('arbiterIntent', { intent: entry.intent ?? '–', actual: entry.actual ?? '–' })}</span
        >
        <span class="muted">{tc('arbiterAction_', entry.action)} · {entry.reason}</span>
      </li>
    {/each}
    {#each decision.commands as command, index (`${command.at}-${index}`)}
      <li class="command">
        <Icon name="upload" size={16} />
        <span class="kind">{tc('kind_', command.kind)}</span>
        <span class="values">{command.value ?? '–'}</span>
        <span class="muted">{tc('cmd_', command.status)} · {command.detail}</span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .arbiter {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.4rem;
  }
  li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.15rem var(--space-2);
    font-size: var(--fs-body);
  }
  li :global(svg) {
    color: var(--status-ok);
  }
  .send :global(svg),
  .command :global(svg) {
    color: var(--status-manual);
  }
  .skip :global(svg) {
    color: var(--status-limited);
  }
  .kind {
    font-weight: var(--fw-semibold);
  }
  .values {
    font-variant-numeric: tabular-nums;
  }
  .muted {
    font-size: var(--fs-caption);
  }
  .empty {
    margin: 0;
  }
</style>
