<!--
  Replay: "What would ovenbird have sent?" (System → Replay, `#/system/replay`). Replays the stored
  decisions of a period with the active configuration, a stored version or the current draft, and
  lays the result next to what ovenbird recorded and what the pump actually ran on: summary
  figures, the three lines, how it decided and the episodes against the pump. Open loop: a fixed
  note says that no comfort or energy claim follows. The replay runs on the service as a job; the
  page polls it and keeps it when the tab is left and opened again.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import Select from '$ui/Select.svelte';
  import StatChip from '$ui/StatChip.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import CoverageStrip from '$components/replay/CoverageStrip.svelte';
  import ReplayChart from '$components/replay/ReplayChart.svelte';
  import ReplayEpisodes from '$components/replay/ReplayEpisodes.svelte';
  import { fetchVersions } from '$lib/core/api';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import type { ConfigVersion } from '$lib/core/types';
  import {
    customPeriod,
    fetchCoverage,
    identityState,
    presetPeriod,
    REPLAY_PRESETS,
    replayBody,
    topShares,
    type CoverageCell,
    type ReplayCoverage,
    type ReplayKind,
    type ReplayPreset,
    type ReplayResult,
  } from '$lib/replay/replay';
  import { replayRun } from '$lib/replay/run.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const MINUTE = 60_000;
  const KINDS: ReplayKind[] = ['active', 'version', 'draft'];

  let coverage = $state<ReplayCoverage | null>(null);
  let coveragePhase = $state<'loading' | 'ok' | 'missing' | 'failed'>('loading');
  let preset = $state<ReplayPreset>('7d');
  let customFrom = $state('');
  let customTo = $state('');
  let anchor = $state(Math.floor(untrack(() => live.clock) / MINUTE) * MINUTE);
  let kind = $state<ReplayKind>('active');
  let versions = $state<ConfigVersion[] | null>(null);
  let versionsFailed = $state(false);
  let chosenVersion = $state<number | null>(null);

  const lang = $derived(settings.language);
  const maxDays = $derived(coverage?.max_days ?? 31);
  const activeVersion = $derived(ctl.config?.version ?? null);
  const custom = $derived(preset === 'custom' ? customPeriod(customFrom, customTo, maxDays) : null);
  const problem = $derived(custom && 'problem' in custom ? custom.problem : null);
  const period = $derived.by(() => {
    if (custom) return 'from' in custom ? custom : null;
    return presetPeriod(preset as Exclude<ReplayPreset, 'custom'>, anchor, maxDays);
  });
  const job = $derived(replayRun.job);
  const result = $derived<ReplayResult | null>(job?.state === 'done' ? (job.result ?? null) : null);
  const canRun = $derived(
    period !== null && !replayRun.running && (kind !== 'version' || chosenVersion !== null),
  );

  const presetOptions = $derived(
    REPLAY_PRESETS.map((value) => ({
      value,
      label: t(`replayPreset_${value}`),
      testid: `replay-preset-${value}`,
    })),
  );
  const kindOptions = $derived(
    KINDS.map((value) => ({
      value,
      label: t(`replayConfig_${value}`),
      testid: `replay-config-${value}`,
    })),
  );

  function localInput(ms: number): string {
    const d = new Date(ms);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function pickPreset(next: ReplayPreset): void {
    if (next === 'custom' && preset !== 'custom' && period) {
      customFrom = localInput(period.from);
      customTo = localInput(period.to);
    }
    if (next !== 'custom') anchor = Math.floor(live.clock / MINUTE) * MINUTE;
    preset = next;
  }

  function pickDay(cell: CoverageCell): void {
    customFrom = localInput(cell.from);
    customTo = localInput(Math.min(cell.to, live.clock));
    preset = 'custom';
  }

  function pickKind(next: ReplayKind): void {
    kind = next;
    if (next === 'version' && versions === null) void loadVersions();
  }

  async function loadVersions(): Promise<void> {
    versionsFailed = false;
    try {
      const body = await fetchVersions(50);
      versions = body.versions;
      chosenVersion ??= body.versions.find((v) => v.version !== activeVersion)?.version ?? null;
    } catch {
      versionsFailed = true;
    }
  }

  function run(): void {
    if (!period) return;
    void replayRun.start(
      replayBody(period, {
        kind,
        version: chosenVersion,
        changes: kind === 'draft' ? draft.changes : undefined,
      }),
    );
  }

  $effect(() => {
    const controller = new AbortController();
    const now = untrack(() => live.clock);
    fetchCoverage(null, controller.signal)
      .then((body) => {
        if (body === null) {
          coveragePhase = 'missing';
          return;
        }
        coverage = body;
        coveragePhase = 'ok';
        anchor = Math.min(anchor, Date.parse(body.to) || now);
      })
      .catch(() => {
        if (!controller.signal.aborted) coveragePhase = 'failed';
      });
    return () => controller.abort();
  });

  $effect(() => {
    untrack(() => replayRun.resume());
    return () => replayRun.pause();
  });

  const num = (value: number | null | undefined, digits = 1) =>
    value === null || value === undefined ? '–' : formatNumber(value, digits, lang);
  const minutes = (value: number) =>
    value > 0 ? formatDuration(value * 60, lang) : t('replayNone');
  const when = (iso: string | null | undefined) => formatDateTime(iso ?? null, lang, live.clock);
  const pct = (share: number) => `${formatNumber(share * 100, 0, lang)} %`;

  function configLabel(value: ReplayResult['config']): string {
    if (value.kind === 'version')
      return t('replayResultConfig_version', { version: value.version ?? '–' });
    if (value.kind === 'draft')
      return t('replayResultConfig_draft', { n: Object.keys(value.changes ?? {}).length });
    return value.version === null
      ? t('replayResultConfig_activePlain')
      : t('replayResultConfig_active', { version: value.version });
  }

  const identity = $derived(result ? identityState(result.identity) : null);
  const binding = $derived(result ? (topShares(result.summary.binding, 1)[0] ?? null) : null);
  const shareGroups = $derived(
    result
      ? [
          {
            id: 'ladder',
            title: t('replayShareLadder'),
            prefix: 'ladder_',
            items: topShares(result.summary.ladder),
          },
          {
            id: 'reason',
            title: t('replayShareReason'),
            prefix: 'reason_',
            items: topShares(result.summary.reason),
          },
          {
            id: 'binding',
            title: t('replayShareBinding'),
            prefix: 'binding_',
            items: topShares(result.summary.binding),
          },
        ]
      : [],
  );
</script>

<section class="replay" data-testid="replay-page" aria-labelledby="replay-title">
  <div class="intro">
    <h2 id="replay-title">{t('replayTitle')}</h2>
    <p class="muted lead">{t('replayLead')}</p>
  </div>

  <div class="claims" data-help="system/replay.claims">
    <InlineMessage tone="info" icon size="md" testid="replay-no-claims">
      <strong>{t('replayNoClaimsTitle')}.</strong>
      {t('replayNoClaims')}
    </InlineMessage>
  </div>

  {#if coveragePhase === 'missing'}
    <Card bare as="div" testid="replay-missing">
      <EmptyState art="noData" title={t('replayMissingTitle')} text={t('replayMissingText')} />
    </Card>
  {:else}
    <Card
      title={t('replayPeriodLabel')}
      icon="clock"
      testid="replay-setup"
      help="system/replay.period"
    >
      <div class="range-bar">
        <Segmented
          options={presetOptions}
          value={preset}
          onchange={pickPreset}
          label={t('replayPeriodLabel')}
          wrap
        />
        {#if preset === 'custom'}
          <div class="custom">
            <label>
              <span>{t('replayFrom')}</span>
              <TextInput
                block={false}
                type="datetime-local"
                bind:value={customFrom}
                aria-invalid={problem !== null}
                data-testid="replay-from"
              />
            </label>
            <label>
              <span>{t('replayTo')}</span>
              <TextInput
                block={false}
                type="datetime-local"
                bind:value={customTo}
                aria-invalid={problem !== null}
                data-testid="replay-to"
              />
            </label>
          </div>
          {#if problem !== null}
            <p class="err" role="alert" data-testid="replay-period-error">
              {t(`replayPeriod_${problem}`, { days: formatNumber(maxDays, 0, lang) })}
            </p>
          {/if}
        {/if}
      </div>
      {#if coverage}
        <CoverageStrip {coverage} {period} now={live.clock} onpick={pickDay} />
      {:else if coveragePhase === 'loading'}
        <p class="muted caption">…</p>
      {/if}
    </Card>

    <Card
      title={t('replayConfigLabel')}
      icon="settings"
      testid="replay-config"
      help="system/replay.config"
    >
      <div class="config">
        <Segmented
          options={kindOptions}
          value={kind}
          onchange={pickKind}
          label={t('replayConfigLabel')}
          wrap
        />
        {#if kind === 'active'}
          <p class="caption muted" data-testid="replay-config-note">
            {t('replayConfigActiveNote', { version: activeVersion ?? '–' })}
          </p>
        {:else if kind === 'version'}
          {#if versionsFailed}
            <p class="err">{t('replayVersionsMissing')}</p>
          {:else if versions}
            <label class="version">
              <span class="caption">{t('replayVersionLabel')}</span>
              <Select bind:value={chosenVersion} block={false} data-testid="replay-version">
                {#each versions as item (item.version)}
                  <option value={item.version}>
                    {t('replayVersionOption', {
                      version: item.version,
                      date: when(item.created_at),
                    })}
                  </option>
                {/each}
              </Select>
            </label>
          {/if}
        {:else}
          <p class="caption muted" data-testid="replay-config-note">
            {draft.count > 0
              ? t('replayConfigDraftNote', { n: draft.count })
              : t('replayConfigDraftEmpty')}
          </p>
        {/if}
      </div>
      <div class="run" data-help="system/replay.run">
        {#if replayRun.running}
          <div class="progress" role="status" data-testid="replay-progress">
            <progress max="1" value={job?.progress ?? 0}></progress>
            <span>
              {t('replayRunning', { pct: formatNumber((job?.progress ?? 0) * 100, 0, lang) })}
              · {t(`replayPhase_${(job?.phase ?? 'queued') as 'queued'}`)}
            </span>
          </div>
          <Button onclick={() => void replayRun.cancel()} data-testid="replay-cancel">
            {t('replayCancel')}
          </Button>
        {:else}
          <Button variant="primary" disabled={!canRun} onclick={run} data-testid="replay-run">
            {result ? t('replayRunAgain') : t('replayRun')}
          </Button>
        {/if}
      </div>
      {#if replayRun.problem}
        <InlineMessage tone="error" testid="replay-problem">
          {t(`replayProblem_${replayRun.problem}`, { detail: replayRun.detail ?? '' })}
        </InlineMessage>
      {:else if job?.state === 'failed'}
        <InlineMessage tone="error" testid="replay-problem">
          {t('replayFailed', { error: job.error ?? '' })}
        </InlineMessage>
      {:else if job?.state === 'cancelled'}
        <InlineMessage tone="warn" testid="replay-cancelled">{t('replayCancelled')}</InlineMessage>
      {/if}
    </Card>

    {#if result}
      <Card title={t('replayResultTitle')} icon="chart" testid="replay-result">
        <p class="caption muted for" data-testid="replay-for">
          {t('replayResultFor', {
            config: configLabel(result.config),
            from: when(result.from),
            to: when(result.to),
            ticks: result.ticks,
            seconds: num(result.run_s, 1),
          })}
        </p>
        {#if result.ticks === 0}
          <p class="muted" data-testid="replay-empty">{t('replayEmpty')}</p>
        {:else}
          <InlineMessage
            tone={identity === 'exact' ? 'ok' : identity === 'differs' ? 'warn' : 'info'}
            icon
            testid="replay-identity"
          >
            {t(`replayIdentity_${identity ?? 'unchecked'}`, {
              n: result.identity.ticks,
              m: result.identity.mismatches,
              at: when(result.identity.first_mismatch),
            })}
          </InlineMessage>
          <div class="chips">
            <StatChip
              label={t('replayChipChanges')}
              value={String(result.summary.changes_replayed)}
              caption={t('replayChipChangesCaption', { n: result.summary.changes_recorded })}
              testid="replay-chip-changes"
            />
            <StatChip
              label={t('replayChipWrites')}
              value={num(result.summary.writes_per_day)}
              tone={result.summary.days_over_budget > 0 ? 'limited' : 'default'}
              caption={result.summary.days_over_budget > 0
                ? t('replayChipWritesOver', {
                    n: result.summary.days_over_budget,
                    budget: result.summary.budget,
                  })
                : t('replayChipWritesCaption', {
                    max: result.summary.max_writes_day,
                    budget: result.summary.budget,
                  })}
              testid="replay-chip-writes"
            />
            <StatChip
              label={t('replayChipAbove')}
              value={minutes(result.summary.above_pump_min)}
              caption={t('replayChipPumpCaption', { k: num(result.threshold_k) })}
              testid="replay-chip-above"
            />
            <StatChip
              label={t('replayChipBelow')}
              value={minutes(result.summary.below_pump_min)}
              caption={t('replayChipPumpCaption', { k: num(result.threshold_k) })}
              testid="replay-chip-below"
            />
            <StatChip
              label={t('replayChipRecorded')}
              value={minutes(result.summary.differs_recorded_min)}
              caption={t('replayChipRecordedCaption', {
                k: num(result.summary.mean_diff_recorded_k),
              })}
              testid="replay-chip-recorded"
            />
            <StatChip
              label={t('replayChipBinding')}
              value={binding ? tc('binding_', binding[0]) : t('replayNone')}
              caption={binding
                ? t('replayChipBindingCaption', { share: pct(binding[1]) })
                : undefined}
              testid="replay-chip-binding"
            />
          </div>
        {/if}
      </Card>

      {#if result.ticks > 0}
        <Card title={t('replayChartTitle')} testid="replay-chart-card">
          <ReplayChart {result} now={live.clock} />
        </Card>

        <Card title={t('replaySharesTitle')} testid="replay-shares">
          <div class="shares">
            {#each shareGroups as group (group.id)}
              <div class="share-group" data-testid="replay-share-{group.id}">
                <h3 class="caption">{group.title}</h3>
                {#if group.items.length === 0}
                  <p class="caption muted">{t('replayShareNone')}</p>
                {:else}
                  <ul>
                    {#each group.items as [code, share] (code)}
                      <li>
                        <span class="name">{tc(group.prefix, code)}</span>
                        <span class="bar" style:--share={share} aria-hidden="true"></span>
                        <span class="value">{pct(share)}</span>
                      </li>
                    {/each}
                  </ul>
                {/if}
              </div>
            {/each}
          </div>
        </Card>

        <Card title={t('replayEpisodesTitle')} testid="replay-episodes-card">
          <ReplayEpisodes
            episodes={result.episodes}
            total={result.episodes_total}
            thresholdK={result.threshold_k}
            now={live.clock}
          />
        </Card>
      {/if}

      {#if result.limitations.length}
        <Card title={t('replayLimitationsTitle')} testid="replay-limitations">
          <ul class="limits">
            {#each result.limitations as line (line)}<li>{line}</li>{/each}
          </ul>
        </Card>
      {/if}
    {:else if !replayRun.running && !replayRun.problem && job?.state !== 'failed'}
      <p class="muted" data-testid="replay-idle">{t('replayIdle')}</p>
    {/if}
  {/if}
</section>

<style>
  .replay {
    display: grid;
    gap: var(--space-4);
    min-width: 0;
  }
  .intro h2 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-emph);
  }
  .lead {
    margin: 0;
    max-width: 60rem;
    overflow-wrap: anywhere;
  }
  .range-bar,
  .config {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: var(--space-2) var(--space-3);
    margin-bottom: var(--space-3);
  }
  .custom {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-3);
  }
  .custom label,
  .version {
    display: grid;
    gap: var(--space-1);
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .config p {
    flex-basis: 100%;
    margin: 0;
  }
  .err {
    flex-basis: 100%;
    margin: 0;
    color: var(--err-text);
  }
  .run {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin-bottom: var(--space-2);
  }
  .progress {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }
  .progress progress {
    width: min(14rem, 60vw);
    accent-color: var(--accent);
  }
  .for {
    margin: 0 0 var(--space-3);
    overflow-wrap: anywhere;
  }
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(10rem, 45%), 1fr));
    gap: var(--space-3);
    margin-top: var(--space-3);
  }
  .shares {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(16rem, 100%), 1fr));
    gap: var(--space-4);
  }
  .share-group h3 {
    margin: 0 0 var(--space-2);
    color: var(--muted);
    font-weight: var(--fw-semibold);
  }
  .share-group ul,
  .limits {
    display: grid;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .share-group li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 4rem 3rem;
    align-items: center;
    gap: var(--space-2);
  }
  .name {
    overflow-wrap: anywhere;
  }
  .bar {
    height: 0.5rem;
    border-radius: var(--radius-pill);
    background: linear-gradient(
      to right,
      var(--accent) calc(var(--share) * 100%),
      var(--surface-2) calc(var(--share) * 100%)
    );
  }
  .value {
    text-align: end;
    font-variant-numeric: tabular-nums;
  }
  .limits li {
    overflow-wrap: anywhere;
  }
</style>
