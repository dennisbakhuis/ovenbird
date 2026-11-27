<!--
  House section: the facts about the house (the heated floor area turns the learned heat loss
  into the indicative insulation score), the bounds on what is learned and the learning settings,
  the same fields the House page shows, and a link to that page.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import HouseFields from '$components/house/HouseFields.svelte';
  import Icon from '$ui/Icon.svelte';
  import { buildHash } from '$lib/core/router.svelte';
  import { t, tOpt } from '$lib/core/settings.svelte';
  import { SUBSET_GROUP, type Subset } from '$lib/house/settings';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  let { schema, config }: { schema: ConfigSchema; config: ConfigDoc } = $props();

  const SUBSETS: Subset[] = ['facts', 'bounds', 'learning'];
  const present = (subset: Subset) =>
    Object.values(schema.fields).some((def) => def.group === SUBSET_GROUP[subset]);
</script>

<Card bare as="div" class="stack" data-help="settings/house.area" data-testid="house-section">
  {#each SUBSETS.filter(present) as subset (subset)}
    <section class="subset" data-testid="house-subset-{subset}" data-help="settings/house.{subset}">
      <h3>{tOpt(`group_${SUBSET_GROUP[subset]}`)}</h3>
      <HouseFields {schema} {config} {subset} />
    </section>
  {/each}
  <p class="muted link">
    {t('houseSectionText')}
    <a href={buildHash('house')} data-testid="house-section-link"
      >{t('houseSectionLink')}<Icon name="chevronRight" size={16} /></a
    >
  </p>
</Card>

<style>
  .subset {
    display: grid;
    gap: var(--space-2);
  }
  .subset h3 {
    margin: 0;
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }
  .link {
    margin: 0;
  }
  a {
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    font-weight: var(--fw-medium);
  }
</style>
