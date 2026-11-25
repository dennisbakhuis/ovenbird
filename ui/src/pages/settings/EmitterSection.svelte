<!--
  Emitter section: the three presets as choice cards, each with its curve drawn small and its
  maximum supply, then what switching would change (PresetDiff).
-->
<script lang="ts">
  import Pill from '$ui/Pill.svelte';
  import Card from '$ui/Card.svelte';
  import Field from '$components/settings/Field.svelte';
  import PresetDiff from '$components/settings/PresetDiff.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import { asCurve } from '$lib/core/curve';
  import { draft } from '$lib/core/draft.svelte';
  import { formatNumber } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import Segmented from '$ui/Segmented.svelte';
  import MiniCurve from '$components/settings/MiniCurve.svelte';

  interface Props {
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { schema, config }: Props = $props();
  const locale = $derived(settings.language);
  const current = $derived(String(config.fields['control_emitter']?.value ?? 'mixed'));
  const chosen = $derived(String(draft.value('control_emitter', config) ?? current));
  const options = $derived(schema.fields['control_emitter']?.options ?? []);
  const choices = $derived(
    options.map((value) => ({
      value,
      label: tOpt(`cfg.control_emitter.opt.${value}`) ?? value,
      testid: `emitter-${value}`,
    })),
  );
  const yRange = $derived.by<[number, number]>(() => {
    const waters = options.flatMap(
      (id) => asCurve(schema.presets[id]?.['control_curve'])?.map((p) => p[1]) ?? [],
    );
    return waters.length > 0
      ? [Math.floor(Math.min(...waters)) - 1, Math.ceil(Math.max(...waters)) + 1]
      : [20, 55];
  });
  const maxOf = (id: string) => {
    const v = schema.presets[id]?.['control_max_supply_c'];
    return typeof v === 'number' ? formatNumber(v, 0, locale) : '–';
  };
</script>

<Card bare as="div">
  <Field
    id="control_emitter"
    {schema}
    {config}
    {draft}
    wide
    helpTarget="settings/emitter.choose"
    errors={cfg.validation?.errors.filter((e) => e.field === 'control_emitter') ?? []}
    warnings={cfg.validation?.warnings.filter((e) => e.field === 'control_emitter') ?? []}
  >
    {#snippet editor(api)}
      <Segmented
        options={choices}
        value={chosen}
        onchange={(option) => api.set(option)}
        semantics="radio"
        appearance="cards"
        name="emitter"
        label={t('cfg.control_emitter.label')}
        disabled={api.disabled}
        itemClass="emitter-choice"
      >
        {#snippet option(item)}
          {@const curve = asCurve(schema.presets[item.value]?.['control_curve'])}
          <span class="title">
            {item.label}
            {#if item.value === current}<Pill tone="ok">{t('emitterInUse')}</Pill>{/if}
          </span>
          {#if curve}<span class="mini"><MiniCurve {curve} height={72} labels {yRange} /></span
            >{/if}
          <span class="caption">{t('overviewMaxSupply', { value: maxOf(item.value) })}</span>
        {/snippet}
      </Segmented>
    {/snippet}
  </Field>
</Card>
<PresetDiff {schema} {config} {current} {chosen} help="settings/emitter.diff" />

<style>
  .mini {
    margin-top: auto;
  }
  .title {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    font-weight: var(--fw-semibold);
  }
  @media (--narrow) {
    :global(.emitter-choice) {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 8.5rem;
      grid-template-areas:
        'title mini'
        'cap mini';
      align-items: center;
      padding: var(--space-2) var(--space-3);
    }
    :global(.emitter-choice.checked) {
      padding: calc(var(--space-2) - 1px) calc(var(--space-3) - 1px);
    }
    .title {
      grid-area: title;
    }
    .mini {
      grid-area: mini;
      margin-top: 0;
    }
    :global(.emitter-choice) .caption {
      grid-area: cap;
    }
  }
</style>
