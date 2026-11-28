<!--
  Trial: the go-live checklist from live facts, the trial against the same length before it on the
  cut-over criteria, compressor run lengths, and Release control (rehearse or hand back to the
  other controller). Each part loads on its own; an older service without an endpoint gets a calm
  line instead of that part. Nothing is started automatically.
-->
<script lang="ts">
  import { poll } from '$lib/core/poll.svelte';
  import { untrack } from 'svelte';
  import Card from '$ui/Card.svelte';
  import Checklist from '$components/trial/Checklist.svelte';
  import Criteria from '$components/trial/Criteria.svelte';
  import ReleaseCard from '$components/trial/ReleaseCard.svelte';
  import RunLengths from '$components/trial/RunLengths.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    fetchRelease,
    fetchRuns,
    fetchSnapshotState,
    fetchTrialStatus,
    trialFormat,
    type InsightRuns,
    type ReleaseState,
    type SnapshotResponse,
    type TrialStatus,
  } from '$lib/trial/trial';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  type Part<T> = { phase: 'loading' } | { phase: 'failed' } | { phase: 'ok'; data: T | null };

  const REFRESH_MS = 60_000;
  const RUN_DAYS = 7;

  let status = $state<Part<TrialStatus>>({ phase: 'loading' });
  let runs = $state<Part<InsightRuns>>({ phase: 'loading' });
  let snapshot = $state<Part<SnapshotResponse>>({ phase: 'loading' });
  let release = $state<Part<ReleaseState>>({ phase: 'loading' });
  let reloads = $state(0);

  const fmt = $derived(trialFormat(settings.language, live.clock));

  async function load<T>(
    fetcher: (signal: AbortSignal) => Promise<T | null>,
    signal: AbortSignal,
    set: (part: Part<T>) => void,
    keep: boolean,
  ): Promise<void> {
    try {
      const data = await fetcher(signal);
      if (!signal.aborted) set({ phase: 'ok', data });
    } catch {
      if (!signal.aborted && !keep) set({ phase: 'failed' });
    }
  }

  $effect(() => {
    void reloads;
    return poll(
      (signal) =>
        untrack(() =>
          Promise.all([
            load(fetchTrialStatus, signal, (p) => (status = p), status.phase === 'ok'),
            load(
              (s) => fetchRuns(RUN_DAYS, s),
              signal,
              (p) => (runs = p),
              runs.phase === 'ok',
            ),
            load(fetchSnapshotState, signal, (p) => (snapshot = p), snapshot.phase === 'ok'),
          ]),
        ),
      { intervalMs: REFRESH_MS },
    );
  });

  $effect(() => {
    const controller = new AbortController();
    void load(fetchRelease, controller.signal, (p) => (release = p), false);
    return () => controller.abort();
  });

  const summary = $derived(status.phase === 'ok' ? (status.data?.summary ?? null) : null);
  const shortShare = $derived.by(() => {
    const criterion = summary?.criteria.find((c) => c.id === 'short_runs');
    return criterion ? { trial: criterion.trial, baseline: criterion.baseline } : null;
  });
</script>

<p class="page-lead muted">{t('trialLead')}</p>

<div class="grid">
  <div class="span-7 stack">
    <Card
      title={t('trialChecklistTitle')}
      icon="check"
      testid="trial-checklist-card"
      help="system/trial.checklist"
    >
      {#if status.phase === 'loading'}
        <p class="muted">{t('trialLoading')}</p>
      {:else if status.phase === 'failed'}
        <p class="muted">{t('trialFailed')}</p>
      {:else if status.data === null}
        <p class="muted" data-testid="trial-missing">{t('trialMissing')}</p>
      {:else}
        <Checklist status={status.data} {fmt} />
      {/if}
    </Card>

    <Card
      title={t('trialCriteriaTitle')}
      icon="chart"
      testid="trial-criteria-card"
      help="system/trial.criteria"
    >
      {#if status.phase === 'loading'}
        <p class="muted">{t('loading')}</p>
      {:else if summary === null}
        <p class="muted">{t('trialCriteriaMissing')}</p>
      {:else}
        <Criteria {summary} {fmt} />
      {/if}
    </Card>
  </div>

  <div class="span-5 stack">
    <Card
      title={t('trialReleaseTitle')}
      icon="undo"
      testid="trial-release-card"
      help="system/trial.release"
    >
      {#if snapshot.phase === 'loading' || release.phase === 'loading'}
        <p class="muted">{t('loading')}</p>
      {:else}
        <ReleaseCard
          {ctl}
          snapshot={snapshot.phase === 'ok' ? snapshot.data : null}
          release={release.phase === 'ok' ? release.data : null}
          {fmt}
          onchanged={() => (reloads += 1)}
        />
      {/if}
    </Card>

    <Card
      title={t('trialRunsTitle')}
      icon="clock"
      testid="trial-runs-card"
      help="system/trial.runs"
    >
      {#if runs.phase === 'loading'}
        <p class="muted">{t('loading')}</p>
      {:else if runs.phase === 'failed' || runs.data === null}
        <p class="muted" data-testid="trial-runs-missing">{t('trialRunsMissing')}</p>
      {:else}
        <RunLengths runs={runs.data} {shortShare} {fmt} />
      {/if}
    </Card>
  </div>
</div>

<style>
  .page-lead {
    margin: 0 0 var(--space-3);
    max-width: 60rem;
  }
  @container main (max-width: 40rem) {
    .page-lead {
      display: none;
    }
  }
</style>
