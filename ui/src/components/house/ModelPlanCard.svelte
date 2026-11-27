<!--
  ModelPlanCard: how the controller uses the learned house model. A switch with three positions
  (off, shadow, on) that edits `control_model_use` through the shared settings draft; what the
  planner would do or does now, built from the numbers; why it may not act (most important
  reason first); the computed shift of the last 7 days as a step chart with the allowed range as
  a band, applied stretches solid and shadow-only stretches dashed; the bounds in one line with
  the advanced settings in a collapsed block; and an honest note on what can go wrong.

  Props: control (GET insight/house/control), schema, config (null while they load).
  A11y: the chart's role="img" summary is the sentence under it.
-->
<script lang="ts">
  import { SERIES } from '$components/charts/palette';
  import TimeChart, { type PanelSpec } from '$components/charts/TimeChart.svelte';
  import Field from '$components/settings/Field.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import { clockNow, formatDateTime } from '$lib/core/format';
  import { formatNum } from '$lib/core/chartSummary';
  import { draft } from '$lib/core/draft.svelte';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import {
    effectSentence,
    planLines,
    planSummarySentence,
    shiftSentence,
    sortBlocks,
    summarisePlan,
  } from '$lib/house/plan';
  import type { HouseControl, ModelUse } from '$lib/house/shapes';
  import { issueText } from '$lib/settings/issues';
  import type { MessageKey } from '$lib/i18n';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Pill from '$ui/Pill.svelte';
  import Segmented from '$ui/Segmented.svelte';

  interface Props {
    control: HouseControl;
    schema: ConfigSchema | null;
    config: ConfigDoc | null;
  }

  let { control, schema, config }: Props = $props();

  const USE = 'control_model_use';
  const ADVANCED = [
    'control_model_max_setback_k',
    'control_model_max_preheat_k',
    'control_model_horizon_h',
    'control_model_max_rmse_k',
  ] as const;
  const USES: ModelUse[] = ['off', 'shadow', 'on'];
  const DAY_MS = 86_400_000;

  const lang = $derived(settings.language);
  const tr = (key: MessageKey, params?: Record<string, string | number>) => t(key, params);
  const editable = $derived(schema !== null && config !== null && USE in schema.fields);
  const chosen = $derived.by((): ModelUse => {
    const value = config && draft.has(USE) ? draft.value(USE, config) : control.use;
    return value === 'shadow' || value === 'on' || value === 'off' ? value : control.use;
  });
  const issues = $derived((cfg.validation?.errors ?? []).filter((issue) => issue.field === USE));
  const issueDef = $derived(schema?.fields[USE]);

  const options = $derived(
    USES.map((use) => ({
      value: use,
      label: t(`houseCtlUseShort_${use}` as MessageKey),
      testid: `house-control-use-${use}`,
    })),
  );
  const tone = $derived(
    control.use === 'on' ? 'good' : control.use === 'shadow' ? 'info' : 'neutral',
  );

  const blocks = $derived(sortBlocks(control.verdict.blocks));
  const blockText = (code: string) =>
    tOpt(`houseCtlBlock_${code}`, {
      rmse: control.model_rmse_k === null ? '–' : formatNum(control.model_rmse_k, 2, lang),
      max: formatNum(control.bounds.max_rmse_k, 2, lang),
    }) ?? t('houseCtlBlockUnknown', { code });

  const shift = $derived(shiftSentence(control, tr, lang));
  const effect = $derived(effectSentence(control, tr, lang));
  const summary = $derived(summarisePlan(control.history));
  const days = $derived(
    Math.max(
      1,
      Math.round((Date.parse(control.history.to) - Date.parse(control.history.from)) / DAY_MS),
    ),
  );
  const sentence = $derived(planSummarySentence(summary, days, tr, lang));
  const from = $derived(Date.parse(control.history.from));
  const to = $derived(Date.parse(control.history.to));
  const lines = $derived(planLines(control.history));
  const down = $derived(control.bounds.max_setback_k);
  const up = $derived(control.bounds.max_preheat_k);

  const panels = $derived<PanelSpec[]>([
    {
      id: 'shift',
      unit: 'K',
      height: 110,
      digits: 1,
      min: -Math.max(down, 0.1) - 0.1,
      max: Math.max(up, 0.1) + 0.1,
      zero: true,
      bands: [
        {
          id: 'bounds',
          label: t('houseCtlBand'),
          color: SERIES.neutral,
          upper: up,
          lower: -down,
          opacity: 0.14,
        },
      ],
      rules: [{ value: 0 }],
      lines: [
        {
          id: 'computed',
          label: t('houseCtlComputed'),
          color: SERIES.forecast,
          dash: '4 3',
          step: true,
          width: 1.5,
          points: lines.computed,
        },
        {
          id: 'applied',
          label: t('houseCtlApplied'),
          color: SERIES.setpoint,
          step: true,
          width: 2.5,
          points: lines.applied,
        },
      ],
    },
  ]);

  const evaluatedAt = $derived(
    control.now ? formatDateTime(control.now.at, lang, clockNow()) : null,
  );
  const advancedChanged = $derived(ADVANCED.filter((id) => draft.has(id)).length);
  const advancedMeta = $derived(
    advancedChanged > 0
      ? t('groupChanged', { n: advancedChanged })
      : t('groupCount', { n: ADVANCED.length }),
  );
  const advanced = $derived(schema ? ADVANCED.filter((id) => id in schema.fields) : []);
</script>

{#snippet field(id: string)}
  {#if schema && config}
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
  {/if}
{/snippet}

<Card
  title={t('houseCtlTitle')}
  subtitle={t('houseCtlSubtitle')}
  icon="target"
  testid="house-control"
  help="house.control"
  span={12}
>
  <div class="use">
    <Pill {tone} testid="house-control-pill">{t(`houseCtlUse_${control.use}` as MessageKey)}</Pill>
    <p data-testid="house-control-meaning">{t(`houseCtlMeaning_${control.use}` as MessageKey)}</p>
  </div>

  {#if editable}
    <div class="switch">
      <Segmented
        {options}
        value={chosen}
        onchange={(value) => config && draft.set(USE, value, config)}
        label={t('houseCtlSwitchLabel')}
        appearance="joined"
        size="sm"
        testid="house-control-use"
      />
      <p class="muted hint" data-testid="house-control-locked">
        {t('houseCtlLocked')}
        {t('houseCtlDraftHint')}
      </p>
      {#each issues as issue (issue.code + issue.message)}
        <InlineMessage tone="error" icon testid="house-control-error">
          {issueText(issue, issueDef, tOpt)}
        </InlineMessage>
      {/each}
    </div>
  {/if}

  <section class="block" aria-labelledby="house-control-now" data-testid="house-control-now">
    <h3 id="house-control-now">{t('houseCtlNowTitle')}</h3>
    <p class="shift" data-testid="house-control-shift">{shift}</p>
    {#if effect}<p data-testid="house-control-effect">{effect}</p>{/if}
    {#if evaluatedAt}<p class="muted caption" data-testid="house-control-at">
        {t('houseCtlEvaluated', { when: evaluatedAt })}
      </p>{/if}
  </section>

  <section class="block" aria-labelledby="house-control-blocks" data-testid="house-control-blocks">
    <h3 id="house-control-blocks">{t('houseCtlBlocksTitle')}</h3>
    {#if blocks.length === 0}
      <p data-testid="house-control-ready">{t('houseCtlReady')}</p>
    {:else}
      <ul class="reasons">
        {#each blocks as code (code)}
          <li data-testid="house-control-block-{code}">{blockText(code)}</li>
        {/each}
      </ul>
    {/if}
    {#if control.model}
      <p class="muted caption" data-testid="house-control-model">
        {t('houseCtlModelLine', {
          model: control.model,
          rmse: control.model_rmse_k === null ? '–' : formatNum(control.model_rmse_k, 2, lang),
        })}
      </p>
    {/if}
  </section>

  <section class="block" aria-labelledby="house-control-chart" data-testid="house-control-history">
    <h3 id="house-control-chart">{t('houseCtlChartTitle')}</h3>
    {#if summary.evaluated > 0}
      <TimeChart
        {from}
        {to}
        {panels}
        title={t('houseCtlChartTitle')}
        summary={sentence}
        maxGapMs={control.history.step_s * 1500}
        legend="chips"
      />
      <p class="muted caption">{t('houseCtlChartNote')}</p>
    {/if}
    <p data-testid="house-control-summary">{sentence}</p>
  </section>

  <p class="bounds" data-testid="house-control-bounds">
    {t('houseCtlBounds', {
      down: formatNum(down, 1, lang),
      up: formatNum(up, 1, lang),
      h: control.bounds.horizon_h,
    })}
  </p>
  {#if advanced.length > 0}
    <Details
      summary={t('houseCtlAdvanced')}
      meta={advancedMeta}
      id="house.control.advanced"
      testid="house-control-advanced"
    >
      <div class="fields">
        {#each advanced as id (id)}{@render field(id)}{/each}
      </div>
    </Details>
  {/if}

  <section class="note" data-testid="house-control-note">
    <h3>{t('houseCtlNoteTitle')}</h3>
    <p>{t('houseCtlNote')}</p>
  </section>
</Card>

<style>
  .use {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2) var(--space-3);
  }
  .use p,
  .switch p,
  .block p,
  .bounds,
  .note p {
    margin: 0;
  }
  .switch {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-3);
    justify-items: start;
  }
  .hint {
    max-width: 48rem;
  }
  .block {
    display: grid;
    gap: var(--space-2);
    margin-top: var(--space-4);
    min-width: 0;
  }
  h3 {
    margin: 0;
    font-size: var(--fs-body);
  }
  .shift {
    font-weight: var(--fw-semibold);
  }
  .reasons {
    margin: 0;
    padding-left: var(--space-4);
    display: grid;
    gap: var(--space-1);
  }
  .bounds {
    margin-top: var(--space-4);
  }
  .fields {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .note {
    display: grid;
    gap: var(--space-1);
    margin-top: var(--space-4);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border);
  }
</style>
