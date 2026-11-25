<!--
  ReleaseCard: Release control. What the go-live snapshot holds, what a release does, and two
  admin actions: "Rehearse" (a simple confirmation) and "Release control now" (type a word to
  confirm), both with an optional reason. Before go-live (Shadow, paused) an admin can capture
  the pump state by hand and "Rehearse without sending": a plan of what a hand-back would send,
  shown like a run, that sends and pauses nothing. While a release runs it polls the service every 1.5 s
  and shows each item's progress and the elapsed time against the 5-minute target; when it is done
  it shows the outcome and the next steps to hand back to the previous controller. Nothing starts by itself.

  Props: ctl, snapshot (SnapshotResponse | null for an older service), release (ReleaseState
  | null), onchanged() (after a release finished: reload the checklist).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import { onMount, tick } from 'svelte';
  import { ApiError, failureKind } from '$lib/core/api';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { formatDuration, formatNumber } from '$lib/core/format';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import {
    captureSnapshot,
    confirmMatches,
    elapsedSeconds,
    fetchRelease,
    itemPhase,
    RELEASE_TARGET_S,
    releaseCounts,
    startRelease,
    targetShare,
    type ReleaseRun,
    type ReleaseState,
    type SnapshotResponse,
    type TrialFormat,
  } from '$lib/trial/trial';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';

  interface Props {
    ctl: ControlStore;
    snapshot: SnapshotResponse | null;
    release: ReleaseState | null;
    fmt: TrialFormat;
    onchanged: () => void;
  }

  let { ctl, snapshot: served, release, fmt, onchanged }: Props = $props();

  let captured = $state<SnapshotResponse | null>(null);
  let capturing = $state(false);
  const snapshot = $derived(captured ?? served);

  const POLL_MS = 1500;

  let run = $state<ReleaseRun | null>(null);
  let started = $state(false);
  let fetchedAt = $state(Date.now());
  let nowMs = $state(Date.now());
  let confirming = $state<'rehearse' | 'release' | null>(null);
  let typed = $state('');
  let reason = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let pollFailed = $state(false);
  let panel = $state<HTMLElement | undefined>();

  $effect(() => {
    if (release?.release && !release.release.done && run === null) {
      run = release.release;
      fetchedAt = Date.now();
      started = true;
    }
  });

  const running = $derived(run !== null && !run.done);
  const lang = $derived(settings.language);
  const word = $derived(t('trialConfirmWord'));
  const canRelease = $derived(confirmMatches(typed, word));
  const snap = $derived(snapshot?.snapshot ?? null);
  const publishing = $derived(snapshot?.publishing ?? ctl.control?.publishing ?? true);
  const timeoutS = $derived(release?.timeout_s ?? 192);
  const lastRehearsal = $derived(release?.last_rehearsal ?? null);
  const lastDry = $derived(release?.last_dry_rehearsal ?? null);
  const canCapture = $derived(snapshot?.can_capture);
  const showCapture = $derived(
    canCapture !== undefined &&
      (snap === null || snap.origin === 'manual' || snap.stale === true || !snapshot?.armed),
  );
  const lastRelease = $derived(
    release?.release && release.release.done && !started ? release.release : null,
  );
  const elapsed = $derived(run ? elapsedSeconds(run, fetchedAt, nowMs) : 0);
  const share = $derived(targetShare(elapsed));
  const counts = $derived(run ? releaseCounts(run) : null);
  const value = (v: unknown) =>
    typeof v === 'number'
      ? formatNumber(v, 1, lang)
      : v === null || v === undefined
        ? '–'
        : String(v);
  const kindName = (kind: string) => tOpt(`kind_${kind}`) ?? kind;
  const modeName = (mode: string | null) => (mode ? tc('modeName_', mode) : '–');
  const runLine = (key: 'trialLastRehearsal' | 'trialLastRelease', r: ReleaseRun) =>
    t(key, {
      time: fmt.date(r.finished_at ?? r.started_at),
      duration: formatDuration(r.duration_s, lang),
      outcome: t(`trialOutcome_${r.outcome}`),
    });

  onMount(() => {
    const timer = window.setInterval(() => (nowMs = Date.now()), 1000);
    return () => window.clearInterval(timer);
  });

  $effect(() => {
    if (!running) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      try {
        const state = await fetchRelease();
        if (stopped || !state?.release) return;
        pollFailed = false;
        run = state.release;
        fetchedAt = Date.now();
        if (state.release.done) {
          onchanged();
          void ctl.refresh();
        }
      } catch {
        if (!stopped) pollFailed = true;
      }
    }, POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  });

  async function ask(kind: 'rehearse' | 'release'): Promise<void> {
    confirming = kind;
    typed = '';
    reason = '';
    error = null;
    await tick();
    panel?.querySelector<HTMLElement>('input, button.primary')?.focus();
  }

  function refused(failure: unknown): string {
    const kind = failureKind(failure);
    if (kind === 'forbidden' || kind === 'unauthorized') {
      ctl.admin = false;
      return t('trialErrorForbidden');
    }
    if (failure instanceof ApiError && failure.code)
      return (
        tOpt(`releaseRefusal_${failure.code}`) ??
        tOpt(`captureRefusal_${failure.code}`) ??
        failure.detail?.message ??
        t('trialErrorFailed')
      );
    return t('trialErrorFailed');
  }

  async function capture(): Promise<void> {
    capturing = true;
    error = null;
    try {
      captured = await captureSnapshot();
      ctl.admin = true;
      onchanged();
    } catch (failure) {
      error = refused(failure);
    }
    capturing = false;
  }

  async function plan(): Promise<void> {
    busy = true;
    error = null;
    try {
      const result = await startRelease(true, '', true);
      run = result.release;
      fetchedAt = Date.now();
      started = true;
      ctl.admin = true;
      onchanged();
    } catch (failure) {
      error = refused(failure);
    }
    busy = false;
  }

  async function start(): Promise<void> {
    if (confirming === null) return;
    const rehearsal = confirming === 'rehearse';
    busy = true;
    error = null;
    try {
      const result = await startRelease(rehearsal, reason.trim());
      run = result.release;
      fetchedAt = Date.now();
      started = true;
      confirming = null;
      ctl.admin = true;
      if (result.release.done) onchanged();
      void ctl.refresh();
    } catch (failure) {
      error = refused(failure);
    }
    busy = false;
  }
</script>

<p class="lead muted">{t('trialReleaseLead')}</p>

{#if snapshot === null}
  <p class="muted" data-testid="release-missing">{t('trialReleaseMissing')}</p>
{:else}
  <section class="snapshot" data-testid="trial-snapshot" aria-labelledby="snapshot-title">
    <h3 id="snapshot-title">{t('trialSnapshotTitle')}</h3>
    {#if snap === null}
      <p class="muted" data-testid="trial-snapshot-none">
        {showCapture ? t('trialSnapshotNoneCapture') : t('trialSnapshotNone')}
      </p>
    {:else}
      <p
        class="caption muted"
        data-testid="trial-snapshot-origin"
        data-origin={snap.origin ?? 'go_live'}
      >
        {#if snap.origin === 'manual'}
          {t('trialSnapshotManual', { time: fmt.date(snap.taken_at) })}
        {:else}
          {t('trialSnapshotTaken', { time: fmt.date(snap.taken_at) })} · {t(
            'trialSnapshotPrevious',
            {
              mode: modeName(snap.previous_mode),
            },
          )}
        {/if}
        {#if typeof snap.outside_c === 'number'}
          · {t('trialSnapshotOutside', { temp: formatNumber(snap.outside_c, 1, lang) })}{/if}
      </p>
      {#if snap.stale}
        <p class="warn" data-testid="trial-snapshot-stale">
          <Icon name="warning" size={16} />{t('trialSnapshotStale', {
            days: formatNumber((snap.age_s ?? 0) / 86_400, 0, lang),
          })}
        </p>
      {/if}
      <ul class="items">
        {#each snap.items as item (item.kind)}
          <li>
            <span>{kindName(item.kind)}</span>
            <strong>{value(item.value)}</strong>
            <code class="caption muted">{item.signal}</code>
          </li>
        {/each}
      </ul>
      {#if snap.own_values_possible}
        <p class="warn"><Icon name="warning" size={16} />{t('trialSnapshotOwn')}</p>
      {/if}
      {#if !snap.complete}
        <p class="warn"><Icon name="warning" size={16} />{t('trialSnapshotIncomplete')}</p>
      {/if}
      {#if snap.released_at}
        <p class="muted caption">
          {t('trialSnapshotReleased', { time: fmt.date(snap.released_at) })}
        </p>
      {/if}
      {#if Object.keys(snap.facts).length > 0}
        <Details summary={t('trialSnapshotFacts')} id="trial-snapshot-facts" testid="trial-facts">
          <ul class="facts-list">
            {#each Object.entries(snap.facts) as [signal, fact] (signal)}
              <li><code>{signal}</code> <strong>{value(fact)}</strong></li>
            {/each}
          </ul>
        </Details>
      {/if}
    {/if}
    {#if showCapture}
      <div class="capture" data-testid="trial-capture">
        {#if snap !== null}<p class="caption muted">{t('trialCaptureLead')}</p>{/if}
        <Button
          onclick={capture}
          disabled={!canCapture || ctl.admin === false || capturing}
          data-testid="trial-capture-button"
          >{snap === null ? t('trialCapture') : t('trialCaptureAgain')}</Button
        >
        {#if !canCapture && snapshot?.capture_refusal}
          <p class="caption muted" data-testid="trial-capture-refusal">
            {tc('captureRefusal_', snapshot.capture_refusal)}
          </p>
        {/if}
      </div>
    {/if}
  </section>
{/if}

{#if snapshot !== null}
  <Details summary={t('trialWhatHappens')} id="trial-what-happens" testid="trial-what-happens">
    <ol class="steps">
      <li>{t('trialStep1')}</li>
      <li>{t('trialStep2')}</li>
      <li>{t('trialStep3', { timeout: formatDuration(timeoutS, lang) })}</li>
      <li>{t('trialStep4')}</li>
    </ol>
    <p class="muted">{t('trialRehearsalNote')}</p>
  </Details>

  {#if run !== null && (running || started)}
    <section class="progress" data-testid="release-progress" aria-live="polite">
      <p class="state" data-testid="release-state" data-outcome={run.outcome}>
        {#if run.dry}
          <Icon name="check" size={18} />
          {t('trialDryDone')}
        {:else if running}
          <Icon name="clock" size={18} />
          {run.rehearsal ? t('trialRunningRehearsal') : t('trialRunning')}
        {:else if run.outcome === 'ok'}
          <Icon name="check" size={18} />
          {run.rehearsal
            ? t('trialDoneOkRehearsal', { duration: formatDuration(run.duration_s, lang) })
            : t('trialDoneOk', { duration: formatDuration(run.duration_s, lang) })}
        {:else}
          <Icon name="warning" size={18} />
          {t('trialDoneIncomplete', { duration: formatDuration(run.duration_s, lang) })}
        {/if}
      </p>
      {#if !run.dry}<div class="elapsed">
          <div
            class="bar"
            class:over={elapsed > RELEASE_TARGET_S}
            role="progressbar"
            aria-label={t('trialElapsedLabel')}
            aria-valuemin="0"
            aria-valuemax={RELEASE_TARGET_S}
            aria-valuenow={Math.round(elapsed)}
            aria-valuetext={t('trialElapsed', {
              elapsed: formatDuration(elapsed, lang),
              target: formatDuration(RELEASE_TARGET_S, lang),
            })}
          >
            <span style:width="{share * 100}%"></span>
          </div>
          <span class="caption" data-testid="release-elapsed"
            >{t('trialElapsed', {
              elapsed: formatDuration(elapsed, lang),
              target: formatDuration(RELEASE_TARGET_S, lang),
            })}{#if elapsed > RELEASE_TARGET_S}
              · {t('trialOverTarget')}{/if}</span
          >
        </div>{/if}
      {#if counts && !run.dry}
        <p class="caption muted">{t('trialItemsSummary', counts)}</p>
      {/if}
      <ul class="run-items" data-testid="release-items">
        {#each run.items as item (item.kind)}
          {@const phase = itemPhase(item.status)}
          <li data-kind={item.kind} data-status={item.status}>
            <span class="name">{kindName(item.kind)}</span>
            <span class="values">{value(item.before)} → {value(item.target ?? item.snapshot)}</span>
            <Pill
              tone={phase === 'good' ? 'good' : phase === 'bad' ? 'bad' : 'info'}
              icon={phase === 'good' ? 'check' : phase === 'bad' ? 'critical' : 'clock'}
              >{tc('releaseItem_', item.status)}</Pill
            >
            {#if item.clamped}<span class="detail caption" data-testid="release-item-clamped"
                >{t('trialItemClamped')}</span
              >{/if}
            {#if item.detail}<span class="detail caption muted">{item.detail}</span>{/if}
          </li>
        {/each}
      </ul>
      {#if pollFailed}<p class="caption warn">{t('trialPollFailed')}</p>{/if}
      {#if run.done && !run.dry}
        <section class="next" data-testid="release-next" aria-labelledby="next-title">
          <h3 id="next-title">{t('trialNextTitle')}</h3>
          <ol>
            <li>{t('trialNext1')}</li>
            <li>
              {t('trialNext2')}
              <a href="#/system/shadow">{t('trialCompareLink')}</a> ·
              <a href="#/activity">{t('trialActivityLink')}</a>
            </li>
            <li>{t('trialNext3')}</li>
            <li>{t('trialNext4')}</li>
          </ol>
          {#if run.rehearsal}<p class="muted">{t('trialNextRehearsal')}</p>{/if}
        </section>
      {/if}
    </section>
  {:else if lastRehearsal || lastDry || lastRelease || publishing}
    <p class="caption muted" data-testid="release-last">
      {lastRehearsal ? runLine('trialLastRehearsal', lastRehearsal) : t('trialNoRehearsal')}
      {#if lastDry}
        {t('trialLastDry', {
          time: fmt.date(lastDry.finished_at ?? lastDry.started_at),
          outcome: t(`trialOutcome_${lastDry.outcome}`),
        })}
      {/if}
      {#if lastRelease && !lastRelease.rehearsal}
        {runLine('trialLastRelease', lastRelease)}
      {/if}
    </p>
  {/if}

  {#if !running}
    {#if ctl.admin === false}
      <p class="muted" data-testid="release-admin-only">{t('trialAdminOnly')}</p>
    {:else if !publishing}
      <p class="muted" data-testid="release-not-publishing">
        {t('trialNotPublishing', { mode: modeName(ctl.control?.mode ?? 'shadow') })}
      </p>
    {/if}
    {#if confirming === null}
      <ActionRow>
        {#if snap !== null && canCapture !== undefined && !publishing}
          <Button
            type="button"
            variant="primary"
            onclick={plan}
            disabled={ctl.admin === false || busy}
            data-testid="release-dry">{t('trialDryRehearse')}</Button
          >
        {/if}
        <Button
          onclick={() => ask('rehearse')}
          disabled={ctl.admin === false}
          data-testid="release-rehearse">{t('trialRehearse')}</Button
        >
        <Button
          variant="danger"
          onclick={() => ask('release')}
          disabled={ctl.admin === false}
          data-testid="release-now">{t('trialRelease')}</Button
        >
      </ActionRow>
    {:else}
      <form
        class="confirm"
        bind:this={panel}
        data-testid="release-confirm"
        aria-labelledby="confirm-title"
        onsubmit={(event) => {
          event.preventDefault();
          if (confirming === 'rehearse' || canRelease) void start();
        }}
      >
        <h3 id="confirm-title">
          {confirming === 'rehearse'
            ? t('trialConfirmRehearseTitle')
            : t('trialConfirmReleaseTitle')}
        </h3>
        <p>
          {confirming === 'rehearse' ? t('trialConfirmRehearseText') : t('trialConfirmReleaseText')}
        </p>
        <p class="after" data-testid="release-confirm-after">
          {confirming === 'rehearse'
            ? t('trialConfirmAfterRehearse')
            : t('trialConfirmAfterRelease')}
        </p>
        {#if confirming === 'release'}
          <label>
            <span>{t('trialConfirmType', { word })}</span>
            <TextInput
              type="text"
              bind:value={typed}
              autocomplete="off"
              spellcheck="false"
              data-testid="release-type"
            />
          </label>
        {/if}
        <label>
          <span>{t('trialReason')}</span>
          <TextInput
            type="text"
            maxlength={200}
            bind:value={reason}
            placeholder={t('trialReasonPlaceholder')}
            data-testid="release-reason"
          />
        </label>
        <ActionRow>
          <Button
            type="submit"
            variant={confirming === 'release' ? 'danger' : 'primary'}
            solid
            disabled={busy || (confirming === 'release' && !canRelease)}
            data-testid="release-start"
          >
            {busy
              ? t('trialStarting')
              : confirming === 'rehearse'
                ? t('trialStartRehearsal')
                : t('trialStartRelease')}
          </Button>
          <Button onclick={() => (confirming = null)} disabled={busy}>{t('cancel')}</Button>
        </ActionRow>
      </form>
    {/if}
    {#if error}<InlineMessage tone="error" size="md" class="release-error" testid="release-error"
        >{error}</InlineMessage
      >{/if}
  {/if}
{/if}

<style>
  .lead {
    margin: 0 0 var(--space-3);
    font-size: var(--fs-caption);
  }
  h3 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-body);
  }
  section + :global(*),
  .snapshot {
    margin-bottom: var(--space-2);
  }
  p {
    margin: 0 0 var(--space-2);
  }
  .items,
  .facts-list,
  .run-items {
    list-style: none;
    margin: 0 0 var(--space-2);
    padding: 0;
  }
  .items li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 0 var(--space-2);
    padding: var(--space-1) 0;
    border-top: 1px solid var(--border);
  }
  .items li:first-child {
    border-top: none;
  }
  .items code {
    grid-column: 1 / -1;
    overflow-wrap: anywhere;
  }
  @container main (max-width: 40rem) {
    .items code {
      display: none;
    }
  }
  .facts-list li {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: var(--space-2);
    padding: 0.15rem 0;
  }
  .facts-list code {
    font-size: var(--fs-caption);
    overflow-wrap: anywhere;
  }
  .warn {
    display: flex;
    gap: var(--space-1);
    align-items: flex-start;
    color: var(--warn-text);
  }
  .steps {
    margin: 0 0 var(--space-2);
    padding-left: 1.25rem;
  }
  .progress {
    margin: var(--space-2) 0;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface-2);
  }
  .state {
    display: flex;
    gap: var(--space-2);
    align-items: center;
    font-weight: var(--fw-bold);
  }
  .state[data-outcome='ok'] {
    color: var(--status-ok);
  }
  .state[data-outcome='incomplete'] {
    color: var(--status-limited);
  }
  .elapsed {
    display: grid;
    gap: var(--space-1);
    margin-bottom: var(--space-2);
  }
  .bar {
    height: 0.6rem;
    border-radius: var(--radius-pill);
    background: var(--surface);
    border: 1px solid var(--border);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: var(--status-ok);
    transition: width 0.4s linear;
  }
  .bar.over span {
    background: var(--status-limited);
  }
  .run-items li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 0.1rem var(--space-2);
    align-items: center;
    padding: 0.35rem 0;
    border-top: 1px solid var(--border);
  }
  .run-items li:first-child {
    border-top: none;
  }
  .name {
    font-weight: var(--fw-semibold);
  }
  .values {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .detail {
    grid-column: 1 / -1;
    overflow-wrap: anywhere;
  }
  .next ol {
    margin: 0;
    padding-left: 1.25rem;
    display: grid;
    gap: var(--space-1);
  }
  .capture {
    display: grid;
    justify-items: start;
    gap: var(--space-1);
    margin-top: var(--space-2);
  }
  .capture p {
    margin: 0;
  }
  .confirm {
    display: grid;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 2px solid var(--status-limited);
    border-radius: var(--radius);
  }
  .confirm .after {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .confirm label {
    display: grid;
    gap: var(--space-1);
  }
  :global(.release-error) {
    margin-top: var(--space-2);
  }
  @media (prefers-reduced-motion: reduce) {
    .bar span {
      transition: none;
    }
  }
  @container main (max-width: 40rem) {
    .lead {
      display: none;
    }
  }
</style>
