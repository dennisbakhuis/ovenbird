<!--
  HouseFields: the house settings, in three subsets that Settings → House and the House page share.
  `facts` (what you know about the house), `bounds` (pin or limit what the model learns, with
  the learned value and its 90 % range beside the minimum and maximum) and `learning` (how the
  learner fits, with the left-out days). Every field is the schema-driven Field bound to the one
  settings draft, so an edit here goes through the same review and apply bar as in Settings.
  Advanced fields sit behind a "More" block unless `flat` shows everything.

  Props: schema, config, subset, house (the learned model, for the bounds), flat, explain (the
  sentence on pinning above the bounds; the House card shows it itself).
-->
<script lang="ts">
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatNumber } from '$lib/core/format';
  import { fieldsOf } from '$lib/core/schema';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import type { HouseInsight } from '$lib/house/house';
  import {
    BOUND_ROWS,
    EXCLUDED_DAYS,
    SUBSET_GROUP,
    isPinned,
    learnedOf,
    type Subset,
  } from '$lib/house/settings';
  import Details from '$ui/Details.svelte';
  import Pill from '$ui/Pill.svelte';
  import Field, { type EditorApi } from '$components/settings/Field.svelte';
  import ExcludedDaysEditor from './ExcludedDaysEditor.svelte';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
    subset: Subset;
    house?: HouseInsight | null;
    flat?: boolean;
    explain?: boolean;
  }

  let { schema, config, subset, house = null, flat = false, explain = true }: Props = $props();

  const group = $derived(SUBSET_GROUP[subset]);
  const lang = $derived(settings.language);
  const num = (value: number, digits: number) =>
    formatNumber(value, digits, lang).replace('-', '−');
  const basic = $derived(fieldsOf(schema, [group], ['basic']));
  const advanced = $derived(fieldsOf(schema, [group], ['advanced']));
  const shown = $derived(flat ? [...basic, ...advanced] : basic);
  const more = $derived(flat ? [] : advanced);
  const listed = $derived(subset === 'bounds' ? advanced : more);
  const moreChanged = $derived(listed.filter((id) => draft.has(id)).length);
  const moreMeta = $derived(
    moreChanged > 0 ? t('groupChanged', { n: moreChanged }) : t('groupCount', { n: listed.length }),
  );
  const groupTitle = $derived(tOpt(`group_${group}`) ?? group);
  const bounds = $derived(
    BOUND_ROWS.filter((row) => schema.fields[row.min] && schema.fields[row.max]),
  );
</script>

{#snippet days(api: EditorApi)}
  <ExcludedDaysEditor
    days={api.value}
    onchange={(next) => api.set(next)}
    disabled={api.disabled}
    invalid={api.invalid}
    max={schema.fields[EXCLUDED_DAYS]?.max_items}
  />
{/snippet}

{#snippet field(id: string)}
  <Field
    {id}
    {schema}
    {config}
    {draft}
    signals={cfg.signals}
    signalsState={cfg.signalsState}
    errors={(cfg.validation?.errors ?? []).filter((e) => e.field === id)}
    warnings={(cfg.validation?.warnings ?? []).filter((e) => e.field === id)}
    editor={id === EXCLUDED_DAYS ? days : undefined}
    wide={id === EXCLUDED_DAYS}
  />
{/snippet}

{#snippet boundRows()}
  <div class="bounds" data-testid="house-fields-bounds">
    {#if explain}<p class="explain" data-testid="bounds-explain">{t('houseBoundsExplain')}</p>{/if}
    {#each bounds as row (row.id)}
      {@const learned = learnedOf(house, row.id)}
      {@const pinned = isPinned(draft.value(row.min, config), draft.value(row.max, config))}
      <section class="quantity" data-testid="bound-{row.id}">
        <div class="title">
          <h3>{t(`houseBound_${row.id}`)}</h3>
          {#if pinned}<Pill tone="info" testid="bound-pinned-{row.id}"
              >{t('houseBoundsPinned')}</Pill
            >{/if}
        </div>
        <p class="learned muted" data-testid="bound-learned-{row.id}">
          {#if learned === null}
            {t('houseBoundsNoModel')}
          {:else if learned.interval}
            {t('houseBoundsLearned', {
              value: num(learned.value, row.digits),
              unit: row.unit,
              lo: num(learned.interval[0], row.digits),
              hi: num(learned.interval[1], row.digits),
            })}
          {:else}
            {t('houseBoundsLearnedPlain', {
              value: num(learned.value, row.digits),
              unit: row.unit,
            })}
          {/if}
        </p>
        <div class="fields">
          {@render field(row.min)}
          {@render field(row.max)}
        </div>
      </section>
    {/each}
  </div>
{/snippet}

{#if subset === 'bounds'}
  {#if flat}
    {@render boundRows()}
  {:else}
    <Details
      summary={t('houseFieldsToggle')}
      meta={moreMeta}
      id="settings.adv.{group}"
      testid="advanced-{group}"
    >
      {@render boundRows()}
    </Details>
  {/if}
{:else}
  <div class="set" data-testid="house-fields-{subset}">
    {#if shown.length > 0}
      <div class="fields">
        {#each shown as id (id)}{@render field(id)}{/each}
      </div>
    {/if}
    {#if more.length > 0}
      <div class="more">
        <Details
          summary={shown.length > 0 ? t('groupMore', { group: groupTitle }) : groupTitle}
          meta={moreMeta}
          id="settings.adv.{group}"
          testid="advanced-{group}"
        >
          <div class="fields">
            {#each more as id (id)}{@render field(id)}{/each}
          </div>
        </Details>
      </div>
    {/if}
  </div>
{/if}

<style>
  .fields {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .more {
    border-top: 1px solid var(--border);
    padding-top: var(--space-1);
  }
  .more:first-child {
    border-top: none;
  }
  .bounds {
    display: grid;
    gap: var(--space-4);
  }
  .explain,
  .learned {
    margin: 0;
  }
  .quantity {
    display: grid;
    gap: var(--space-1);
    min-width: 0;
  }
  .title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  h3 {
    margin: 0;
    font-size: var(--fs-body);
  }
</style>
