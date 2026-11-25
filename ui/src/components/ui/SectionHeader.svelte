<!--
  SectionHeader: a heading with an optional subtitle and a right-hand actions slot, for sections
  inside a card or page that are not a Card of their own.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    title: string;
    subtitle?: string;
    level?: 2 | 3;
    testid?: string;
    actions?: Snippet;
  }

  let { title, subtitle, level = 3, testid, actions }: Props = $props();
</script>

<header class="section-header" data-testid={testid}>
  <div class="text">
    <svelte:element this={level === 2 ? 'h2' : 'h3'} class="title">{title}</svelte:element>
    {#if subtitle}<p class="subtitle">{subtitle}</p>{/if}
  </div>
  {#if actions}<div class="actions">{@render actions()}</div>{/if}
</header>

<style>
  @layer components {
    .section-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-1) var(--space-3);
    }
    .text {
      flex: 1 1 12rem;
      min-width: 0;
    }
    .title {
      margin: 0;
    }
    .subtitle {
      margin: var(--space-1) 0 0;
      color: var(--muted);
      font-size: var(--fs-caption);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-2);
    }
  }
</style>
