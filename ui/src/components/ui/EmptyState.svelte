<!--
  EmptyState: a drawing beside a short message for a list or chart with nothing to show. The
  drawing loads on demand (components/art) and is decorative; the text carries the meaning.

  Props: art (ArtName), title, text, size ('normal' | 'small'), testid; children for extra
  content under the text, action for a button or link.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { ArtName } from '$lib/help/types';
  import Art from '$components/art/Art.svelte';

  interface Props {
    art: ArtName;
    title?: string;
    text?: string;
    size?: 'normal' | 'small';
    testid?: string;
    children?: Snippet;
    action?: Snippet;
  }

  let { art, title, text, size = 'normal', testid, children, action }: Props = $props();
</script>

<div class="empty {size}" data-testid={testid}>
  <div class="art"><Art name={art} /></div>
  <div class="body">
    {#if title}<p class="title">{title}</p>{/if}
    {#if text}<p class="text">{text}</p>{/if}
    {@render children?.()}
    {#if action}<div class="action">{@render action()}</div>{/if}
  </div>
</div>

<style>
  .empty {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-4);
  }
  .art {
    flex: none;
    width: 14rem;
    aspect-ratio: 300 / 180;
  }
  .small .art {
    width: 9rem;
  }
  .body {
    flex: 1 1 14rem;
    min-width: 0;
    display: grid;
    gap: var(--space-2);
  }
  p {
    margin: 0;
  }
  .title {
    font-weight: var(--fw-semibold);
  }
  .text {
    color: var(--muted);
  }
  @media (--narrow) {
    .empty {
      justify-content: center;
      text-align: center;
    }
    .art {
      width: min(100%, 14rem);
      max-height: 140px;
    }
    .small .art {
      width: 8rem;
    }
    .action {
      justify-self: center;
    }
  }
</style>
