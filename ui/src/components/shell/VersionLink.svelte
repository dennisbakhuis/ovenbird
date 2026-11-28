<!--
  VersionLink: the service version as a small muted link ("v0.6.0") to System → Overview, where
  the About card is. The slot keeps its width while the version is still unknown, so the link
  fades in without moving anything; nothing is shown until the version arrives.

  Props: version (from `health`; null while unknown), testid, prefix (show "ovenbird" before the
  number).
-->
<script lang="ts">
  import { buildHash } from '$lib/core/router.svelte';
  import { t } from '$lib/core/settings.svelte';

  interface Props {
    version: string | null;
    testid: string;
    prefix?: boolean;
  }

  let { version, testid, prefix = false }: Props = $props();

  const label = $derived(version === null ? '' : `v${version}`);
</script>

<span class="slot" class:prefix data-testid="{testid}-slot">
  {#if version !== null}
    <a
      class="version"
      href={buildHash('system')}
      title={t('aboutTitle')}
      aria-label={t('menuVersion', { version: label })}
      data-testid={testid}
      >{#if prefix}<span class="name">{t('appName')}</span>{/if}{label}</a
    >
  {/if}
</span>

<style>
  .slot {
    display: inline-flex;
    align-items: center;
    min-width: 6.5ch;
    min-height: 1.5em;
    font-size: var(--fs-caption);
    font-variant-numeric: tabular-nums;
    line-height: 1.5;
  }
  .slot.prefix {
    min-width: 15ch;
  }
  .version {
    color: var(--muted);
    text-decoration: none;
    white-space: nowrap;
    animation: version-in 0.2s ease-out;
  }
  .version:hover {
    color: var(--text);
    text-decoration: underline;
  }
  .name {
    margin-right: 0.35em;
  }
  @keyframes version-in {
    from {
      opacity: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .version {
      animation: none;
    }
  }
</style>
