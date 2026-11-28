<!--
  HouseInputCard: the facts about the house as a card on the House page. Open while no fact is
  set (a new user fills it in), collapsed otherwise with the number of facts set. Edits go into the
  settings draft and through the draft bar.

  Props: schema, config.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { t } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import { FACTS_GROUP, FACT_FIELDS, anyFactSet } from '$lib/house/settings';
  import HouseFields from './HouseFields.svelte';

  let { schema, config }: { schema: ConfigSchema; config: ConfigDoc } = $props();

  const factsSet = $derived(
    FACT_FIELDS.filter((id) => {
      const value = config.fields[id]?.value;
      return value !== null && value !== undefined;
    }).length,
  );
  const inDraft = $derived(
    Object.keys(draft.changes).filter((id) => schema.fields[id]?.group === FACTS_GROUP).length,
  );
  const open = $derived(!anyFactSet(config));
  const meta = $derived(
    inDraft > 0 ? t('groupChanged', { n: inDraft }) : t('houseFactsSet', { n: factsSet }),
  );
</script>

<Card
  title={t('houseFactsInputTitle')}
  subtitle={t('houseFactsInputSubtitle')}
  icon="home"
  testid="house-facts-input"
  help="house.inputs"
  span={12}
>
  {#if open}
    <p class="intro" data-testid="house-facts-intro">{t('houseFactsInputIntro')}</p>
  {/if}
  <Details summary={t('houseFieldsToggle')} {meta} {open} testid="house-facts-input-details">
    <HouseFields {schema} {config} flat />
  </Details>
</Card>

<style>
  .intro {
    margin: 0 0 var(--space-2);
  }
</style>
