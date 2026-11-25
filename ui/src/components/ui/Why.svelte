<script lang="ts">
  import type { Snippet } from 'svelte';
  import { help } from '$lib/help/store.svelte';
  import { t } from '$lib/core/settings.svelte';
  import Button from './Button.svelte';
  import Icon from './Icon.svelte';
  import Overlay from './Overlay.svelte';
  import { NARROW_QUERY } from '$lib/core/breakpoints';

  interface Props {
    title?: string;
    label?: string;
    ariaLabel?: string;
    trigger?: Snippet;
    triggerClass?: string;
    align?: 'start' | 'end';
    sheet?: 'auto' | 'always' | 'never';
    width?: string;
    open?: boolean;
    testid?: string;
    triggerAttrs?: Record<string, string | undefined>;
    children: Snippet;
  }

  let {
    title,
    label,
    ariaLabel,
    trigger,
    triggerClass = '',
    align = 'start',
    sheet = 'auto',
    width = '22rem',
    open = $bindable(false),
    testid = 'why',
    triggerAttrs = {},
    children,
  }: Props = $props();

  const id = `why-${Math.random().toString(36).slice(2, 8)}`;
  let button: HTMLElement | undefined = $state();
  let panel: HTMLDivElement | undefined = $state();
  let asSheet = $state(false);
  let helpTarget = $state<string | null>(null);
  let place = $state<{ top: number; left: number; width: number; up: boolean }>({
    top: 0,
    left: 0,
    width: 0,
    up: false,
  });

  const name = $derived(ariaLabel ?? title ?? label ?? t('whyLabel'));

  function phone(): boolean {
    return typeof window.matchMedia === 'function'
      ? window.matchMedia(NARROW_QUERY).matches
      : window.innerWidth <= 640;
  }

  function position(): void {
    if (!button || asSheet) return;
    const rect = button.getBoundingClientRect();
    const gutter = 8;
    const room = window.innerWidth - 2 * gutter;
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const wanted = width.endsWith('rem') ? parseFloat(width) * rem : parseFloat(width) || 352;
    const w = Math.min(wanted, room);
    const left =
      align === 'end'
        ? Math.max(gutter, Math.min(rect.right - w, window.innerWidth - gutter - w))
        : Math.max(gutter, Math.min(rect.left, window.innerWidth - gutter - w));
    const height = panel?.offsetHeight ?? 0;
    const below = window.innerHeight - rect.bottom;
    const up = height > 0 && below < height + 16 && rect.top > below;
    place = { top: up ? rect.top - 6 : rect.bottom + 6, left, width: w, up };
  }

  function toggle(): void {
    open = !open;
  }

  function close(returnFocus = true): void {
    if (!open) return;
    open = false;
    if (returnFocus) button?.focus();
  }

  $effect(() => {
    if (!open) return;
    asSheet = sheet === 'always' || (sheet === 'auto' && phone());
    helpTarget = button?.closest<HTMLElement>('[data-help]')?.dataset['help'] ?? null;
    position();
    const frame = requestAnimationFrame(() => {
      position();
      if (panel && !panel.contains(document.activeElement)) panel.focus();
    });
    const onMove = () => position();
    window.addEventListener('resize', onMove);
    window.addEventListener('scroll', onMove, true);
    const onHash = () => close(false);
    window.addEventListener('hashchange', onHash);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', onMove);
      window.removeEventListener('scroll', onMove, true);
      window.removeEventListener('hashchange', onHash);
    };
  });

  function moreHelp(): void {
    const target = helpTarget;
    close();
    if (target) help.show(target);
  }

  function onfocusout(event: FocusEvent): void {
    if (asSheet) return;
    const next = event.relatedTarget as Node | null;
    if (next && (panel?.contains(next) || button?.contains(next))) return;
    if (next) close(false);
  }
</script>

<Button
  class="why-trigger {trigger ? 'why-custom' : label ? 'why-text' : 'why-icon'} {triggerClass}"
  aria-expanded={open}
  aria-controls={open ? id : undefined}
  aria-haspopup="dialog"
  aria-label={trigger || !label ? name : undefined}
  bind:element={button}
  onclick={toggle}
  onkeydown={(event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      close();
    }
  }}
  data-testid={`${testid}-button`}
  {...triggerAttrs}
>
  {#if trigger}
    {@render trigger()}
  {:else if label}
    <Icon name="why" size={16} />{label}
  {:else}
    <Icon name="why" size={18} />
  {/if}
</Button>

{#if open}
  <Overlay
    {id}
    modal={asSheet}
    scrim={asSheet}
    layer="popover"
    outside
    ignore={() => [button]}
    onclose={() => close()}
    onoutside={() => close(false)}
    layerClass="why-layer {asSheet ? 'sheet' : ''}"
    class="why-panel {place.up ? 'up' : ''}"
    role="dialog"
    aria-label={title ? undefined : name}
    aria-labelledby={title ? `${id}-title` : undefined}
    style={asSheet ? undefined : `top:${place.top}px;left:${place.left}px;width:${place.width}px`}
    bind:element={panel}
    {onfocusout}
    data-testid={testid}
  >
    <div class="head">
      {#if title}<h2 id="{id}-title">{title}</h2>{/if}
      <Button class="why-close" onclick={() => close()} aria-label={t('close')}>
        <Icon name="close" size={20} />
      </Button>
    </div>
    <div class="content">
      {@render children()}
      {#if helpTarget}
        <p class="more-help">
          <Button class="why-more" onclick={moreHelp} data-testid="why-more-help">
            {t('helpMoreInHelp')}<Icon name="arrowRight" size={16} />
          </Button>
        </p>
      {/if}
    </div>
  </Overlay>
{/if}

<style>
  :global(.why-trigger) {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    min-height: 0;
    padding: 0;
    border: none;
    background: none;
    color: var(--muted);
    font-weight: var(--fw-medium);
    cursor: pointer;
  }
  :global(.why-trigger.why-icon) {
    flex: none;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    vertical-align: middle;
  }
  :global(.why-trigger.why-text) {
    color: var(--accent);
    font-size: var(--fs-body);
    padding: var(--space-1) 0;
  }
  :global(.why-trigger:hover:not(:disabled)) {
    color: var(--accent);
  }
  :global(.why-trigger[aria-expanded='true']) {
    color: var(--accent);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.why-trigger.why-icon) {
      width: var(--tap);
      height: var(--tap);
      margin: -6px;
    }
    :global(.why-trigger.why-text) {
      min-height: var(--tap);
      margin-block: -8px;
    }
  }
  :global(.why-panel) {
    position: fixed;
    max-height: min(70vh, 32rem);
    overflow: auto;
    overscroll-behavior: contain;
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow-pop);
    font-size: var(--fs-body);
    text-align: left;
  }
  :global(.why-panel.up) {
    transform: translateY(-100%);
  }
  :global(.why-layer.sheet .why-panel) {
    left: 0;
    right: 0;
    bottom: 0;
    top: auto;
    width: auto;
    max-height: 85vh;
    border-radius: var(--radius-sheet) var(--radius-sheet) 0 0;
    border-bottom: none;
    padding-bottom: env(safe-area-inset-bottom);
    transform: none;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-1) 0 var(--space-4);
    position: sticky;
    top: 0;
    background: var(--surface);
  }
  .head h2 {
    margin: 0;
    font-size: var(--fs-emph);
  }
  :global(.why-close) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-left: auto;
    min-width: 40px;
    min-height: var(--control-h);
    padding: 0;
    border-color: transparent;
    background: transparent;
    color: var(--muted);
  }
  :global(.why-layer.sheet .why-close) {
    min-width: var(--tap);
    min-height: var(--tap);
  }
  .content {
    padding: 0 var(--space-4) var(--space-4);
    line-height: var(--lh-body);
  }
  .content :global(p) {
    margin: var(--space-2) 0 0;
  }
  .content :global(p:first-child) {
    margin-top: var(--space-1);
  }
  .content .more-help {
    margin: var(--space-3) 0 0;
    padding-top: var(--space-2);
    border-top: 1px solid var(--border);
  }
  :global(.why-more) {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    min-height: 32px;
    padding: 0;
    border: none;
    background: none;
    color: var(--accent);
    font-weight: var(--fw-bold);
  }
  :global(.why-more):hover {
    text-decoration: underline;
  }
</style>
