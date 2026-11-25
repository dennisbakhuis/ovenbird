<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { IconName } from '$lib/core/icons';
  import { t } from '$lib/core/settings.svelte';
  import Icon from './Icon.svelte';

  type Tone = 'default' | 'ok' | 'limited' | 'frozen' | 'stopped' | 'manual' | 'unknown';
  type Trend = 'up' | 'down' | 'flat';

  interface Props {
    label: string;
    value: string;
    unit?: string;
    icon?: IconName;
    iconColor?: string;
    tone?: Tone;
    caption?: string;
    trend?: Trend | null;
    trendLabel?: string;
    stale?: boolean;
    href?: string;
    size?: 'sm' | 'md' | 'lg';
    title?: string;
    testid?: string;
    children?: Snippet;
  }

  let {
    label,
    value,
    unit,
    icon,
    iconColor,
    tone = 'default',
    caption,
    trend = null,
    trendLabel,
    stale = false,
    href,
    size = 'md',
    title,
    testid,
    children,
  }: Props = $props();

  const TREND_ICON: Record<Trend, IconName> = {
    up: 'trendUp',
    down: 'trendDown',
    flat: 'trendFlat',
  };
  const TREND_KEY = { up: 'trendRising', down: 'trendFalling', flat: 'trendSteady' } as const;
</script>

<svelte:element
  this={href ? 'a' : 'div'}
  {href}
  class="stat {size} tone-{tone}"
  class:stale
  class:link={Boolean(href)}
  {title}
  data-testid={testid}
>
  <span class="label">
    {#if icon}<span class="icon-wrap" style:color={iconColor}><Icon name={icon} size={16} /></span
      >{/if}
    <span class="label-text">{label}</span>
  </span>
  <span class="reading">
    <span class="value">{value}</span>{#if unit}<span class="unit">&#8239;{unit}</span>{/if}
    {#if trend}
      <span class="trend" title={trendLabel ?? t(TREND_KEY[trend])}>
        <Icon name={TREND_ICON[trend]} size={18} label={trendLabel ?? t(TREND_KEY[trend])} />
      </span>
    {/if}
  </span>
  {#if children}<span class="extra">{@render children()}</span>{/if}
  {#if caption}<span class="caption">{caption}</span>{/if}
</svelte:element>

<style>
  .stat {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text);
    text-decoration: none;
  }
  .stat.link:hover {
    border-color: var(--accent);
  }
  .label {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    color: var(--muted);
    font-size: var(--fs-caption);
    font-weight: var(--fw-medium);
    min-width: 0;
  }
  .label-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .icon-wrap {
    display: inline-flex;
  }
  .reading {
    display: flex;
    align-items: baseline;
    gap: 0;
    flex-wrap: wrap;
    line-height: var(--lh-tight);
  }
  .value {
    font-size: var(--fs-value);
    font-family: var(--font-display);
    font-weight: var(--fw-semibold);
  }
  .sm .value {
    font-size: var(--fs-emph);
  }
  .lg .value {
    font-size: var(--fs-hero);
    font-family: var(--font-display);
    font-weight: var(--fw-strong);
    letter-spacing: -0.02em;
  }
  .unit {
    color: var(--muted);
    font-size: var(--fs-body);
  }
  .lg .unit {
    font-size: var(--fs-value);
    font-family: var(--font-display);
  }
  .trend {
    display: inline-flex;
    align-self: center;
    margin-left: 0.35rem;
    color: var(--muted);
  }
  .extra {
    display: block;
    min-width: 0;
  }
  .caption {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .sm {
    padding: var(--space-2) var(--space-3);
  }
  .tone-ok {
    border-left: 3px solid var(--cat-normal);
  }
  .tone-limited {
    border-left: 3px solid var(--cat-limited);
  }
  .tone-frozen {
    border-left: 3px solid var(--cat-frozen);
  }
  .tone-stopped {
    border-left: 3px solid var(--cat-stopped);
  }
  .tone-manual {
    border-left: 3px solid var(--cat-manual);
  }
  .tone-unknown {
    border-left: 3px solid var(--cat-unknown);
  }
  .stale .value,
  .stale .unit {
    opacity: 0.55;
  }
</style>
