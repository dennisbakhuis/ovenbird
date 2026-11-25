<!--
  House section: the heated floor area, which turns the learned heat loss into the indicative
  insulation score on the House page, and a link to that page.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import FieldGroup from '$components/settings/FieldGroup.svelte';
  import Icon from '$ui/Icon.svelte';
  import { buildHash } from '$lib/core/router.svelte';
  import { t } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  let { schema, config }: { schema: ConfigSchema; config: ConfigDoc } = $props();
</script>

<Card bare as="div" class="stack" data-help="settings/house.area" data-testid="house-section">
  <FieldGroup {schema} {config} groups={['house']} />
  <p class="muted link">
    {t('houseSectionText')}
    <a href={buildHash('house')} data-testid="house-section-link"
      >{t('houseSectionLink')}<Icon name="chevronRight" size={16} /></a
    >
  </p>
</Card>

<style>
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
