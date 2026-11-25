<!--
  Checkbox: a native checkbox with its label text. The label wraps the control so the whole row
  is the click target; pass `children` for rich label content.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLInputAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLInputAttributes, 'class' | 'type' | 'children'> {
    checked?: boolean;
    label?: string;
    class?: string;
    children?: Snippet;
  }

  let { checked = $bindable(false), label, class: extra = '', children, ...rest }: Props = $props();
</script>

<label class="check {extra}">
  <input {...rest} type="checkbox" bind:checked />
  {#if children}<span>{@render children()}</span>{:else if label}<span>{label}</span>{/if}
</label>

<style>
  @layer components {
    .check {
      display: inline-flex;
      align-items: flex-start;
      gap: var(--space-2);
      cursor: pointer;
    }
    input {
      flex: none;
      width: 1.3rem;
      height: 1.3rem;
      margin: 0.1rem 0 0;
    }
  }
</style>
