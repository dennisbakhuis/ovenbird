<!--
  HouseInputCard: one subset of the house settings as a card on the House page. `facts` (Overview)
  sits open and first while there is no model or no fact is set, so a new user can fill it in
  while the learner waits, and collapses once a model exists and a fact is set. `bounds` (Model)
  opens when a bound is set; `learning` (Learning) is collapsed. Edits go into the settings draft
  and through the draft bar; a note says they apply at the next learner run.

  Props: subset, schema, config, house (the learned model, if any), changedSince (a stored change
  is newer than the model), prominent (open and full width), showRun.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { t } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import type { HouseInsight } from '$lib/house/house';
  import {
    BOUND_ROWS,
    FACT_FIELDS,
    SUBSET_GROUP,
    anyFactSet,
    type Subset,
  } from '$lib/house/settings';
  import type { MessageKey } from '$lib/i18n';
  import HouseFields from './HouseFields.svelte';
  import PendingNote from './PendingNote.svelte';

  interface Props {
    subset: Subset;
    schema: ConfigSchema;
    config: ConfigDoc;
    house?: HouseInsight | null;
    changedSince?: boolean;
    showRun?: boolean;
    onstarted?: () => void;
  }

  let {
    subset,
    schema,
    config,
    house = null,
    changedSince = false,
    showRun = true,
    onstarted,
  }: Props = $props();

  const TEXT: Record<Subset, { title: MessageKey; subtitle: MessageKey; testid: string }> = {
    facts: {
      title: 'houseFactsInputTitle',
      subtitle: 'houseFactsInputSubtitle',
      testid: 'house-facts-input',
    },
    bounds: {
      title: 'houseBoundsTitle',
      subtitle: 'houseBoundsSubtitle',
      testid: 'house-bounds-card',
    },
    learning: {
      title: 'houseLearningSettingsTitle',
      subtitle: 'houseLearningSettingsHint',
      testid: 'house-learning-settings',
    },
  };

  const text = $derived(TEXT[subset]);
  const isSet = (id: string) => {
    const value = config.fields[id]?.value;
    return value !== null && value !== undefined;
  };
  const factsSet = $derived(FACT_FIELDS.filter(isSet).length);
  const boundsSet = $derived(BOUND_ROWS.flatMap((row) => [row.min, row.max]).filter(isSet).length);
  const inDraft = $derived(
    Object.keys(draft.changes).filter((id) => schema.fields[id]?.group === SUBSET_GROUP[subset])
      .length,
  );
  const open = $derived(
    subset === 'facts'
      ? house === null || !anyFactSet(config)
      : subset === 'bounds'
        ? boundsSet > 0
        : false,
  );
  const meta = $derived(
    inDraft > 0
      ? t('groupChanged', { n: inDraft })
      : subset === 'facts'
        ? t('groupCount', { n: factsSet })
        : subset === 'bounds'
          ? t('groupCount', { n: boundsSet })
          : undefined,
  );
</script>

<Card
  title={t(text.title)}
  subtitle={t(text.subtitle)}
  icon={subset === 'learning' ? 'clock' : 'home'}
  testid={text.testid}
  help="house.{subset === 'facts' ? 'inputs' : subset}"
  span={12}
>
  {#if subset === 'facts' && house === null}
    <p class="intro" data-testid="house-facts-intro">{t('houseFactsInputIntro')}</p>
  {/if}
  {#if subset === 'bounds'}
    <p class="intro" data-testid="bounds-explain">{t('houseBoundsExplain')}</p>
  {/if}
  <Details summary={t('houseFieldsToggle')} {meta} {open} testid="{text.testid}-details">
    <HouseFields {schema} {config} {subset} {house} flat explain={false} />
  </Details>
  <PendingNote {changedSince} {showRun} {onstarted} />
</Card>

<style>
  .intro {
    margin: 0 0 var(--space-2);
  }
</style>
