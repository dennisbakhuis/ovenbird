<!--
  StatusLine: one line about the model in use: its name and age, and whether the learner can
  already trust it (credible) or still needs data. Shown above the cards of the Overview tab.

  Props: house (HouseInsight).
-->
<script lang="ts">
  import Pill from '$ui/Pill.svelte';
  import { clockNow, formatAge, formatDateTime } from '$lib/core/format';
  import type { HouseInsight } from '$lib/house/house';
  import { modelAgeDays } from '$lib/house/timeline';
  import { settings, t } from '$lib/core/settings.svelte';

  let { house }: { house: HouseInsight } = $props();

  const lang = $derived(settings.language);
  const age = $derived(modelAgeDays(house, clockNow()));
  const credible = $derived(house.credibility.credible);
  const stale = $derived(house.learner?.stale === true);
</script>

<p class="status" data-testid="house-status">
  <Pill tone={credible ? 'good' : 'warn'} testid="house-status-credible">
    {credible ? t('houseStatusCredible') : t('houseStatusLearning')}
  </Pill>
  <span data-testid="house-status-age">
    {#if age === null}
      {t('houseStatusModel', { model: house.model })}
    {:else if age === 0}
      {t('houseStatusToday', { model: house.model })}
    {:else}
      {t('houseStatusAge', { model: house.model, age: formatAge(age * 86400, lang) })}
    {/if}
    {#if house.champion}<span class="caption"
        >{formatDateTime(house.champion.promoted_at, lang)}</span
      >{/if}
  </span>
  {#if stale}<Pill tone="warn">{t('houseStatusStale')}</Pill>{/if}
</p>

<style>
  .status {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0 0 var(--space-3);
  }
</style>
