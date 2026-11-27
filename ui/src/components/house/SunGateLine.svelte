<!--
  SunGateLine: one read-only line for the Control tab: whether the model's sun response is trusted,
  and if not yet, the first plain reason. The controller's model plan uses the sun response, so
  the line sits next to the card that explains the plan.

  Props: house (HouseInsight).
-->
<script lang="ts">
  import { formatNumber } from '$lib/core/format';
  import type { HouseInsight } from '$lib/house/house';
  import { gateReasons } from '$lib/house/trust';
  import { settings, t } from '$lib/core/settings.svelte';
  import Pill from '$ui/Pill.svelte';

  let { house }: { house: HouseInsight } = $props();

  const lang = $derived(settings.language);
  const gate = $derived(house.gates?.sun);
  const reason = $derived(
    gateReasons(
      gate,
      t,
      (value, digits = 1) => formatNumber(value, digits, lang),
      house,
    )[0]?.replace(/\.$/, ''),
  );
</script>

{#if gate}
  <p class="line" data-testid="house-sun-line" data-ok={gate.ok}>
    <Pill tone={gate.ok ? 'good' : 'warn'} testid="house-sun-line-pill">
      {gate.ok ? t('houseGateOk') : t('houseGateNotYet')}
    </Pill>
    <span data-testid="house-sun-line-text">
      {#if gate.ok}
        {t('houseSunLineOk')}
      {:else if reason}
        {t('houseSunLineNot', { reason })}
      {:else}
        {t('houseSunLineNotPlain')}
      {/if}
    </span>
    <span class="caption">{t('houseSunLineUse')}</span>
  </p>
{/if}

<style>
  .line {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }
</style>
