<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '$lib/core/settings.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import Overlay from './Overlay.svelte';

  interface Props {
    title: string;
    onclose: () => void;
    children: Snippet;
    footer?: Snippet;
    testid?: string;
  }

  let { title, onclose, children, footer, testid = 'modal' }: Props = $props();

  const titleId = `modal-${Math.random().toString(36).slice(2, 8)}`;
</script>

<Overlay
  modal
  backdrop
  autofocus
  restoreFocus
  {onclose}
  class="modal-dialog"
  role="dialog"
  aria-labelledby={titleId}
  data-testid={testid}
>
  <header>
    <h2 id={titleId}>{title}</h2>
    <Button class="modal-close" onclick={onclose} aria-label={t('close')}>
      <Icon name="close" size={22} />
    </Button>
  </header>
  <div class="body">{@render children()}</div>
  {#if footer}
    <footer>{@render footer()}</footer>
  {/if}
</Overlay>

<style>
  :global(.modal-dialog) {
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow-pop);
    width: min(60rem, 100%);
    max-height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  h2 {
    margin: 0;
  }
  :global(.modal-close) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: var(--tap);
    min-height: var(--tap);
    padding: 0;
    border-color: transparent;
    background: transparent;
  }
  .body {
    padding: var(--space-4);
    overflow: auto;
    overscroll-behavior: contain;
    min-width: 0;
  }
  footer {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    justify-content: flex-end;
    padding: var(--space-3) var(--space-4);
    border-top: 1px solid var(--border);
  }
  @media (--narrow) {
    :global(.modal-dialog) {
      width: 100%;
      height: 100%;
      border-radius: 0;
      border: none;
    }
    footer {
      padding-bottom: calc(var(--space-3) + env(safe-area-inset-bottom));
    }
  }
</style>
