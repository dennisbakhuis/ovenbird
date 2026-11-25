<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import type { IconName } from '$lib/core/icons';
  import Icon from './Icon.svelte';

  type Tone =
    | 'good'
    | 'warn'
    | 'bad'
    | 'info'
    | 'neutral'
    | 'ok'
    | 'limited'
    | 'frozen'
    | 'stopped'
    | 'manual'
    | 'unknown'
    | 'plain';

  interface Props extends Omit<HTMLAttributes<HTMLElement>, 'class' | 'children' | 'onclick'> {
    tone?: Tone;
    icon?: IconName;
    href?: string;
    title?: string;
    size?: 'sm' | 'md';
    testid?: string;
    interactive?: boolean;
    pressed?: boolean;
    onclick?: (event: MouseEvent) => void;
    removable?: boolean;
    onremove?: () => void;
    removeLabel?: string;
    class?: string;
    children: Snippet;
  }

  let {
    tone = 'neutral',
    icon,
    href,
    title,
    size = 'sm',
    testid,
    interactive = false,
    pressed,
    onclick,
    removable = false,
    onremove,
    removeLabel,
    class: extra = '',
    children,
    ...rest
  }: Props = $props();

  const ALIAS: Record<Tone, string> = {
    good: 'ok',
    warn: 'limited',
    bad: 'stopped',
    info: 'manual',
    neutral: 'unknown',
    ok: 'ok',
    limited: 'limited',
    frozen: 'frozen',
    stopped: 'stopped',
    manual: 'manual',
    unknown: 'unknown',
    plain: 'plain',
  };
  const asButton = $derived(interactive || Boolean(onclick));
  const element = $derived(href ? 'a' : asButton ? 'button' : 'span');
</script>

<svelte:element
  this={element}
  {...rest}
  {href}
  {title}
  type={asButton && !href ? 'button' : undefined}
  aria-pressed={asButton && pressed !== undefined ? pressed : undefined}
  {onclick}
  class="pill {ALIAS[tone]} {size} {extra}"
  class:link={Boolean(href)}
  class:interactive={asButton}
  data-testid={testid}
>
  {#if icon}<Icon name={icon} size={size === 'sm' ? 14 : 16} />{/if}{@render children()}
  {#if href}<Icon name="chevronRight" size={14} class="go" />{/if}
  {#if removable}
    <button
      type="button"
      class="remove"
      aria-label={removeLabel}
      onclick={(event) => {
        event.stopPropagation();
        onremove?.();
      }}
    >
      <Icon name="close" size={12} />
    </button>
  {/if}
</svelte:element>

<style>
  @layer components {
    .pill {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      padding: 0.1rem 0.6rem;
      border-radius: var(--radius-pill);
      font-size: var(--fs-caption);
      font-weight: var(--fw-semibold);
      white-space: nowrap;
      line-height: 1.5;
      text-decoration: none;
      vertical-align: middle;
    }
    .md {
      padding: var(--space-1) var(--space-3);
      font-size: var(--fs-body);
    }
    .link {
      padding-right: 0.35rem;
    }
    .link:hover {
      text-decoration: underline;
    }
    .ok {
      background: var(--status-ok-bg);
      color: var(--status-ok);
    }
    .limited {
      background: var(--status-limited-bg);
      color: var(--status-limited);
    }
    .frozen {
      background: var(--status-frozen-bg);
      color: var(--status-frozen);
    }
    .stopped {
      background: var(--status-stopped-bg);
      color: var(--status-stopped);
    }
    .manual {
      background: var(--status-manual-bg);
      color: var(--status-manual);
    }
    .unknown {
      background: var(--status-unknown-bg);
      color: var(--status-unknown);
    }
    .plain {
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
    }
    .interactive {
      font-family: inherit;
      cursor: pointer;
    }
    .remove {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin: 0 -0.3rem 0 0;
      padding: 0;
      border: 0;
      border-radius: 50%;
      background: transparent;
      color: inherit;
      cursor: pointer;
    }
    .remove:hover {
      background: var(--surface-2);
    }
  }
</style>
