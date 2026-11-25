<!--
  TextInput: the one text-like input (text, search, number, time, ...). With `unit` the unit
  sits inside the frame after the value. `invalid` sets aria-invalid and the error border.
  Everything else (id, placeholder, maxlength, oninput, data-testid, ...) passes through.
-->
<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLInputAttributes, 'class' | 'children'> {
    value?: HTMLInputAttributes['value'];
    invalid?: boolean;
    unit?: string;
    align?: 'start' | 'end';
    block?: boolean;
    framed?: boolean;
    width?: string;
    class?: string;
    element?: HTMLInputElement;
  }

  let {
    value = $bindable(),
    invalid = false,
    unit,
    align = 'start',
    block = true,
    framed = false,
    width,
    class: extra = '',
    element = $bindable(),
    type = 'text',
    disabled,
    ...rest
  }: Props = $props();
</script>

{#if unit || framed}
  <span
    class="frame {extra}"
    class:invalid
    class:disabled
    style:width
    style:max-width={width ? '100%' : undefined}
  >
    <input
      {...rest}
      {type}
      {disabled}
      aria-invalid={invalid || undefined}
      class="bare"
      class:end={align === 'end'}
      bind:value
      bind:this={element}
    />
    {#if unit}<span class="unit">{unit}</span>{/if}
  </span>
{:else}
  <input
    {...rest}
    {type}
    {disabled}
    aria-invalid={invalid || undefined}
    class="field {extra}"
    class:invalid
    class:block={block && !width}
    style:width
    style:max-width={width ? '100%' : undefined}
    class:end={align === 'end'}
    bind:value
    bind:this={element}
  />
{/if}

<style>
  @layer components {
    .field,
    .frame {
      box-sizing: border-box;
      min-height: var(--tap);
      border: 1px solid var(--border);
      border-radius: var(--radius-control);
      background: var(--surface);
      color: var(--text);
      font: inherit;
    }
    .field {
      padding: 0.4rem 0.6rem;
    }
    .block {
      width: 100%;
      max-width: 28rem;
    }
    .frame {
      display: flex;
      align-items: center;
    }
    .frame:focus-within {
      outline: 3px solid var(--accent);
      outline-offset: 1px;
    }
    .invalid {
      border-color: var(--err-text);
    }
    .field:disabled,
    .frame.disabled {
      background: var(--surface-2);
      color: var(--muted);
    }
    .bare {
      flex: 1;
      width: 100%;
      min-width: 0;
      min-height: calc(var(--tap) - 2px);
      padding: 0 0.6rem;
      border: none;
      background: transparent;
      color: inherit;
      font: inherit;
      font-variant-numeric: tabular-nums;
    }
    .bare:focus-visible {
      outline: none;
    }
    .end {
      text-align: right;
    }
    .unit {
      padding-right: 0.6rem;
      color: var(--muted);
      white-space: nowrap;
      font-size: var(--fs-caption);
    }
  }
</style>
