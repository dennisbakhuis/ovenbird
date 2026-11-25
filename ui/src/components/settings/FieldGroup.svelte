<!--
  FieldGroup: the fields of one or more schema groups. Basic fields are listed; advanced fields
  of each group sit in a collapsed "More: <group>" block. With `collapsed` and a `title`, the
  whole set (basic and advanced) goes into one collapsed block — groups by topic. `only` picks
  and orders explicit field ids. Collapsed blocks remember their state per device and show how
  many of their fields are changed.
-->
<script lang="ts">
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { fieldsOf } from '$lib/core/schema';
  import { t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import type { IconName } from '$lib/core/icons';
  import Details from '$ui/Details.svelte';
  import Field from './Field.svelte';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
    groups: string[];
    exclude?: string[];
    only?: string[];
    title?: string;
    icon?: IconName;
    collapsed?: boolean;
    headings?: boolean;
    testid?: string;
    helpTarget?: string | Record<string, string>;
  }

  let {
    schema,
    config,
    groups,
    exclude = [],
    only,
    title,
    icon,
    collapsed = false,
    headings = true,
    testid,
    helpTarget,
  }: Props = $props();

  const pick = (ids: string[]) =>
    (only ? only.filter((id) => ids.includes(id)) : ids).filter((id) => !exclude.includes(id));
  const basic = (group: string) => pick(fieldsOf(schema, [group], ['basic']));
  const advanced = (group: string) => pick(fieldsOf(schema, [group], ['advanced']));
  const all = $derived(pick(fieldsOf(schema, groups, ['basic', 'advanced'])));
  const changedOf = (ids: string[]) => ids.filter((id) => draft.has(id)).length;
  const meta = (ids: string[]) => {
    const n = changedOf(ids);
    return n > 0 ? t('groupChanged', { n }) : t('groupCount', { n: ids.length });
  };
  const groupTitle = (group: string) => tOpt(`group_${group}`) ?? group;
  const helpOf = (group: string) =>
    typeof helpTarget === 'string' ? helpTarget : helpTarget?.[group];
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

{#if collapsed && title}
  {#if all.length > 0}
    <div
      class="block"
      data-testid={testid ?? `group-${groups[0]}`}
      data-help={typeof helpTarget === 'string' ? helpTarget : undefined}
    >
      <Details
        summary={title}
        {icon}
        meta={meta(all)}
        id="settings.{testid ?? groups.join('-')}"
        testid="{testid ?? `group-${groups[0]}`}-details"
      >
        <div class="fields">
          {#each all as id (id)}{@render field(id)}{/each}
        </div>
      </Details>
    </div>
  {/if}
{:else}
  {#each groups as group (group)}
    {@const shown = basic(group)}
    {@const extra = advanced(group)}
    {#if shown.length > 0 || extra.length > 0}
      <section class="group" data-testid="group-{group}" data-help={helpOf(group)}>
        {#if headings && groups.length > 1 && shown.length > 0}
          <h3>{groupTitle(group)}</h3>
        {/if}
        {#if shown.length > 0}
          <div class="fields">
            {#each shown as id (id)}{@render field(id)}{/each}
          </div>
        {/if}
        {#if extra.length > 0}
          <div class="block">
            <Details
              summary={shown.length > 0
                ? t('groupMore', { group: groupTitle(group) })
                : groupTitle(group)}
              meta={meta(extra)}
              id="settings.adv.{group}"
              testid="advanced-{group}"
            >
              <div class="fields">
                {#each extra as id (id)}{@render field(id)}{/each}
              </div>
            </Details>
          </div>
        {/if}
      </section>
    {/if}
  {/each}
{/if}

<style>
  .group + .group:has(h3) {
    margin-top: var(--space-3);
  }
  .group h3 {
    margin: 0;
    padding-top: var(--space-2);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }
  .fields {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .block {
    border-top: 1px solid var(--border);
    padding-top: var(--space-1);
  }
  .group > .block:first-child,
  .block:first-child {
    border-top: none;
  }
  .block :global(.details .body) {
    padding-left: 1.6rem;
  }
  @media (--narrow) {
    .block :global(.details .body) {
      padding-left: 0;
    }
  }
</style>
