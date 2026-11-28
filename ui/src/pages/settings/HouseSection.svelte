<!--
  House section: the facts about the house, the same fields the House page shows, and a link to
  that page.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import HouseFields from '$components/house/HouseFields.svelte';
  import Icon from '$ui/Icon.svelte';
  import { buildHash } from '$lib/core/router.svelte';
  import { t, tOpt } from '$lib/core/settings.svelte';
  import { FACTS_GROUP } from '$lib/house/settings';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  let { schema, config }: { schema: ConfigSchema; config: ConfigDoc } = $props();
</script>

<Card bare as="div" class="stack" data-help="settings/house.area" data-testid="house-section">
  <section class="subset" data-testid="house-subset-facts" data-help="settings/house.facts">
    <h3>{tOpt(`group_${FACTS_GROUP}`)}</h3>
    <HouseFields {schema} {config} />
  </section>
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
