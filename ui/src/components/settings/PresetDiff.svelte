<!--
  PresetDiff: what switching the emitter preset does. Only the values that will change are
  drawn (curve as old/new overlay, numbers as from → to chips); values you set yourself are
  kept and listed collapsed; for the preset in use, a one-line count with the full list
  collapsed.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import { sameValue } from '$lib/core/draft.svelte';
  import { formatValue } from '$lib/core/fieldFormat';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import Details from '$ui/Details.svelte';
  import DiffTable from './DiffTable.svelte';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
    current: string;
    chosen: string;
    help?: string;
  }

  let { schema, config, current, chosen, help }: Props = $props();

  const locale = $derived(settings.language);
  const words = $derived({
    on: t('on'),
    off: t('off'),
    none: t('fieldNone'),
    forever: t('retentionForeverValue'),
  });
  const show = (field: string, value: unknown) =>
    formatValue(schema.fields[field], value, locale, words);
  const name = (field: string) => tOpt(`cfg.${field}.label`) ?? field;
  const presetName = (id: string) => tOpt(`cfg.control_emitter.opt.${id}`) ?? id;

  const rows = $derived(
    Object.entries(schema.presets[chosen] ?? {}).map(([field, preset]) => {
      const known = config.fields[field];
      const following = known?.source === 'preset' || known?.source === 'default';
      const nowValue = known?.value;
      return {
        field,
        now: nowValue,
        preset,
        keeps: !following,
        changes: following && !sameValue(nowValue, preset),
      };
    }),
  );
  const changes = $derived(rows.filter((r) => r.changes));
  const kept = $derived(rows.filter((r) => r.keeps && !sameValue(r.now, r.preset)));
  const same = $derived(rows.length - changes.length - kept.length);
  const order = (field: string) =>
    field === 'control_curve' ? 0 : schema.fields[field]?.tier === 'expert' ? 2 : 1;
  const entries = $derived(
    [...changes]
      .sort((a, b) => order(a.field) - order(b.field))
      .map((r) => ({ field: r.field, from: r.now, to: r.preset })),
  );
</script>

<Card
  bare
  class="preset-diff"
  data-testid="preset-diff"
  data-help={help}
  aria-labelledby="preset-title"
>
  <h3 id="preset-title">
    <Icon name={chosen === current ? 'check' : 'arrowRight'} size={18} />
    {chosen === current
      ? t('presetInUse', { preset: presetName(chosen) })
      : t('presetSwitchTo', { preset: presetName(chosen) })}
  </h3>
  {#if chosen === current}
    <p class="muted" data-testid="preset-summary">
      {t('presetSameSummary', { n: rows.length - kept.length, kept: kept.length })}
    </p>
  {:else}
    <p data-testid="preset-summary">
      {t('presetWillChange', { n: changes.length })}
      {#if kept.length > 0}<span class="muted">{t('presetKeptCount', { n: kept.length })}</span
        >{/if}
    </p>
    {#if entries.length > 0}
      <DiffTable {entries} {schema} />
    {/if}
  {/if}

  {#if kept.length > 0}
    <Details summary={t('presetKeptTitle')} meta={kept.length} icon="hand" testid="preset-kept">
      <ul class="list">
        {#each kept as row (row.field)}
          <li>
            <span>{name(row.field)}</span>
            <span class="vals"
              ><strong>{show(row.field, row.now)}</strong>
              <span class="muted">{t('presetInstead', { value: show(row.field, row.preset) })}</span
              ></span
            >
          </li>
        {/each}
      </ul>
    </Details>
  {/if}
  {#if chosen === current || same > 0}
    <Details
      summary={chosen === current ? t('presetAllTitle') : t('presetSameTitle')}
      meta={chosen === current ? rows.length : same}
      icon="settings"
      testid="preset-all"
    >
      <ul class="list">
        {#each rows.filter((r) => chosen === current || (!r.changes && !kept.includes(r))) as row (row.field)}
          <li>
            <span>{name(row.field)}</span>
            <span class="vals">{show(row.field, row.preset)}</span>
          </li>
        {/each}
      </ul>
    </Details>
  {/if}
</Card>

<style>
  :global(.preset-diff) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  h3 {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0;
    font-size: var(--fs-emph);
  }
  h3 :global(.icon) {
    color: var(--accent);
  }
  p {
    margin: 0;
  }
  p .muted {
    margin-left: 0.35rem;
  }
  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: var(--fs-body);
  }
  .list li {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.1rem var(--space-3);
    padding: 0.3rem 0;
    border-bottom: 1px solid var(--border);
  }
  .list li:last-child {
    border-bottom: none;
  }
  .vals {
    font-variant-numeric: tabular-nums;
    text-align: right;
    overflow-wrap: anywhere;
    min-width: 0;
  }
  .vals .muted {
    margin-left: 0.35rem;
    font-size: var(--fs-caption);
  }
</style>
