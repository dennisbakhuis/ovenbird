<!--
  Criteria: the cut-over criteria side by side, the trial period against the same length before
  it: value, value before, difference, the rule and the status (word and icon), with the periods
  and one line on the trial: "met" only for a completed trial from go-live; "No trial yet",
  "Trial running: 0.4 of 7 days" or "ended early" otherwise.

  Props: summary (TrialSummary), fmt (TrialFormat).
  A11y: a table with a caption; statuses are words.
-->
<script lang="ts">
  import { t, tc, tOpt } from '$lib/core/settings.svelte';
  import {
    criterionDelta,
    criterionValue,
    type CriterionStatus,
    type TrialCriterion,
    type TrialFormat,
    type TrialSummary,
    trialVerdict,
  } from '$lib/trial/trial';
  import Pill from '$ui/Pill.svelte';

  let { summary, fmt }: { summary: TrialSummary; fmt: TrialFormat } = $props();

  const TONE = { ok: 'good', fail: 'bad', info: 'neutral', unknown: 'neutral' } as const;
  const ICON = { ok: 'check', fail: 'critical', info: 'info', unknown: 'info' } as const;

  const span = (from: string, to: string) => `${fmt.date(from)} – ${fmt.date(to)}`;

  function rule(criterion: TrialCriterion): string {
    const limit = criterion.limit === null ? '–' : fmt.num(criterion.limit, 1);
    switch (criterion.id) {
      case 'room_mean':
        return t('trialRule_room_mean', { limit });
      case 'short_runs':
        return t('trialRule_short_runs');
      case 'pump_errors':
        return t('trialRule_pump_errors');
      case 'writes_per_day':
        return t('trialRule_writes_per_day', { limit });
      default:
        return t('trialRule_info');
    }
  }
  const statusText = (value: CriterionStatus) => t(`trialCriterionStatus_${value}`);
  const verdict = $derived(trialVerdict(summary, fmt));
</script>

<p class="lead muted">
  {t('trialCriteriaLead', {
    trial: span(summary.trial.from, summary.trial.to),
    baseline: span(summary.baseline.from, summary.baseline.to),
  })}
  <span class="source">{t(`trialCriteriaSource_${summary.source}`)}</span>
</p>
<div class="scroll">
  <table data-testid="trial-criteria">
    <caption class="visually-hidden">{t('trialCriteriaTitle')}</caption>
    <thead>
      <tr>
        <th scope="col">{t('trialColCriterion')}</th>
        <th scope="col" class="num">{t('trialColTrial')}</th>
        <th scope="col" class="num">{t('trialColBaseline')}</th>
        <th scope="col" class="wide">{t('trialColRule')}</th>
        <th scope="col">{t('trialColStatus')}</th>
      </tr>
    </thead>
    <tbody>
      {#each summary.criteria as criterion (criterion.id)}
        {@const delta = criterionDelta(criterion.id, criterion.delta, fmt)}
        <tr data-criterion={criterion.id}>
          <th scope="row">
            {tc('trialCriterion_', criterion.id)}
            {#if criterion.status !== 'info'}<span class="narrow caption muted"
                >{rule(criterion)}</span
              >{/if}
          </th>
          <td class="num"
            >{criterionValue(criterion.id, criterion.trial, fmt)}{#if delta}<span
                class="delta caption muted">{delta}</span
              >{/if}</td
          >
          <td class="num">{criterionValue(criterion.id, criterion.baseline, fmt)}</td>
          <td class="wide muted">{rule(criterion)}</td>
          <td>
            <Pill tone={TONE[criterion.status]} icon={ICON[criterion.status]}
              >{statusText(criterion.status)}</Pill
            >
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
<p
  class="met tone-{verdict.tone}"
  data-testid="trial-criteria-met"
  data-state={verdict.state}
  data-met={verdict.key === 'trialCriteriaMet'}
>
  {tOpt(verdict.key, verdict.params) ?? verdict.key}
</p>

<style>
  .lead {
    margin: 0 0 var(--space-2);
    font-size: var(--fs-caption);
  }
  .scroll {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th,
  td {
    padding: 0.4rem var(--space-2) 0.4rem 0;
    text-align: left;
    vertical-align: top;
  }
  thead th {
    color: var(--muted);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
  }
  tbody th {
    font-weight: var(--fw-semibold);
  }
  .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .delta {
    display: block;
  }
  .narrow {
    display: none;
    font-weight: var(--fw-regular);
  }
  .met {
    margin: var(--space-2) 0 0;
    font-weight: var(--fw-semibold);
  }
  .met.tone-warn {
    color: var(--status-limited);
  }
  .met.tone-good {
    color: var(--status-ok);
  }
  .met.tone-neutral {
    color: var(--muted);
  }
  @container main (max-width: 40rem) {
    .wide {
      display: none;
    }
    .narrow {
      display: block;
    }
    .source {
      display: none;
    }
    th,
    td {
      padding-right: 0.35rem;
    }
  }
</style>
