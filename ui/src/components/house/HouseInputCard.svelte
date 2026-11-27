<!--
  HouseInputCard: one subset of the house settings as a card on the House page. `facts` (Overview)
  is open only while there is no model yet (a new user fills it in while the learner waits) and
  collapsed otherwise, with the number of facts set. `bounds` (Model) stays collapsed (its summary counts the bounds set and says when a value ended
  at your limit) and opens with draft changes,
  says when the limits cost accuracy (`constraint_cost.worse`, both errors) and lists the values
  that ended at the model's own range in a details block; `learning` (Learning) is collapsed.
  Edits go into the settings draft and through the draft bar; a note says they apply at the next
  learner run.

  Props: subset, schema, config, house (the learned model, if any), changedSince (a stored change
  is newer than the model), prominent (open and full width), showRun.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatNumber } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import type { HouseInsight } from '$lib/house/house';
  import { BOUND_ROWS, FACT_FIELDS, SUBSET_GROUP, type Subset } from '$lib/house/settings';
  import { constraintSentence, structuralBounds } from '$lib/house/trust';
  import type { MessageKey } from '$lib/i18n';
  import HouseFields from './HouseFields.svelte';
  import PendingNote from './PendingNote.svelte';

  type CardSubset = Exclude<Subset, 'plan'>;

  interface Props {
    subset: CardSubset;
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

  const TEXT: Record<CardSubset, { title: MessageKey; subtitle: MessageKey; testid: string }> = {
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
    subset === 'facts' ? house === null : subset === 'bounds' ? inDraft > 0 : false,
  );
  const lang = $derived(settings.language);
  const num = (value: number, digits: number) => formatNumber(value, digits, lang);
  const worse = $derived(
    subset === 'bounds'
      ? constraintSentence(house?.validation, t, (value, digits = 1) => num(value, digits))
      : null,
  );
  const atLimit = $derived(
    subset === 'bounds' && (house?.at_bound ?? []).some((entry) => entry.kind === 'owner'),
  );
  const structural = $derived(subset === 'bounds' ? structuralBounds(house?.at_bound) : []);
  const meta = $derived(
    inDraft > 0
      ? t('groupChanged', { n: inDraft })
      : subset === 'facts'
        ? t('houseFactsSet', { n: factsSet })
        : subset === 'bounds'
          ? atLimit
            ? `${t('groupCount', { n: boundsSet })} · ${t('houseAtLimit')}`
            : t('groupCount', { n: boundsSet })
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
  {#if worse}
    <p class="worse" data-testid="house-constraint-worse">
      <Icon name="warning" size={16} />{worse}
    </p>
  {/if}
  <Details summary={t('houseFieldsToggle')} {meta} {open} testid="{text.testid}-details">
    <HouseFields {schema} {config} {subset} {house} flat explain={false} />
  </Details>
  {#if structural.length > 0}
    <Details
      summary={t('houseStructuralSummary')}
      meta={String(structural.length)}
      id="house-structural"
      testid="house-structural"
    >
      <p class="intro">{t('houseStructuralText')}</p>
      <ul class="structural" data-testid="house-structural-list">
        {#each structural as entry (entry.parameter)}
          <li>
            {t('houseStructuralRow', {
              name: tOpt(`houseParam_${entry.parameter}`) ?? entry.parameter,
              value: num(entry.value, 2),
              side: t(`houseSide_${entry.side}`),
              limit: num(entry.limit, 2),
            })}
          </li>
        {/each}
      </ul>
    </Details>
  {/if}
  <PendingNote {changedSince} {showRun} {onstarted} />
</Card>

<style>
  .intro {
    margin: 0 0 var(--space-2);
  }
  .worse {
    display: flex;
    gap: var(--space-2);
    margin: 0 0 var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-control);
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .structural {
    margin: 0;
    padding-left: var(--space-4);
    display: grid;
    gap: var(--space-1);
  }
</style>
