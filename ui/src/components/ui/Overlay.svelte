<!--
  Overlay: the shared base of Modal, the Why popover and sheet, the help drawer. One place for
  portal, scroll lock, focus trap, Escape, outside-click dismissal and focus restore. It renders
  a fixed layer (optionally dimmed) holding one panel and optional `beside` content; the consumer styles the panel through the
  `class` prop and its own `:global` rules.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { lockScroll, portal as portalAction, trapFocus } from '$lib/core/overlay';

  type Layer = 'modal' | 'popover' | 'drawer' | 'menu';

  interface Props extends Omit<HTMLAttributes<HTMLDivElement>, 'class' | 'children'> {
    onclose?: () => void;
    onoutside?: () => void;
    modal?: boolean;
    portal?: boolean;
    layer?: Layer;
    backdrop?: boolean;
    scrim?: boolean;
    escape?: boolean;
    escapePrevent?: boolean;
    outside?: boolean;
    ignore?: () => (Element | null | undefined)[];
    autofocus?: boolean;
    restoreFocus?: boolean;
    layerClass?: string;
    layerAttrs?: Record<string, string | undefined>;
    class?: string;
    element?: HTMLDivElement;
    children: Snippet;
    beside?: Snippet;
  }

  let {
    onclose,
    onoutside,
    modal = false,
    portal = true,
    layer = 'modal',
    backdrop = false,
    scrim = false,
    escape = true,
    escapePrevent = false,
    outside = false,
    ignore,
    autofocus = false,
    restoreFocus = false,
    layerClass = '',
    layerAttrs = {},
    class: panelClass = '',
    element = $bindable(),
    children,
    beside,
    onkeydown,
    ...rest
  }: Props = $props();

  const mount = (node: HTMLElement, enabled: boolean) =>
    enabled ? portalAction(node) : { destroy: () => undefined };

  $effect(() => {
    if (!modal) return;
    return lockScroll();
  });

  $effect(() => {
    if (!restoreFocus) return;
    const previous = document.activeElement as HTMLElement | null;
    return () => previous?.focus?.();
  });

  $effect(() => {
    if (autofocus) element?.focus();
  });

  $effect(() => {
    if (!outside) return;
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (element?.contains(target)) return;
      if (ignore?.().some((item) => item?.contains(target))) return;
      (onoutside ?? onclose)?.();
    };
    document.addEventListener('pointerdown', onPointer, true);
    return () => document.removeEventListener('pointerdown', onPointer, true);
  });

  function handleKeydown(event: KeyboardEvent & { currentTarget: EventTarget & HTMLDivElement }) {
    if (escape && event.key === 'Escape' && onclose) {
      if (escapePrevent) event.preventDefault();
      event.stopPropagation();
      onclose();
      return;
    }
    if (modal && element) trapFocus(event, element);
    (onkeydown as ((e: typeof event) => void) | undefined)?.(event);
  }
</script>

<div
  class="ov-layer {layerClass}"
  class:backdrop
  style:z-index="var(--z-{layer})"
  use:mount={portal}
  {...layerAttrs}
>
  {#if scrim}<div class="ov-scrim" aria-hidden="true"></div>{/if}
  <div
    {...rest}
    class="ov-panel {panelClass}"
    aria-modal={modal ? 'true' : undefined}
    tabindex="-1"
    bind:this={element}
    onkeydown={handleKeydown}
  >
    {@render children()}
  </div>
  {@render beside?.()}
</div>

<style>
  .ov-layer {
    position: fixed;
    inset: 0;
    pointer-events: none;
  }
  .ov-layer.backdrop {
    pointer-events: auto;
    background: var(--backdrop);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-4);
    overscroll-behavior: contain;
  }
  .ov-scrim {
    position: absolute;
    inset: 0;
    background: var(--backdrop);
    pointer-events: auto;
  }
  .ov-panel {
    pointer-events: auto;
  }
  .ov-panel:focus {
    outline: none;
  }
  @media (--narrow) {
    .ov-layer.backdrop {
      padding: 0;
    }
  }
</style>
