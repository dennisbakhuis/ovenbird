<!--
  HealthGrid: the health checks as a compact grid of status tiles (icon, name, state word).
  Colour is never the only signal: every state has its own icon and word.

  Props: checks (name -> state), notes (optional caption per check name).
-->
<script lang="ts">
  import type { IconName } from '$lib/core/icons';
  import { tc } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  let { checks, notes = {} }: { checks: Record<string, string>; notes?: Record<string, string> } =
    $props();

  const GOOD = new Set(['connected', 'alive', 'ok']);
  const NEUTRAL = new Set(['disabled']);
  const WARN = new Set(['info', 'warning', 'starting', 'stale']);

  type Tone = 'good' | 'neutral' | 'warn' | 'bad';

  function tone(state: string): Tone {
    if (GOOD.has(state)) return 'good';
    if (NEUTRAL.has(state)) return 'neutral';
    return WARN.has(state) ? 'warn' : 'bad';
  }

  const ICON: Record<Tone, IconName> = {
    good: 'check',
    neutral: 'minus',
    warn: 'warning',
    bad: 'critical',
  };
</script>

<ul class="checks" data-testid="health-grid">
  {#each Object.entries(checks) as [name, state] (name)}
    {@const level = tone(state)}
    <li class="tile {level}" data-check={name} data-state={state}>
      <Icon name={ICON[level]} size={18} />
      <span class="text">
        <span class="name">{tc('check_', name)}</span>
        <span class="state">{tc('state_', state)}</span>
        {#if notes[name]}<span class="note">{notes[name]}</span>{/if}
      </span>
    </li>
  {/each}
</ul>

<style>
  .checks {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(10.5rem, 1fr));
    gap: var(--space-2);
  }
  .tile {
    display: flex;
    gap: var(--space-2);
    align-items: flex-start;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius);
    border: 1px solid var(--border);
    border-left-width: 3px;
    background: var(--surface-2);
  }
  .text {
    display: grid;
    min-width: 0;
  }
  .name {
    font-weight: var(--fw-semibold);
    font-size: var(--fs-body);
  }
  .state,
  .note {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .good {
    border-left-color: var(--status-ok);
  }
  .good :global(.icon) {
    color: var(--status-ok);
  }
  .warn {
    border-left-color: var(--status-limited);
  }
  .warn :global(.icon) {
    color: var(--status-limited);
  }
  .bad {
    border-left-color: var(--status-stopped);
    background: var(--status-stopped-bg);
  }
  .bad :global(.icon) {
    color: var(--status-stopped);
  }
  .neutral :global(.icon) {
    color: var(--muted);
  }
</style>
