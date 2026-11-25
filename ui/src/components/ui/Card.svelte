<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import type { IconName } from '$lib/core/icons';
  import Icon from './Icon.svelte';

  type Span = 3 | 4 | 5 | 6 | 7 | 8 | 9 | 12;
  type Tone = 'default' | 'ok' | 'limited' | 'stopped' | 'manual';

  interface Props extends Omit<
    HTMLAttributes<HTMLElement>,
    'class' | 'children' | 'title' | 'style'
  > {
    title?: string;
    subtitle?: string;
    icon?: IconName;
    href?: string;
    linkLabel?: string;
    span?: Span;
    bare?: boolean;
    as?: 'section' | 'div' | 'a';
    class?: string;
    tone?: Tone;
    level?: 2 | 3;
    flush?: boolean;
    testid?: string;
    help?: string;
    hint?: string;
    style?: string;
    element?: HTMLElement;
    actions?: Snippet;
    children: Snippet;
  }

  let {
    title,
    subtitle,
    icon,
    href,
    linkLabel,
    span,
    bare = false,
    as = 'section',
    class: extra = '',
    tone = 'default',
    level = 2,
    flush = false,
    testid,
    help,
    hint,
    style,
    element = $bindable(),
    actions,
    children,
    ...rest
  }: Props = $props();

  const columns = $derived(span ?? (bare ? undefined : 12));
  const root = $derived(as === 'a' ? 'a' : as);
</script>

<svelte:element
  this={root}
  data-testid={testid}
  data-help={help}
  title={hint}
  {...rest}
  href={as === 'a' ? href : undefined}
  class="card {columns ? `span-${columns}` : ''} tone-{tone} {extra}"
  class:bare
  class:flush
  {style}
  bind:this={element}
>
  {#if title || actions}
    <header>
      {#if title}
        <svelte:element this={level === 2 ? 'h2' : 'h3'} class="title">
          {#if icon}<Icon name={icon} size={18} />{/if}
          <span>{title}</span>
        </svelte:element>
      {/if}
      {#if actions}<div class="actions">{@render actions()}</div>{/if}
      {#if href && as !== 'a'}
        <a class="more hit" {href}>
          {linkLabel ?? ''}<Icon
            name="chevronRight"
            size={16}
            label={linkLabel ? undefined : title}
          />
        </a>
      {/if}
    </header>
    {#if subtitle}<p class="subtitle">{subtitle}</p>{/if}
  {/if}
  {@render children()}
</svelte:element>

<style>
  @layer components {
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: var(--card-pad);
      min-width: 0;
    }
    .card:not(.bare) {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    @container main (max-width: 40rem) {
      .card {
        --card-pad: 0.75rem;
      }
    }
  }
  .card.flush {
    padding: 0;
    overflow: hidden;
  }
  .tone-ok {
    border-color: var(--cat-normal);
  }
  .tone-limited {
    border-color: var(--cat-limited);
    background: color-mix(in srgb, var(--status-limited-bg) 45%, var(--surface));
  }
  .tone-stopped {
    border-color: var(--cat-stopped);
    background: color-mix(in srgb, var(--status-stopped-bg) 45%, var(--surface));
  }
  .tone-manual {
    border-color: var(--cat-manual);
  }
  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    min-height: 1.5rem;
  }
  .title {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0;
    font-size: var(--fs-emph);
    flex: 1 1 12rem;
    min-width: 0;
  }
  .title :global(.icon) {
    color: var(--muted);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .more {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    font-size: var(--fs-body);
    text-decoration: none;
    font-weight: var(--fw-medium);
  }
  .more:hover {
    text-decoration: underline;
  }
  .subtitle {
    margin: calc(-1 * var(--space-2)) 0 0;
    color: var(--muted);
    font-size: var(--fs-caption);
  }
</style>
