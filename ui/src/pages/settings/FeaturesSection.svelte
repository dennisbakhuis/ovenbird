<!--
  Features section: one card per optional feature, each with its own on/off switch, so what
  ovenbird does is a choice. The state pills come from `GET control/features` and follow the
  saved configuration; the switches edit the draft like every other setting.
-->
<script lang="ts">
  import FeatureCard from '$components/settings/FeatureCard.svelte';
  import { fetchDayShift, fetchFeatures } from '$lib/core/api';
  import { poll } from '$lib/core/poll.svelte';
  import { t } from '$lib/core/settings.svelte';
  import { entryOf, FEATURES } from '$lib/settings/features';
  import type { ConfigDoc, ConfigSchema, DayShift, FeatureEntry } from '$lib/core/types';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { schema, config }: Props = $props();

  const split = Math.ceil(FEATURES.length / 2);
  const columns = [FEATURES.slice(0, split), FEATURES.slice(split)];

  let entries = $state<FeatureEntry[] | null>(null);
  let dayshift = $state<DayShift | null>(null);

  $effect(() => {
    void config.version;
    return poll(
      async (signal) => {
        try {
          entries = (await fetchFeatures(signal)).features;
        } catch {
          if (!signal.aborted) entries = null;
        }
      },
      { intervalMs: 15_000 },
    );
  });

  $effect(() => {
    void config.version;
    return poll(
      async (signal) => {
        try {
          dayshift = await fetchDayShift(signal);
        } catch {
          if (!signal.aborted) dayshift = null;
        }
      },
      { intervalMs: 60_000 },
    );
  });
</script>

<div class="features" data-testid="settings-features">
  <p class="intro">{t('settingsFeaturesIntro')}</p>
  <p class="legend muted" data-testid="features-legend">{t('featuresLegend')}</p>
  {#if entries === null}
    <p class="muted" data-testid="features-no-status">{t('featuresNoStatus')}</p>
  {/if}
  <div class="cards">
    {#each columns as column, index (index)}
      <div class="column" data-testid="features-column">
        {#each column as spec (spec.id)}
          <FeatureCard {spec} {schema} {config} entry={entryOf(entries, spec.id)} {dayshift} />
        {/each}
      </div>
    {/each}
  </div>
</div>

<style>
  .features {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  p {
    margin: 0;
  }
  .legend {
    font-size: var(--fs-caption);
  }
  .cards {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .column {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    min-width: 0;
  }
  @container main (min-width: 64rem) {
    .cards {
      flex-direction: row;
      align-items: flex-start;
    }
    .column {
      flex: 1 1 0;
    }
  }
</style>
