<!--
  RunCard: the learner that fits the house model. Its state in plain words (idle with the next run,
  running since, switched off, or not built into this install), the last run with its outcome,
  time and duration, the last failure and its reason, and "Run now". After a start the card asks
  the service every 5 s until the learner is idle again, then tells the page to reload. Without the
  endpoint (an older service) the card is not shown.

  With a model it also says how the model fared at the last check against newer data ("still
  good" or "no longer trusted because …") and lists the data notes of the run.

  Props: credibility (what a "not enough data yet" run still misses), waiting (the page has no
  model yet), revalidation (the latest check of the model in use), warnings (data notes),
  onsettled (called when a run finished).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Pill from '$ui/Pill.svelte';
  import { clockNow, formatDateTime, formatDuration } from '$lib/core/format';
  import { buildHash } from '$lib/core/router.svelte';
  import { learningNeeds, needsText, type Credibility, type Revalidation } from '$lib/house/house';
  import { failingGates, revalidationErrors, revalidationSentence } from '$lib/house/trust';
  import {
    FAILURE_KEYS,
    OUTCOME_KEYS,
    RUN_POLL_MS,
    fetchRun,
    outcomeKind,
    presentation,
    refusalOf,
    startRun,
    type HouseRun,
  } from '$lib/house/run';
  import { formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';

  interface Props {
    credibility?: Credibility | null;
    waiting?: boolean;
    revalidation?: Revalidation | null;
    warnings?: string[];
    onsettled?: () => void;
  }

  let {
    credibility = null,
    waiting = false,
    revalidation = null,
    warnings = [],
    onsettled,
  }: Props = $props();

  const lang = $derived(settings.language);
  let run = $state<HouseRun | null>(null);
  let absent = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);

  const kind = $derived(run ? presentation(run, clockNow()) : null);
  const running = $derived(run?.state === 'running');
  const last = $derived(run?.last ?? null);
  const outcome = $derived(last ? outcomeKind(last.outcome) : null);
  const needs = $derived(outcome === 'learning' ? learningNeeds(credibility) : []);
  const revalTrusted = $derived(
    revalidation !== null && revalidation.credible && failingGates(revalidation).length === 0,
  );
  const revalErrors = $derived(
    revalidation
      ? revalidationErrors(revalidation, t, (value, digits = 1) =>
          formatNumber(value, digits, lang),
        )
      : null,
  );
  const interval = $derived(run ? formatDuration(run.interval_h * 3600, lang) : '');
  const when = (iso: string | null | undefined) => formatDateTime(iso ?? null, lang);

  async function refresh(): Promise<void> {
    try {
      const next = await fetchRun();
      if (next === null) {
        absent = true;
        return;
      }
      const wasRunning = run?.state === 'running';
      run = next;
      absent = false;
      if (wasRunning && next.state !== 'running') onsettled?.();
    } catch {
      return;
    }
  }

  $effect(() => {
    void refresh();
  });

  $effect(() => {
    if (!running) return;
    const timer = window.setInterval(() => void refresh(), RUN_POLL_MS);
    return () => window.clearInterval(timer);
  });

  async function start(): Promise<void> {
    busy = true;
    error = null;
    try {
      run = await startRun();
    } catch (failure) {
      const refusal = refusalOf(failure);
      error = t(`houseRunRefused_${refusal}`);
      if (refusal === 'learner_running' || refusal === 'learner_unavailable') await refresh();
    }
    busy = false;
  }
</script>

{#if !absent && run}
  <Card
    title={t('houseRunTitle')}
    subtitle={t('houseRunSubtitle')}
    icon="clock"
    testid="house-run"
    help="house.run"
    span={12}
  >
    <div class="body">
      <p class="state" data-testid="run-state" data-kind={kind}>
        {#if kind === 'running'}
          <Pill tone="info">{t('houseRunPill_running')}</Pill>
          {t('houseRunRunning', { time: when(run.started_at) })}
        {:else if kind === 'unavailable'}
          <Pill tone="neutral">{t('houseRunPill_unavailable')}</Pill>
          {t('houseRunUnavailable')}
        {:else if kind === 'disabled'}
          <Pill tone="neutral">{t('houseRunPill_disabled')}</Pill>
          {t('houseRunDisabled')}
          <a href={buildHash('settings', ['house'])} data-testid="run-settings-link"
            >{t('houseRunSettingsLink')}</a
          >
        {:else if kind === 'due_soon'}
          <Pill tone="good">{t('houseRunPill_idle')}</Pill>
          {t('houseRunDue')}
        {:else if kind === 'scheduled'}
          <Pill tone="good">{t('houseRunPill_idle')}</Pill>
          {t('houseRunNext', { time: when(run.next_due_at), every: interval })}
        {:else}
          <Pill tone="good">{t('houseRunPill_idle')}</Pill>
          {t('houseRunNever', { every: interval })}
        {/if}
      </p>

      {#if last}
        <dl class="facts" data-testid="run-last">
          <div>
            <dt>{t('houseRunLast')}</dt>
            <dd data-testid="run-outcome" data-outcome={outcome}>
              {t(OUTCOME_KEYS[outcome ?? 'other'])}
              {#if last.message}<span class="caption">{last.message}</span>{/if}
            </dd>
          </div>
          <div>
            <dt>{t('houseRunWhen')}</dt>
            <dd>
              {when(last.at)}{#if last.runtime_s !== null}
                <span class="caption"
                  >{t('houseRunTook', { time: formatDuration(last.runtime_s, lang) })}</span
                >{/if}
            </dd>
          </div>
        </dl>
      {:else if kind !== 'unavailable'}
        <p class="muted" data-testid="run-never">{t('houseRunNone')}</p>
      {/if}

      {#if outcome === 'learning'}
        <p class="note" data-testid="run-learning">
          {#if credibility}
            {needsText(needs, t, (value, digits) => formatNumber(value, digits ?? 0, lang))}
          {:else}
            {t('houseRunLearning')}
          {/if}
        </p>
      {/if}

      {#if revalidation}
        <div class="reval" data-testid="house-revalidation" data-credible={revalidation.credible}>
          <p>
            <Pill tone={revalTrusted ? 'good' : 'warn'} testid="house-revalidation-pill"
              >{revalTrusted ? t('houseStatusTrusted') : t('houseStatusLearning')}</Pill
            >
            <span data-testid="house-revalidation-text"
              >{revalidationSentence(revalidation, t, when(revalidation.at))}</span
            >
          </p>
          {#if revalErrors}
            <p class="caption">{revalErrors} {t(`houseRevalSource_${revalidation.source}`)}</p>
          {/if}
        </div>
      {/if}

      {#if warnings.length > 0}
        <InlineMessage tone="warn" icon size="md" testid="house-data-warnings">
          <strong>{t('houseWarningsTitle')}</strong>
          {#each warnings as warning (warning)}<span class="detail">{warning}</span>{/each}
        </InlineMessage>
      {/if}

      {#if waiting && kind !== 'unavailable'}
        <p class="note" data-testid="run-expect">{t('houseRunExpect')}</p>
      {/if}

      {#if run.failure}
        <InlineMessage tone="warn" icon size="md" testid="run-failure">
          {t('houseRunFailed', {
            time: when(run.failure.at),
            reason: t(FAILURE_KEYS[run.failure.reason] ?? 'houseRunFailure_exit'),
          })}
          {#if run.failure.detail}<span class="detail">{run.failure.detail}</span>{/if}
        </InlineMessage>
      {/if}

      <ActionRow>
        <Button
          type="button"
          variant="primary"
          disabled={running || run.state === 'unavailable'}
          {busy}
          onclick={start}
          data-testid="run-now"
        >
          {t('houseRunNow')}
        </Button>
        {#if running}
          <span class="caption" role="status">{t('houseRunWorking')}</span>
        {/if}
      </ActionRow>
      {#if error}<InlineMessage tone="error" size="md" testid="run-error">{error}</InlineMessage
        >{/if}
    </div>
  </Card>
{/if}

<style>
  .body {
    display: grid;
    gap: var(--space-3);
  }
  p {
    margin: 0;
  }
  .state {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .reval {
    display: grid;
    gap: var(--space-1);
  }
  .reval p {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .facts {
    display: grid;
    gap: var(--space-2);
    margin: 0;
  }
  .facts dt {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .facts dd {
    margin: 0;
  }
  .facts .caption,
  .detail {
    display: block;
  }
  .detail {
    font-size: var(--fs-caption);
    overflow-wrap: anywhere;
  }
</style>
