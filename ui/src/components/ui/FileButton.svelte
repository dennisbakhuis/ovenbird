<!--
  FileButton: a button-looking file picker. The native file input sits invisibly over the label so
  keyboard, drag and click all work; the focus ring shows on the label. `onchange` gets the event.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { IconName } from '$lib/core/icons';
  import Icon from './Icon.svelte';

  interface Props {
    accept?: string;
    icon?: IconName;
    testid?: string;
    onchange: (event: Event & { currentTarget: HTMLInputElement }) => void;
    children: Snippet;
  }

  let { accept, icon, testid, onchange, children }: Props = $props();
</script>

<label class="file">
  <span class="face">
    {#if icon}<Icon name={icon} size={18} />{/if}{@render children()}
  </span>
  <input type="file" {accept} {onchange} data-testid={testid} />
</label>

<style>
  @layer components {
    .file {
      position: relative;
      display: inline-flex;
    }
    input {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
      width: 100%;
    }
    .face {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      min-height: var(--tap);
      padding: 0.4rem 0.9rem;
      border: 1px solid var(--border);
      border-radius: var(--radius-control);
      font-weight: var(--fw-semibold);
      background: var(--surface);
    }
    .file:focus-within .face {
      outline: 3px solid var(--accent);
      outline-offset: 2px;
    }
  }
</style>
