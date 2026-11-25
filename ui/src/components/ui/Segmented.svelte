<!--
  Segmented: one-of-many choice as a row of buttons. `semantics="pressed"` renders buttons with
  aria-pressed inside a labelled group; `semantics="radio"` renders visually hidden radio inputs
  (arrow keys move, one tab stop) for settings that behave like a form field. `appearance`:
  buttons (separate), joined (one frame), pill, radios (visible native radios) or cards (large
  radio cards whose content comes from the `option` snippet). `tint` swaps the accent fill for the
  soft tint; `fill` makes the items share the width equally.
-->
<script lang="ts" module>
  export interface SegmentedOption<V> {
    value: V;
    label: string;
    testid?: string;
    disabled?: boolean;
  }
</script>

<script lang="ts" generics="T extends string | number">
  import type { Snippet } from 'svelte';

  interface Props {
    options: SegmentedOption<T>[];
    value: T;
    onchange: (value: T) => void;
    label?: string;
    semantics?: 'pressed' | 'radio';
    appearance?: 'buttons' | 'joined' | 'pill' | 'radios' | 'cards';
    disabled?: boolean;
    itemClass?: string;
    option?: Snippet<[SegmentedOption<T>, boolean]>;
    size?: 'sm' | 'md';
    tint?: boolean;
    fill?: boolean;
    name?: string;
    wrap?: boolean;
    testid?: string;
    class?: string;
  }

  const uid = Math.random().toString(36).slice(2, 8);
  let {
    options,
    value,
    onchange,
    label,
    semantics = 'pressed',
    appearance = 'buttons',
    disabled = false,
    itemClass = '',
    option: optionContent,
    size = 'md',
    tint = false,
    fill = false,
    name = `segmented-${uid}`,
    wrap = false,
    testid,
    class: extra = '',
  }: Props = $props();

  function pick(next: T): void {
    onchange(next);
  }
</script>

<div
  class="segmented {appearance} {size} {extra}"
  class:tint
  class:fill
  class:wrap
  role={semantics === 'radio' ? 'radiogroup' : 'group'}
  aria-label={label}
  data-testid={testid}
>
  {#each options as option (option.value)}
    {#if semantics === 'radio'}
      <label class="item {itemClass}" class:checked={value === option.value}>
        <input
          type="radio"
          {name}
          value={option.value}
          checked={value === option.value}
          disabled={disabled || option.disabled}
          onchange={() => pick(option.value)}
          data-testid={option.testid}
        />
        {#if optionContent}{@render optionContent(option, value === option.value)}{:else}<span
            >{option.label}</span
          >{/if}
      </label>
    {:else}
      <button
        type="button"
        class="item {itemClass}"
        aria-pressed={value === option.value}
        disabled={disabled || option.disabled}
        onclick={() => pick(option.value)}
        data-testid={option.testid}
      >
        {option.label}
      </button>
    {/if}
  {/each}
</div>

<style>
  @layer components {
    .segmented {
      display: inline-flex;
      gap: var(--space-1);
    }
    .wrap {
      flex-wrap: wrap;
    }
    .fill {
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: 1fr;
    }
    .item {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      min-height: var(--control-h);
      min-width: 3.2rem;
      padding: 0.4rem 0.9rem;
      border: 1px solid var(--border);
      border-radius: var(--radius-control);
      background: var(--surface);
      color: var(--text);
      font: inherit;
      font-weight: var(--fw-semibold);
      cursor: pointer;
    }
    .item:hover:not(:disabled) {
      border-color: var(--accent);
    }
    .item:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .sm .item {
      min-height: 1.9rem;
      padding: var(--space-1) 0.7rem;
      font-weight: var(--fw-semibold);
    }
    .item input {
      position: absolute;
      opacity: 0;
      inset: 0;
      margin: 0;
      cursor: pointer;
    }
    .item:has(input:focus-visible) {
      outline: 3px solid var(--accent);
      outline-offset: -3px;
    }
    button.item[aria-pressed='true'] {
      background: var(--accent);
      border-color: var(--accent);
      color: var(--on-accent);
    }
    .item.checked {
      background: var(--accent);
      border-color: var(--accent);
      color: var(--on-accent);
    }
    .joined {
      gap: 0;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: hidden;
    }
    .joined .item {
      min-width: 0;
      min-height: var(--tap);
      padding: var(--space-1) 0.8rem;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: var(--text);
    }
    .joined.sm .item {
      min-height: 1.9rem;
      padding: var(--space-1) 0.7rem;
    }
    .joined .item:hover:not(:disabled) {
      border-color: var(--border);
    }
    .joined.tint {
      border-radius: var(--radius-control);
    }
    .joined.tint .item {
      min-height: var(--control-h);
    }
    .fill .item {
      min-width: 0;
      padding: 0 var(--space-2);
    }
    .joined .item + .item {
      border-left: 1px solid var(--border);
    }
    .joined button.item[aria-pressed='true'],
    .joined .item.checked {
      background: var(--accent);
      color: var(--on-accent);
    }
    .pill .item {
      min-height: var(--control-h);
      min-width: 0;
      padding: 0.3rem 0.7rem;
      border-radius: var(--radius-pill);
      font-size: var(--fs-caption);
      font-weight: inherit;
    }
    .tint .item {
      color: var(--muted);
    }
    .tint button.item[aria-pressed='true'],
    .tint .item.checked {
      background: var(--status-manual-bg);
      border-color: var(--border);
      color: var(--status-manual);
    }
    .radios {
      flex-wrap: wrap;
      gap: var(--space-1) var(--space-5);
    }
    .radios .item {
      justify-content: flex-start;
      gap: var(--space-2);
      min-width: 0;
      min-height: 44px;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: none;
      color: var(--text);
      font-weight: inherit;
    }
    .radios .item input {
      position: static;
      opacity: 1;
      width: 1.2rem;
      height: 1.2rem;
      margin: 3px 3px 3px 4px;
    }
    .radios .item:has(input:focus-visible) {
      outline: none;
    }
    .radios .item input:focus-visible {
      outline: 3px solid var(--accent);
      outline-offset: 2px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
      gap: var(--space-3);
    }
    .cards .item {
      flex-direction: column;
      align-items: stretch;
      justify-content: flex-start;
      gap: var(--space-1);
      min-width: 0;
      min-height: 0;
      padding: var(--space-3);
      border-radius: var(--radius);
      background: var(--surface);
      color: var(--text);
      font-weight: inherit;
      text-align: left;
    }
    .cards .item.checked {
      border: 2px solid var(--accent);
      padding: calc(var(--space-3) - 1px);
      background: color-mix(in srgb, var(--accent) 6%, var(--surface));
      color: var(--text);
    }
    .cards .item:has(input:focus-visible) {
      outline-offset: 2px;
    }
    @media (--narrow) {
      .cards {
        grid-template-columns: minmax(0, 1fr);
        gap: var(--space-2);
      }
    }
    @media (--narrow), (pointer: coarse) {
      .segmented:not(.radios, .cards, .joined) .item {
        min-height: var(--tap);
      }
      .joined.sm .item {
        min-height: var(--tap);
        padding-inline: 0.9rem;
      }
    }
  }
</style>
