<!--
  Button: the one place that styles every standard button. Variants: default, primary, danger,
  ghost (transparent), link (text), icon (square, no frame) and bare (behaviour only: the look
  is entirely the caller's, for list rows and triggers). `href` renders an anchor that looks the
  same. `busy` disables the button, sets aria-busy and shows a spinner. Everything else (type,
  disabled, aria-*, onclick, data-*) passes through. Callers style layout through `class`.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAnchorAttributes, HTMLButtonAttributes } from 'svelte/elements';
  import type { IconName } from '$lib/core/icons';
  import Icon from './Icon.svelte';

  type Variant = 'default' | 'primary' | 'danger' | 'ghost' | 'link' | 'icon' | 'bare';

  interface Props extends Omit<HTMLButtonAttributes, 'class' | 'children'> {
    variant?: Variant;
    size?: 'sm' | 'md';
    href?: string;
    target?: HTMLAnchorAttributes['target'];
    rel?: HTMLAnchorAttributes['rel'];
    download?: HTMLAnchorAttributes['download'];
    busy?: boolean;
    icon?: IconName;
    iconSize?: number;
    solid?: boolean;
    class?: string;
    element?: HTMLElement;
    children?: Snippet;
  }

  let {
    variant = 'default',
    size = 'md',
    href,
    busy = false,
    icon,
    iconSize = 18,
    solid = false,
    class: extra = '',
    element = $bindable(),
    type = 'button',
    disabled,
    children,
    ...rest
  }: Props = $props();

  const inert = $derived(Boolean(disabled) || busy);
</script>

<svelte:element
  this={href ? 'a' : 'button'}
  {...rest}
  bind:this={element}
  href={href && !inert ? href : undefined}
  type={href ? undefined : type}
  disabled={href ? undefined : inert}
  aria-disabled={href && inert ? 'true' : undefined}
  aria-busy={busy ? 'true' : undefined}
  class="btn {variant} {size} {extra}"
  class:solid
>
  {#if busy}<span class="spin" aria-hidden="true"></span>{:else if icon}<Icon
      name={icon}
      size={iconSize}
    />{/if}{@render children?.()}
</svelte:element>

<style>
  @layer components {
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: var(--space-2);
      box-sizing: border-box;
      min-height: var(--control-h);
      padding: 0.4rem 0.9rem;
      border: 1px solid var(--border);
      border-radius: var(--radius-control);
      background: var(--surface);
      color: var(--text);
      font: inherit;
      font-weight: var(--fw-semibold);
      text-decoration: none;
      cursor: pointer;
    }
    .btn:hover:not(:disabled, [aria-disabled='true']) {
      border-color: var(--accent);
    }
    .btn:disabled,
    .btn[aria-disabled='true'] {
      opacity: 0.55;
      cursor: not-allowed;
    }
    .btn[aria-busy='true'] {
      cursor: progress;
    }
    .sm {
      min-height: 32px;
      padding: 0.15rem 0.6rem;
      font-size: var(--fs-caption);
    }
    .primary {
      background: var(--accent);
      border-color: var(--accent);
      color: var(--on-accent);
    }
    .danger {
      border-color: var(--status-stopped);
      color: var(--status-stopped);
    }
    .danger.solid {
      background: var(--cat-stopped);
      border-color: var(--cat-stopped);
      color: var(--on-solid);
    }
    .ghost {
      border-color: transparent;
      background: transparent;
    }
    .ghost:hover:not(:disabled, [aria-disabled='true']) {
      background: var(--surface-2);
    }
    .link {
      min-height: 0;
      padding: 0;
      border: none;
      background: none;
      color: var(--accent);
      font-weight: var(--fw-medium);
    }
    .link:hover:not(:disabled, [aria-disabled='true']) {
      text-decoration: underline;
    }
    .icon {
      min-width: var(--control-h);
      padding: 0;
      border-color: transparent;
      background: transparent;
    }
    .icon.sm {
      min-width: 32px;
    }
    .bare {
      min-height: 0;
      padding: 0;
      border: none;
      border-radius: 0;
      background: none;
      color: inherit;
      font-weight: inherit;
      gap: 0;
    }
    .bare:hover:not(:disabled, [aria-disabled='true']) {
      border-color: transparent;
    }
    @media (--narrow), (pointer: coarse) {
      .btn:not(.bare, .link) {
        min-height: var(--tap);
      }
      .icon {
        min-width: var(--tap);
      }
    }
  }
  .spin {
    width: 1em;
    height: 1em;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    animation: btn-spin 0.8s linear infinite;
  }
  @keyframes btn-spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
