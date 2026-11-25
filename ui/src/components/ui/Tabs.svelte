<script lang="ts">
  import type { IconName } from '$lib/core/icons';
  import Icon from './Icon.svelte';

  interface TabItem {
    id: string;
    label: string;
    href: string;
    icon?: IconName;
    count?: number;
  }

  let { items, active, label }: { items: TabItem[]; active: string; label: string } = $props();

  let strip: HTMLElement | undefined = $state();
  let fadeStart = $state(false);
  let fadeEnd = $state(false);
  let compact = $state(false);
  let needed = 0;

  function measure(): void {
    if (!strip) return;
    if (!compact && strip.scrollWidth > strip.clientWidth + 2) {
      needed = strip.scrollWidth;
      compact = true;
      return;
    }
    if (compact && strip.clientWidth >= needed) {
      compact = false;
      return;
    }
    fadeStart = strip.scrollLeft > 2;
    fadeEnd = strip.scrollLeft + strip.clientWidth < strip.scrollWidth - 2;
  }

  function reveal(): void {
    if (!strip) return;
    const current = strip.querySelector<HTMLElement>('[aria-current="page"]');
    if (current && strip.scrollWidth > strip.clientWidth) {
      const left = current.offsetLeft - strip.offsetLeft;
      const target = left - (strip.clientWidth - current.offsetWidth) / 2;
      strip.scrollLeft = Math.max(0, target);
    }
    measure();
  }

  const labels = $derived(items.map((item) => `${item.label}${item.count ?? ''}`).join('|'));

  $effect(() => {
    void labels;
    compact = false;
  });

  $effect(() => {
    void active;
    void compact;
    if (!strip) return;
    reveal();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(strip);
    return () => observer?.disconnect();
  });
</script>

<div class="wrap" class:fade-start={fadeStart} class:fade-end={fadeEnd} class:compact>
  <nav class="tabs" aria-label={label} bind:this={strip} onscroll={measure}>
    {#each items as item (item.id)}
      <a
        href={item.href}
        aria-current={item.id === active ? 'page' : undefined}
        title={item.label}
        class:iconic={Boolean(item.icon)}
      >
        {#if item.icon}<Icon name={item.icon} size={18} />{/if}
        <span class="label">{item.label}</span>
        {#if item.count}<span class="count">{item.count}</span>{/if}
      </a>
    {/each}
  </nav>
</div>

<style>
  .wrap {
    position: relative;
    margin: 0 0 var(--space-4);
    border-bottom: 1px solid var(--border);
  }
  .wrap::before,
  .wrap::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2rem;
    pointer-events: none;
    opacity: 0;
    transition: opacity var(--dur-fast) ease;
  }
  .wrap::before {
    left: 0;
    background: linear-gradient(to right, var(--bg), transparent);
  }
  .wrap::after {
    right: 0;
    background: linear-gradient(to left, var(--bg), transparent);
  }
  .fade-start::before,
  .fade-end::after {
    opacity: 1;
  }
  .tabs {
    display: flex;
    gap: var(--space-1);
    overflow-x: auto;
    scrollbar-width: none;
  }
  .tabs::-webkit-scrollbar {
    display: none;
  }
  a {
    padding: var(--space-2) 0.8rem;
    color: var(--muted);
    text-decoration: none;
    border-bottom: 3px solid transparent;
    white-space: nowrap;
    min-height: var(--tap);
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-weight: var(--fw-semibold);
  }
  a[aria-current='page'] {
    color: var(--text);
    border-bottom-color: var(--accent);
  }
  a:not([aria-current]):hover {
    color: var(--text);
  }
  a:focus-visible {
    outline-offset: -3px;
  }
  .compact a.iconic:not([aria-current]) {
    min-width: var(--tap);
    justify-content: center;
    padding: var(--space-2) 0.6rem;
  }
  .compact a.iconic:not([aria-current]) .label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .count {
    min-width: 1.25rem;
    padding: 0 0.35rem;
    border-radius: var(--radius-pill);
    background: var(--status-limited-bg);
    color: var(--status-limited);
    font-size: var(--fs-caption);
    text-align: center;
  }
</style>
