<!--
  InsightCharts: the daily figures of the last 7 or 30 local days as bars: electricity and heat
  delivered, COP, compressor starts, running time, defrosts and degree-hours below the comfort
  band. Today is a lighter bar (still running). A day without data is a gap; a day with less than
  80 % coverage says so in its read-out.

  Props: none (loads api/v1/insight/daily itself). Renders nothing when the endpoint does not
  exist (older backend); a failed load shows one muted line.
  A11y: each chart is a Bars with a text summary and arrow-key read-out; the 7/30 switch is a
  pressed-button group.
-->
<script lang="ts">
  import Segmented from '$ui/Segmented.svelte';
  import Button from '$ui/Button.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    barItems,
    INSIGHT_SPANS,
    lastDays,
    partialIndex,
    runHours,
    totals,
    type InsightDay,
    type InsightSpan,
  } from '$lib/house/insight';
  import Bars from '$components/charts/Bars.svelte';
  import { SERIES, STATUS } from '$components/charts/palette';
  import Card from '$ui/Card.svelte';
  import Why from '$ui/Why.svelte';
  import { createInsight } from '$lib/house/useInsight.svelte';

  const insight = createInsight(30);
  $effect(() => insight.start());

  const PHONE_BLOCKS = ['electric', 'cop'];

  let span = $state<InsightSpan>(7);
  const spanOptions = $derived(
    INSIGHT_SPANS.map((option) => ({
      value: option,
      label: t(option === 7 ? 'insightSpan7' : 'insightSpan30'),
      testid: `insight-span-${option}`,
    })),
  );
  let showAll = $state(false);
  const lang = $derived(settings.language);
  const days = $derived(lastDays(insight.state.data?.days ?? [], span));
  const sums = $derived(totals(days));
  const today = $derived(partialIndex(days));
  const notes = $derived({
    partial: t('insightPartial'),
    coverage: (percent: number) => t('insightCoverage', { percent }),
  });

  interface Block {
    id: string;
    title: string;
    unit: string;
    digits: number;
    color: string;
    why?: string;
    pick: (day: InsightDay) => number | null;
  }

  const blocks: Block[] = $derived([
    {
      id: 'electric',
      title: t('insightElectric'),
      unit: 'kWh',
      digits: 1,
      color: SERIES.electric,
      pick: (d) => d.electric_kwh,
    },
    {
      id: 'heat',
      title: t('insightHeat'),
      unit: 'kWh',
      digits: 1,
      color: SERIES.heat,
      pick: (d) => d.heat_kwh,
    },
    {
      id: 'cop',
      title: t('insightCop'),
      unit: '',
      digits: 1,
      color: SERIES.outlet,
      why: t('insightCopWhy'),
      pick: (d) => d.cop,
    },
    {
      id: 'starts',
      title: t('insightStarts'),
      unit: '',
      digits: 0,
      color: SERIES.compressor,
      pick: (d) => d.compressor_starts,
    },
    {
      id: 'run',
      title: t('insightRun'),
      unit: t('insightRunUnit'),
      digits: 1,
      color: SERIES.neutral,
      pick: runHours,
    },
    {
      id: 'defrosts',
      title: t('insightDefrosts'),
      unit: '',
      digits: 0,
      color: SERIES.defrost,
      pick: (d) => d.defrosts,
    },
    {
      id: 'comfort',
      title: t('insightComfort'),
      unit: t('insightComfortUnit'),
      digits: 1,
      color: STATUS.warn,
      why: t('insightComfortWhy'),
      pick: (d) => d.below_comfort_kh,
    },
  ]);
</script>

{#if insight.state.phase !== 'missing'}
  <Card title={t('insightTitle')} icon="chart" testid="insight-card">
    {#snippet actions()}
      <Segmented
        options={spanOptions}
        value={span}
        onchange={(next) => (span = next)}
        label={t('insightSpanLabel')}
      />
    {/snippet}
    {#if insight.state.phase === 'loading'}
      <p class="muted">{t('insightLoading')}</p>
    {:else if insight.state.phase === 'failed'}
      <p class="muted" data-testid="insight-failed">{t('insightFailed')}</p>
    {:else if days.length === 0}
      <p class="muted">{t('insightEmpty')}</p>
    {:else}
      <div class="fit" class:all={showAll}>
        <div class="blocks" data-testid="insight-blocks" data-days={days.length}>
          {#each blocks as block (block.id)}
            <section
              class="block"
              class:extra={!PHONE_BLOCKS.includes(block.id)}
              data-testid="insight-{block.id}"
            >
              <h3>
                {block.title}{#if block.unit}<span class="unit"> {block.unit}</span>{/if}
                {#if block.why}<Why title={block.title}><p>{block.why}</p></Why>{/if}
              </h3>
              <Bars
                title={`${block.title} (${t(span === 7 ? 'insightSpan7' : 'insightSpan30')})`}
                items={barItems(days, block.pick, {
                  color: block.color,
                  language: lang,
                  notes,
                })}
                unit={block.unit}
                digits={block.digits}
                height={span === 7 ? 92 : 80}
                highlight={span === 7 ? today : null}
                min={0}
              />
            </section>
          {/each}
        </div>
        <Button
          class="insight-more"
          aria-expanded={showAll}
          data-testid="insight-show-all"
          onclick={() => (showAll = !showAll)}
        >
          {showAll
            ? t('insightShowFewer')
            : t('insightShowAll', { n: blocks.length - PHONE_BLOCKS.length })}
        </Button>
      </div>
      <p class="muted caption foot" data-testid="insight-note">
        {t('insightGapNote')}
        {#if sums.lowCoverageDays > 0}{t('insightGapCoverage', { days: sums.lowCoverageDays })}{/if}
      </p>
    {/if}
  </Card>
{/if}

<style>
  .fit {
    container: insight / inline-size;
  }
  .blocks {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 17rem), 1fr));
    gap: var(--space-3) var(--space-5);
  }
  :global(.insight-more) {
    display: none;
  }
  @container insight (max-width: 36rem) {
    .fit:not(.all) .extra {
      display: none;
    }
    :global(.insight-more) {
      display: inline-flex;
      margin-top: var(--space-3);
      min-height: var(--tap);
    }
  }
  .block {
    min-width: 0;
  }
  h3 {
    min-height: 2rem;
    margin: 0 0 var(--space-1);
    font-size: var(--fs-body);
    font-weight: var(--fw-semibold);
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }
  .unit {
    font-weight: var(--fw-regular);
  }
  .foot {
    margin: var(--space-3) 0 0;
  }
</style>
