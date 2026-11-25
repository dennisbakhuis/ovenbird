<!--
  Yearly archive: every finished month frozen into a zip in the data directory, independent of
  the retention. The switch turns it on or off (a configuration change, admin); downloads per
  calendar year, heating season (August to July) or month, and delete per month or year with a
  confirmation (admin). The occupancy notice stays in view above the downloads.

  Props: archive (GET archive, null for an older service), phase, now (service clock, ms),
  onchange (a newer archive status after a delete), onrefresh (reload after the switch).
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import Modal from '$ui/Modal.svelte';
  import Pill from '$ui/Pill.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import StatChip from '$ui/StatChip.svelte';
  import Switch from '$ui/Switch.svelte';
  import { applyConfig, deleteArchive, failureKind, fetchConfig } from '$lib/core/api';
  import { DOWNLOAD_PREFIX } from '$lib/core/brand';
  import { formatDateTime } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { ArchiveGroup, ArchiveMonth, ArchiveStatus } from '$lib/core/types';
  import {
    frozenOfYear,
    groupPath,
    isPartial,
    monthName,
    monthPath,
    monthShort,
    type GroupKind,
  } from '$lib/system/archive';
  import { downloadFrom, formatBytes, type ArchiveFailure } from '$lib/system/data';

  interface Props {
    archive: ArchiveStatus | null;
    phase: 'loading' | 'failed' | 'ok';
    now: number;
    onchange: (next: ArchiveStatus) => void;
    onrefresh: () => void;
    showMonths?: boolean;
  }

  let { archive, phase, now, onchange, onrefresh, showMonths = false }: Props = $props();

  interface Pending {
    period: string;
    label: string;
    months: number;
  }

  const DOWNLOAD_TEXT: Record<ArchiveFailure, string> = {
    forbidden: 'archiveDownloadForbidden',
    space: 'exportArchiveSpace',
    busy: 'exportArchiveBusy',
    missing: 'archiveGone',
    failed: 'actionFailed',
  };

  const lang = $derived(settings.language);
  const bytes = (value: number | null | undefined) => formatBytes(value, lang);
  const when = (iso: string | null | undefined) => (iso ? formatDateTime(iso, lang, now) : '–');

  let grouping = $state<GroupKind>('year');
  let enabled = $state(true);
  let switching = $state(false);
  let busy = $state<string | null>(null);
  let pending = $state<Pending | null>(null);
  let deleting = $state(false);
  let message = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);

  $effect(() => {
    if (archive && !switching) enabled = archive.enabled;
  });

  const groups = $derived(
    archive ? (grouping === 'year' ? archive.years : archive.seasons) : ([] as ArchiveGroup[]),
  );
  const frozenCount = $derived(archive?.months.filter((m) => m.state === 'frozen').length ?? 0);
  const hasGaps = (group: ArchiveGroup) =>
    (archive?.months ?? []).some(
      (month) => group.months.includes(month.period) && month.complete === false,
    );

  async function toggle(next: boolean): Promise<void> {
    switching = true;
    message = null;
    try {
      const doc = await fetchConfig();
      await applyConfig({
        base_version: doc.version,
        changes: { history_archive_enabled: next },
        comment: '',
        acknowledge: [],
      });
      enabled = next;
      onrefresh();
    } catch (error) {
      enabled = !next;
      const kind = failureKind(error);
      message = {
        tone: 'error',
        text:
          kind === 'forbidden' || kind === 'unauthorized'
            ? t('archiveSwitchForbidden')
            : t('actionFailed'),
      };
    } finally {
      switching = false;
    }
  }

  async function download(key: string, path: string, fallback: string): Promise<void> {
    busy = key;
    message = null;
    const failure = await downloadFrom(path, `${DOWNLOAD_PREFIX}${fallback}.zip`);
    if (failure) message = { tone: 'error', text: t(DOWNLOAD_TEXT[failure] as 'actionFailed') };
    busy = null;
  }

  function askMonth(month: ArchiveMonth): void {
    message = null;
    pending = { period: month.period, label: monthName(month.period, lang), months: 1 };
  }

  function askYear(group: ArchiveGroup): void {
    message = null;
    const months = frozenOfYear(archive?.months ?? [], group.id).length;
    pending = { period: group.id, label: group.period, months };
  }

  async function confirmDelete(): Promise<void> {
    if (!pending) return;
    const asked = pending;
    deleting = true;
    try {
      const result = await deleteArchive(asked.period);
      onchange(result.archive);
      message = { tone: 'ok', text: t('archiveDeleted', { period: asked.label }) };
    } catch (error) {
      const kind = failureKind(error);
      message = {
        tone: 'error',
        text:
          kind === 'forbidden' || kind === 'unauthorized'
            ? t('archiveDeleteForbidden')
            : kind === 'conflict'
              ? t('archiveDeleteOpen')
              : kind === 'missing'
                ? t('archiveGone')
                : t('actionFailed'),
      };
    } finally {
      deleting = false;
      pending = null;
    }
  }

  const coverage = (group: ArchiveGroup) =>
    isPartial(group) && group.first && group.last
      ? t('archivePartial', {
          n: group.months.length,
          of: group.of,
          first: monthShort(group.first, lang),
          last: monthShort(group.last, lang),
        })
      : t('archiveWhole', { n: group.months.length, of: group.of });
</script>

<Card title={t('archiveTitle')} icon="clock" testid="archive-card" help="system/data.yearly">
  {#if phase === 'loading' && !archive}
    <p class="muted">{t('loading')}</p>
  {:else if phase === 'failed' && !archive}
    <p class="muted">{t('actionFailed')}</p>
  {:else if !archive}
    <p class="muted" data-testid="archive-missing">{t('archiveMissing')}</p>
  {:else}
    <p class="lead muted">{t('archiveLead')}</p>
    <InlineMessage tone="warn" icon testid="archive-privacy">{t('archiveNotice')}</InlineMessage>

    <div class="switch-row" data-help="system/data.yearly-switch">
      <span class="switch-label" id="archive-switch-label">{t('archiveSwitch')}</span>
      <Switch
        bind:checked={enabled}
        state={enabled ? t('archiveOn') : t('archiveOff')}
        disabled={switching}
        aria-labelledby="archive-switch-label"
        onchange={(event) => void toggle(event.currentTarget.checked)}
        data-testid="archive-switch"
      />
    </div>

    <div class="status" aria-live="polite" data-testid="archive-status">
      {#if archive.state?.error}
        <InlineMessage tone="error" testid="archive-error"
          >{t('archiveError', { error: archive.state.error })}</InlineMessage
        >
      {:else if !archive.enabled}
        <p class="caption muted" data-testid="archive-off">{t('archiveOffText')}</p>
      {:else if archive.state?.behind}
        <p class="caption muted" data-testid="archive-behind">{t('archiveBehind')}</p>
      {:else if archive.state?.archived_to}
        <p class="caption muted" data-testid="archive-upto">
          {t('archiveUpTo', { when: when(archive.state.archived_to) })}
        </p>
      {/if}
    </div>

    {#if archive.months.length === 0}
      <p class="muted" data-testid="archive-empty">{t('archiveEmpty')}</p>
    {:else}
      <div class="chips">
        <StatChip
          label={t('archiveStored')}
          value={bytes(archive.total_bytes)}
          caption={t('archiveMonthsCount', { n: frozenCount })}
          size="sm"
          testid="archive-total"
        />
        <StatChip
          label={t('archivePerYear')}
          value={bytes(archive.bytes_per_year)}
          caption={t('archivePerYearHint')}
          size="sm"
          testid="archive-per-year"
        />
      </div>

      <section class="part" data-help="system/data.yearly-download">
        <div class="part-head">
          <h3>{t('archiveDownloads')}</h3>
          <Segmented
            options={[
              { value: 'year', label: t('archiveByYear'), testid: 'archive-by-year' },
              { value: 'season', label: t('archiveBySeason'), testid: 'archive-by-season' },
            ]}
            value={grouping}
            onchange={(value) => (grouping = value as GroupKind)}
            label={t('archiveDownloads')}
            size="sm"
          />
        </div>
        {#if grouping === 'season'}
          <p class="caption muted">{t('archiveSeasonHint')}</p>
        {/if}
        <ul class="rows" data-testid="archive-groups">
          {#each groups as group (group.id)}
            <li data-testid="archive-group" data-period={group.id}>
              <div class="what">
                <strong>{group.period}</strong>
                {#if group.complete}
                  <Pill tone="good">{t('archiveComplete')}</Pill>
                {:else if hasGaps(group)}
                  <Pill tone="neutral">{t('archiveIncomplete')}</Pill>
                {/if}
                <span class="caption muted coverage">{coverage(group)}</span>
                {#if group.open_months.length > 0}
                  <span class="caption muted">{t('archiveGroupOpen')}</span>
                {/if}
              </div>
              <span class="size">{bytes(group.bytes)}</span>
              <ActionRow class="row-actions">
                <Button
                  size="sm"
                  disabled={group.months.length === 0}
                  busy={busy === `${group.kind}-${group.id}`}
                  onclick={() =>
                    download(
                      `${group.kind}-${group.id}`,
                      groupPath(group),
                      group.kind === 'year' ? `archive-${group.id}` : `archive-season-${group.id}`,
                    )}
                  aria-label={t('archiveDownloadOf', { period: group.period })}
                  data-testid="archive-group-download"
                >
                  <Icon name="download" size={16} />{t('archiveDownload')}
                </Button>
                {#if group.kind === 'year' && group.months.length > 0}
                  <Button
                    size="sm"
                    variant="ghost"
                    onclick={() => askYear(group)}
                    aria-label={t('archiveDeleteOf', { period: group.period })}
                    data-testid="archive-group-delete">{t('archiveDelete')}</Button
                  >
                {/if}
              </ActionRow>
            </li>
          {/each}
        </ul>
      </section>

      <section class="part" data-help="system/data.yearly-months">
        <Details
          summary={t('archiveMonths')}
          meta={archive.months.length}
          id="system.data.archive-months"
          open={showMonths}
          testid="archive-months-details"
        >
          <ul class="rows" data-testid="archive-months">
            {#each archive.months as month (month.period)}
              {@const name = monthName(month.period, lang)}
              <li data-testid="archive-month" data-period={month.period} data-state={month.state}>
                <div class="what">
                  <strong>{name}</strong>
                  {#if month.state === 'open'}
                    <Pill tone="info">{t('archiveBeingBuilt')}</Pill>
                  {:else if month.complete}
                    <Pill tone="good">{t('archiveComplete')}</Pill>
                  {/if}
                  <span class="caption muted">
                    {month.state === 'open' || month.days === null
                      ? t('archiveOpenUpTo', { when: when(month.archived_to) })
                      : t('archiveDays', { n: month.days, of: month.days_total })}
                    {#if month.missing_days}
                      · {t('archiveMissingDays', { n: month.missing_days })}
                    {/if}
                  </span>
                </div>
                <span class="size">{bytes(month.bytes)}</span>
                <ActionRow class="row-actions">
                  <Button
                    size="sm"
                    busy={busy === month.period}
                    onclick={() =>
                      download(
                        month.period,
                        monthPath(month.period),
                        `archive-${month.period}${month.state === 'open' ? '-partial' : ''}`,
                      )}
                    aria-label={t('archiveDownloadOf', { period: name })}
                    data-testid="archive-month-download"
                  >
                    <Icon name="download" size={16} />{t('archiveDownload')}
                  </Button>
                  {#if month.state === 'frozen'}
                    <Button
                      size="sm"
                      variant="ghost"
                      onclick={() => askMonth(month)}
                      aria-label={t('archiveDeleteOf', { period: name })}
                      data-testid="archive-month-delete">{t('archiveDelete')}</Button
                    >
                  {/if}
                </ActionRow>
              </li>
            {/each}
          </ul>
        </Details>
      </section>
    {/if}

    {#if message}
      <InlineMessage
        tone={message.tone}
        role={message.tone === 'ok' ? 'status' : 'alert'}
        testid="archive-message">{message.text}</InlineMessage
      >
    {/if}
  {/if}
</Card>

{#if pending}
  <Modal
    title={t('archiveDeleteTitle', { period: pending.label })}
    onclose={() => (pending = null)}
    testid="archive-delete-dialog"
  >
    <p>
      {pending.months === 1
        ? t('archiveDeleteMonthText')
        : t('archiveDeleteYearText', { n: pending.months })}
    </p>
    {#snippet footer()}
      <Button onclick={() => (pending = null)}>{t('cancel')}</Button>
      <Button
        variant="danger"
        busy={deleting}
        onclick={confirmDelete}
        data-testid="archive-delete-confirm">{t('archiveDeleteConfirm')}</Button
      >
    {/snippet}
  </Modal>
{/if}

<style>
  .lead {
    margin: 0 0 var(--space-2);
  }
  .switch-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  .switch-label {
    font-weight: var(--fw-semibold);
  }
  .status p {
    margin: 0 0 var(--space-2);
  }
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(10rem, 45%), 1fr));
    gap: var(--space-2);
    margin: var(--space-2) 0;
  }
  .part {
    margin-top: var(--space-4);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border);
  }
  .part h3 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-emph);
  }
  .part p {
    margin: 0 0 var(--space-2);
  }
  .part-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }
  .part-head h3 {
    margin: 0;
  }
  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
  }
  .rows li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    align-items: center;
    gap: var(--space-1) var(--space-3);
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .rows li:last-child {
    border-bottom: 0;
  }
  .what {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    min-width: 0;
  }
  .what .caption {
    flex-basis: 100%;
  }
  .size {
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    text-align: right;
  }
  .rows :global(.row-actions) {
    margin: 0;
  }
  @media (--narrow) {
    .rows li {
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .rows li :global(.row-actions) {
      grid-column: 1 / -1;
    }
  }
</style>
