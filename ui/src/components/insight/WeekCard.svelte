<!--
  WeekCard: the compact "This week" card on Home: electricity, COP, compressor starts and
  degree-hours below the comfort band over the last 7 days, daily electricity as small bars, and a
  link to the full set on the Pump page. Hidden while loading, on a failed load and when the
  endpoint does not exist (older backend).

  Props: none (loads api/v1/insight/daily?days=7 itself).
  On a narrow card only the four figures show (the bars are on Pump).
  A11y: the bars have a text summary; the four figures are a list.
-->
<script lang="ts">
  import { formatNumber } from '$lib/core/format';
  import { barItems, lastDays, partialIndex, totals } from '$lib/house/insight';
  import { settings, t } from '$lib/core/settings.svelte';
  import Bars from '$components/charts/Bars.svelte';
  import { SERIES } from '$components/charts/palette';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import { createInsight } from './useInsight.svelte';

  const insight = createInsight(7);
  $effect(() => insight.start());

  const lang = $derived(settings.language);
  const days = $derived(lastDays(insight.state.data?.days ?? [], 7));
  const sums = $derived(totals(days));
  const num = (value: number | null, digits = 1) =>
    value === null ? '–' : formatNumber(value, digits, lang);
  const notes = $derived({
    partial: t('insightPartial'),
    coverage: (percent: number) => t('insightCoverage', { percent }),
  });
  const figures = $derived([
    { id: 'energy', label: t('insightWeekEnergy'), value: num(sums.electricKwh), unit: 'kWh' },
    { id: 'cop', label: t('insightWeekCop'), value: num(sums.cop), unit: '' },
    { id: 'starts', label: t('insightWeekStarts'), value: num(sums.starts, 0), unit: '' },
    {
      id: 'below',
      label: t('insightWeekBelow'),
      value: num(sums.belowKh),
      unit: t('insightComfortUnit'),
    },
  ]);
</script>

{#if insight.state.phase === 'ok' && days.length > 0}
  <Card
    title={t('insightWeekTitle')}
    icon="chart"
    href="#/pump"
    linkLabel={t('insightMore')}
    testid="insight-week"
  >
    {#snippet actions()}
      <a class="house" href="#/house" data-testid="week-house-link"
        ><Icon name="home" size={16} />{t('weekHouseLink')}</a
      >
    {/snippet}
    <div class="body">
      <ul class="figures">
        {#each figures as figure (figure.id)}
          <li data-testid="week-{figure.id}">
            <span class="label muted caption">{figure.label}</span>
            <span class="value"
              >{figure.value}{#if figure.unit}<span class="unit"> {figure.unit}</span>{/if}</span
            >
          </li>
        {/each}
      </ul>
      <div class="bars">
        <Bars
          title={`${t('insightElectric')} (${t('insightWeekDays', { n: days.length })})`}
          items={barItems(days, (d) => d.electric_kwh, {
            color: SERIES.electric,
            language: lang,
            notes,
          })}
          unit="kWh"
          height={84}
          highlight={partialIndex(days)}
          min={0}
        />
      </div>
    </div>
  </Card>
{/if}

<style>
  .body {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
    gap: var(--space-4);
    align-items: center;
  }
  .house {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: 24px;
    padding: var(--space-1) 0;
    margin: -0.25rem 0;
    font-size: var(--fs-body);
    font-weight: var(--fw-medium);
    text-decoration: none;
  }
  .house:hover {
    text-decoration: underline;
  }
  .figures {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-2) var(--space-3);
  }
  .figures li {
    display: grid;
    min-width: 0;
  }
  .value {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
  .unit {
    font-size: var(--fs-caption);
    margin-left: 0.2em;
    font-weight: var(--fw-regular);
    color: var(--muted);
  }
  @container (max-width: 30rem) {
    .body {
      grid-template-columns: 1fr;
    }
    .figures {
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .bars {
      display: none;
    }
  }
</style>
