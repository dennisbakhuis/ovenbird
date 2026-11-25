<!--
  ActionRow: a wrapping row of buttons. `align="end"` pushes it to the right; `loose` uses the
  wider horizontal gap for rows that mix buttons and text.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';

  interface Props {
    align?: 'start' | 'end';
    center?: boolean;
    loose?: boolean;
    class?: string;
    testid?: string;
    children: Snippet;
  }

  let {
    align = 'start',
    center = false,
    loose = false,
    class: extra = '',
    testid,
    children,
  }: Props = $props();
</script>

<div class="actions {align} {extra}" class:center class:loose data-testid={testid}>
  {@render children()}
</div>

<style>
  @layer components {
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
    }
    .center {
      align-items: center;
    }
    .loose {
      gap: var(--space-2) var(--space-3);
    }
    .end {
      margin-left: auto;
    }
  }
</style>
