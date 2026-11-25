<!--
  InlineMessage: a short tinted message under a control or inside a card. Errors announce
  themselves (role="alert"); warnings, confirmations and notes do not.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { IconName } from '$lib/core/icons';
  import Icon from './Icon.svelte';

  type Tone = 'error' | 'warn' | 'ok' | 'info';

  interface Props {
    tone?: Tone;
    icon?: boolean;
    size?: 'sm' | 'md';
    role?: 'alert' | 'status' | 'none';
    testid?: string;
    class?: string;
    children: Snippet;
  }

  let {
    tone = 'info',
    icon = false,
    size = 'sm',
    role,
    testid,
    class: extra = '',
    children,
  }: Props = $props();

  const ICON: Record<Tone, IconName> = {
    error: 'critical',
    warn: 'warning',
    ok: 'check',
    info: 'info',
  };
  const resolved = $derived(role ?? (tone === 'error' ? 'alert' : undefined));
</script>

<p
  class="message {tone} {size} {extra}"
  role={resolved === 'none' ? undefined : resolved}
  data-testid={testid}
>
  {#if icon}<Icon name={ICON[tone]} size={16} />{/if}<span>{@render children()}</span>
</p>

<style>
  @layer components {
    .message {
      display: flex;
      align-items: flex-start;
      gap: 0.35rem;
      margin: 0;
      border-radius: var(--radius-sm);
    }
    .message :global(.icon) {
      flex: none;
      margin-top: 1px;
    }
    .sm {
      padding: 0.3rem var(--space-2);
      font-size: var(--fs-caption);
    }
    .md {
      padding: var(--space-2) var(--space-3);
      border-radius: var(--radius-control);
    }
    .error {
      background: var(--err-bg);
      color: var(--err-text);
    }
    .warn {
      background: var(--warn-bg);
      color: var(--warn-text);
    }
    .ok {
      background: var(--status-ok-bg);
      color: var(--status-ok);
    }
    .info {
      background: var(--status-manual-bg);
      color: var(--status-manual);
    }
  }
</style>
