<!--
  HouseFields: the facts about the house (build period, floor area, volume, windows, occupants),
  shared by the House page and Settings → House. Every field is the schema-driven Field bound to
  the one settings draft, so an edit here goes through the same review and apply bar as in
  Settings. Advanced fields sit behind a "More" block unless `flat` shows everything.

  Props: schema, config, flat.
-->
<script lang="ts">
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { fieldsOf } from '$lib/core/schema';
  import { t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import { FACTS_GROUP } from '$lib/house/settings';
  import Details from '$ui/Details.svelte';
  import Field from '$components/settings/Field.svelte';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
    flat?: boolean;
  }

  let { schema, config, flat = false }: Props = $props();

  const group = FACTS_GROUP;
  const basic = $derived(fieldsOf(schema, [group], ['basic']));
  const advanced = $derived(fieldsOf(schema, [group], ['advanced']));
  const shown = $derived(flat ? [...basic, ...advanced] : basic);
  const more = $derived(flat ? [] : advanced);
  const moreChanged = $derived(more.filter((id) => draft.has(id)).length);
  const moreMeta = $derived(
    moreChanged > 0 ? t('groupChanged', { n: moreChanged }) : t('groupCount', { n: more.length }),
  );
  const groupTitle = $derived(tOpt(`group_${group}`) ?? group);
</script>

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
  />
{/snippet}

<div class="set" data-testid="house-fields-facts">
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
</style>
