<!--
  Data section: how long the history is kept, as four presets (Short, Standard, Long, Unlimited)
  with the database size each would reach, a fifth "Custom" card when the values match none of
  them, the yearly archive switch, and the five retention fields under "Advanced" (open by
  default for a custom combination). Sizes and downloads live on System → Data; the link goes
  there.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import Field from '$components/settings/Field.svelte';
  import { fetchStorage } from '$lib/core/api';
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { buildHash } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema, HistoryStorage, RetentionPreset } from '$lib/core/types';
  import { formatBytes } from '$lib/system/data';
  import {
    PRESET_IDS,
    RETENTION_FIELDS,
    matchPreset,
    presetChanges,
    presetTable,
    type PresetChoice,
  } from '$lib/system/retention';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { schema, config }: Props = $props();

  const ARCHIVE_FIELD = 'history_archive_enabled';

  let storage = $state<HistoryStorage | null>(null);

  $effect(() => {
    const controller = new AbortController();
    fetchStorage(controller.signal)
      .then((body) => (storage = body))
      .catch(() => undefined);
    return () => controller.abort();
  });

  const lang = $derived(settings.language);
  const table = $derived(presetTable(storage?.presets));
  const values = $derived(
    Object.fromEntries(RETENTION_FIELDS.map((field) => [field, draft.value(field, config)])),
  );
  const chosen = $derived(matchPreset(values, table));
  const active = $derived(storage?.preset ?? null);
  const locked = $derived(RETENTION_FIELDS.some((field) => config.fields[field]?.locked));
  const hasArchive = $derived(ARCHIVE_FIELD in schema.fields);
  const options = $derived([
    ...PRESET_IDS.map((value) => ({
      value: value as PresetChoice,
      label: t(`preset_${value}`),
      testid: `preset-radio-${value}`,
    })),
    ...(chosen === 'custom'
      ? [
          {
            value: 'custom' as PresetChoice,
            label: t('preset_custom'),
            testid: 'preset-radio-custom',
            disabled: true,
          },
        ]
      : []),
  ]);
  let advanced = $state(untrack(() => chosen === 'custom'));

  const sizeOf = (id: PresetChoice) => storage?.presets?.find((item) => item.id === id) ?? null;
  const yearSize = (preset: RetentionPreset) =>
    (preset.projected_bytes ?? 0) + (preset.growth_bytes_per_year ?? 0);

  function choose(id: PresetChoice): void {
    if (id === 'custom' || locked) return;
    for (const [field, days] of Object.entries(presetChanges(id, config, table)))
      draft.set(field, days, config);
  }

  const issues = (id: string) => ({
    errors: (cfg.validation?.errors ?? []).filter((e) => e.field === id),
    warnings: (cfg.validation?.warnings ?? []).filter((e) => e.field === id),
  });
</script>

<p class="intro" data-testid="data-section-intro" data-help="system/data.retention">
  {t('dataSectionText')}
  <a href={buildHash('system', ['data'])} data-testid="data-section-link"
    >{t('dataSectionLink')}<Icon name="chevronRight" size={16} /></a
  >
</p>

<Card bare as="div" testid="data-section">
  <fieldset class="presets" data-help="system/data.retention" data-testid="retention-presets">
    <legend>{t('retentionChoose')}</legend>
    <Segmented
      {options}
      value={chosen}
      onchange={choose}
      semantics="radio"
      appearance="cards"
      name="retention-preset"
      label={t('retentionChoose')}
      disabled={locked}
      itemClass="preset-choice"
    >
      {#snippet option(item)}
        {@const size = sizeOf(item.value)}
        <span class="title" data-testid="preset-{item.value}">
          {item.label}
          {#if item.value === active}<Pill tone="ok">{t('emitterInUse')}</Pill>{/if}
        </span>
        <span class="caption text">{t(`presetText_${item.value}`)}</span>
        {#if item.value !== 'custom'}
          <span class="caption size" data-testid="preset-size-{item.value}">
            {#if size?.projected_bytes}
              <span>{t('presetSize', { size: formatBytes(yearSize(size), lang) })}</span>
              {#if size.growth_bytes_per_year}
                <span class="muted"
                  >{t('presetGrowth', {
                    size: formatBytes(size.growth_bytes_per_year, lang),
                  })}</span
                >
              {/if}
            {:else}
              {t('presetNoSize')}
            {/if}
          </span>
        {/if}
      {/snippet}
    </Segmented>
    {#if locked}<p class="caption muted">{t('presetLocked')}</p>{/if}
  </fieldset>

  {#if hasArchive}
    <Field id={ARCHIVE_FIELD} {schema} {config} {draft} {...issues(ARCHIVE_FIELD)} />
  {/if}

  <Details summary={t('retentionAdvanced')} bind:open={advanced} testid="retention-advanced">
    {#each RETENTION_FIELDS as id (id)}
      {#if id in schema.fields}
        <Field {id} {schema} {config} {draft} {...issues(id)} />
      {/if}
    {/each}
  </Details>
</Card>

<style>
  .intro {
    margin: 0 0 var(--space-3);
    color: var(--muted);
  }
  .intro a {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    white-space: nowrap;
  }
  .presets {
    border: 0;
    margin: 0 0 var(--space-3);
    padding: 0;
    min-width: 0;
  }
  legend {
    padding: 0;
    margin-bottom: var(--space-2);
    font-weight: var(--fw-semibold);
  }
  .presets p {
    margin: var(--space-2) 0 0;
  }
  .title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1);
    font-weight: var(--fw-semibold);
  }
  .text {
    color: var(--muted);
  }
  .size {
    margin-top: auto;
    display: grid;
    font-variant-numeric: tabular-nums;
  }
</style>
