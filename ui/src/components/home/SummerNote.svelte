<!--
  SummerNote: one line on Home while the summer switch holds space heating off (with the slow
  outside mean) or is still collecting that mean. Renders nothing otherwise.
-->
<script lang="ts">
  import Icon from '$ui/Icon.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';

  let { ctl }: { ctl: ControlStore } = $props();

  const summer = $derived(ctl.control?.summer ?? null);
</script>

{#if summer?.enabled && (summer.active || summer.warming_up)}
  <p class="summer" data-testid="home-summer" data-active={summer.active}>
    <Icon name="sun" size={18} />
    {summer.active
      ? t('homeSummerActive', { mean: formatNumber(summer.mean_c ?? 0, 1, settings.language) })
      : t('homeSummerWarming')}
  </p>
{/if}

<style>
  .summer {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    margin: 0;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--muted);
  }
</style>
