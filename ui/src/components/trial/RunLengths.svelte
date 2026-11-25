<!--
  RunLengths: compressor run lengths of the last days as a histogram (Bars with its text summary),
  the key figures (runs, share under 20 min, median, longest, shortest pause), the short-run share
  of the trial against before, and a per-day table in a Details block.

  Props: runs (InsightRuns), shortShare ({ trial, baseline } | null), fmt (TrialFormat).
-->
<script lang="ts">
  import { formatDay } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { InsightRuns, TrialFormat } from '$lib/trial/trial';
  import Bars, { type BarItem } from '$components/charts/Bars.svelte';
  import { STATUS } from '$components/charts/palette';
  import Details from '$ui/Details.svelte';

  interface Props {
    runs: InsightRuns;
    shortShare: { trial: number | null; baseline: number | null } | null;
    fmt: TrialFormat;
  }

  let { runs, shortShare, fmt }: Props = $props();

  const total = $derived(runs.total);
  const items = $derived<BarItem[]>(
    total.histogram.map((bin) => ({
      label:
        bin.to_min === null
          ? t('trialRunsBinOpen', { from: bin.from_min })
          : t('trialRunsBin', { from: bin.from_min, to: bin.to_min }),
      value: bin.runs,
      color: bin.to_min !== null && bin.to_min <= runs.short_run_min ? STATUS.warn : undefined,
    })),
  );
  const minutes = (value: number | null) =>
    value === null ? '–' : fmt.duration(Math.round(value * 60));
  const figures = $derived([
    { id: 'count', label: t('trialRunsCount'), value: fmt.num(total.runs, 0) },
    {
      id: 'short',
      label: t('trialRunsShort', { min: fmt.num(runs.short_run_min, 0) }),
      value: total.short_share === null ? '–' : fmt.percent(total.short_share),
    },
    { id: 'median', label: t('trialRunsMedian'), value: minutes(total.median_min) },
    { id: 'longest', label: t('trialRunsLongest'), value: minutes(total.longest_min) },
    { id: 'off', label: t('trialRunsMinOff'), value: minutes(total.min_off_min) },
  ]);
</script>

<p class="lead muted">{t('trialRunsLead', { days: runs.days.length })}</p>
{#if total.runs === 0}
  <p class="muted" data-testid="trial-runs-none">{t('trialRunsNone')}</p>
{:else}
  <dl class="figures">
    {#each figures as figure (figure.id)}
      <div data-testid="runs-{figure.id}">
        <dt>{figure.label}</dt>
        <dd>{figure.value}</dd>
      </div>
    {/each}
  </dl>
  <Bars title={t('trialRunsChart')} {items} digits={0} height={90} min={0} />
{/if}
{#if shortShare && shortShare.trial !== null && shortShare.baseline !== null}
  <p class="compare" data-testid="trial-short-compare">
    {t('trialRunsCompare', {
      trial: fmt.percent(shortShare.trial),
      baseline: fmt.percent(shortShare.baseline),
    })}
  </p>
{/if}
{#if runs.days.length > 0}
  <Details summary={t('trialRunsPerDay')} id="trial-runs-days" testid="trial-runs-days">
    <table>
      <thead>
        <tr>
          <th scope="col">{t('trialRunsDay')}</th>
          <th scope="col" class="num">{t('trialRunsCount')}</th>
          <th scope="col" class="num"
            >{t('trialRunsShort', { min: fmt.num(runs.short_run_min, 0) })}</th
          >
          <th scope="col" class="num">{t('trialRunsMedian')}</th>
        </tr>
      </thead>
      <tbody>
        {#each runs.days as day (day.date)}
          <tr>
            <th scope="row">{formatDay(day.from, settings.language)}</th>
            <td class="num">{fmt.num(day.runs, 0)}</td>
            <td class="num">{day.short_share === null ? '–' : fmt.percent(day.short_share)}</td>
            <td class="num">{minutes(day.median_min)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </Details>
{/if}

<style>
  .lead {
    margin: 0 0 var(--space-2);
    font-size: var(--fs-caption);
  }
  .figures {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(6.5rem, 1fr));
    gap: var(--space-2) var(--space-3);
    margin: 0 0 var(--space-2);
  }
  .figures div {
    min-width: 0;
  }
  dt {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  dd {
    margin: 0;
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
  .compare {
    margin: var(--space-2) 0;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th,
  td {
    padding: 0.3rem var(--space-2) 0.3rem 0;
    text-align: left;
    font-weight: var(--fw-regular);
  }
  thead th {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  @container main (max-width: 40rem) {
    .lead {
      display: none;
    }
  }
</style>
