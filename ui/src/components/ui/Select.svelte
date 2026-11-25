<!--
  Select: the one native select. Options come in as children (`<option>`s). `invalid` sets
  aria-invalid and the error border; everything else passes through.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLSelectAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLSelectAttributes, 'class' | 'children'> {
    invalid?: boolean;
    block?: boolean;
    class?: string;
    element?: HTMLSelectElement;
    children: Snippet;
  }

  let {
    value = $bindable(),
    invalid = false,
    block = true,
    class: extra = '',
    element = $bindable(),
    children,
    ...rest
  }: Props = $props();
</script>

<select
  {...rest}
  aria-invalid={invalid || undefined}
  class="select {extra}"
  class:invalid
  class:block
  bind:value
  bind:this={element}
>
  {@render children()}
</select>

<style>
  @layer components {
    .select {
      box-sizing: border-box;
      min-height: var(--tap);
      padding: 0.4rem 0.6rem;
      border: 1px solid var(--border);
      border-radius: var(--radius-control);
      background: var(--surface);
      color: var(--text);
      font: inherit;
    }
    .block {
      width: 100%;
      max-width: 28rem;
    }
    .invalid {
      border-color: var(--err-text);
    }
    .select:disabled {
      background: var(--surface-2);
      color: var(--muted);
    }
  }
</style>
