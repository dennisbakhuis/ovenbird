<script lang="ts" module>
  import { STORAGE_PREFIX } from '$lib/core/brand';
  const PREFIX = `${STORAGE_PREFIX}details.`;

  /**
   * Remembered open state of a Details block on this device, or null when never toggled.
   */
  export function rememberedOpen(id: string): boolean | null {
    try {
      const value = localStorage.getItem(PREFIX + id);
      return value === null ? null : value === '1';
    } catch {
      return null;
    }
  }

  function remember(id: string, open: boolean): void {
    try {
      localStorage.setItem(PREFIX + id, open ? '1' : '0');
    } catch {
      return;
    }
  }
</script>

<script lang="ts">
  import { untrack, type Snippet } from 'svelte';
  import type { IconName } from '$lib/core/icons';
  import Icon from './Icon.svelte';

  interface Props {
    summary: string;
    id?: string;
    open?: boolean;
    icon?: IconName;
    meta?: string | number;
    testid?: string;
    children: Snippet;
  }

  let {
    summary,
    id,
    open = $bindable(false),
    icon,
    meta,
    testid = 'details',
    children,
  }: Props = $props();

  untrack(() => {
    if (id) open = rememberedOpen(id) ?? open;
  });

  function ontoggle(event: Event): void {
    open = (event.currentTarget as HTMLDetailsElement).open;
    if (id) remember(id, open);
  }
</script>

<details class="details" {open} {ontoggle} data-testid={testid}>
  <summary>
    <Icon name="chevronRight" size={18} class="chevron" />
    {#if icon}<Icon name={icon} size={18} />{/if}
    <span class="label">{summary}</span>
    {#if meta !== undefined && meta !== ''}<span class="meta">{meta}</span>{/if}
  </summary>
  {#if open}
    <div class="body">{@render children()}</div>
  {/if}
</details>

<style>
  .details {
    min-width: 0;
  }
  summary {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-height: var(--control-h);
    padding: var(--space-1) 0;
    cursor: pointer;
    list-style: none;
    font-weight: var(--fw-semibold);
    color: var(--text);
    border-radius: var(--radius-sm);
  }
  summary::-webkit-details-marker {
    display: none;
  }
  summary :global(.chevron) {
    color: var(--muted);
    transition: transform var(--dur-fast) ease;
  }
  details[open] > summary :global(.chevron) {
    transform: rotate(90deg);
  }
  summary:hover .label {
    color: var(--accent);
  }
  .meta {
    color: var(--muted);
    font-weight: var(--fw-regular);
    font-size: var(--fs-caption);
    padding: 0.05rem 0.45rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
  }
  .body {
    padding: var(--space-1) 0 var(--space-2) 1.6rem;
    min-width: 0;
  }
  @media (--narrow), (pointer: coarse) {
    summary {
      min-height: var(--tap);
      margin-block: -2px;
    }
  }
</style>
