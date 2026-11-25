<!--
  Storage: how large history.db and its backup copy are, what each resolution holds, the size
  expected at the retention in effect, and (admin) "Free space now", which compacts the file
  between two writer batches. The card asks the page to reload the report while a compaction
  runs.
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import InlineMessage from '$ui/InlineMessage.svelte';
  import StatChip from '$ui/StatChip.svelte';
  import { compactHistory, failureKind } from '$lib/core/api';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import { buildHash } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { HistoryStorage } from '$lib/core/types';
  import { formatBytes, resolutionKey } from '$lib/system/data';

  interface Props {
    storage: HistoryStorage | null;
    phase: 'loading' | 'failed' | 'ok';
    onrefresh: () => void;
  }

  let { storage, phase, onrefresh }: Props = $props();

  const POLL_MS = 2_000;
  const POLL_LIMIT = 15;

  const lang = $derived(settings.language);
  const bytes = (value: number | null | undefined) => formatBytes(value, lang);
  const when = (iso: string | null | undefined) => (iso ? formatDateTime(iso, lang) : '–');
  const kept = (days: number | null | undefined) =>
    days === null || days === undefined
      ? t('retentionForeverValue')
      : t('retentionDays', { n: formatNumber(days, 0, lang) });

  const compaction = $derived(storage?.compaction ?? null);
  const busy = $derived(compaction?.pending === true || compaction?.running === true);
  let asking = $state(false);
  let message = $state<{ tone: 'ok' | 'error'; text: string } | null>(null);
  let polls = 0;
  let timer: number | null = null;

  $effect(() => {
    if (!busy || polls >= POLL_LIMIT) return;
    timer = window.setTimeout(() => {
      polls += 1;
      onrefresh();
    }, POLL_MS);
    return () => {
      if (timer !== null) window.clearTimeout(timer);
    };
  });

  async function compact(): Promise<void> {
    asking = true;
    message = null;
    try {
      await compactHistory();
      polls = 0;
      message = { tone: 'ok', text: t('storageCompactQueued') };
      onrefresh();
    } catch (error) {
      const kind = failureKind(error);
      message = {
        tone: 'error',
        text:
          kind === 'forbidden' || kind === 'unauthorized'
            ? t('storageCompactForbidden')
            : t('actionFailed'),
      };
    } finally {
      asking = false;
    }
  }
</script>

<Card title={t('storageTitle')} icon="cpu" testid="storage-card" help="system/data.storage">
  {#if phase === 'loading' && !storage}
    <p class="muted">{t('loading')}</p>
  {:else if phase === 'failed' && !storage}
    <p class="muted">{t('actionFailed')}</p>
  {:else if !storage}
    <p class="muted" data-testid="storage-missing">{t('storageMissing')}</p>
  {:else}
    <div class="chips">
      <StatChip
        label={t('storageDatabase')}
        value={bytes(storage.files.database + storage.files.wal)}
        size="sm"
        testid="storage-database"
      />
      <StatChip
        label={t('storageSnapshot')}
        value={storage.files.snapshot === null
          ? t('storageSnapshotOff')
          : bytes(storage.files.snapshot)}
        size="sm"
        testid="storage-snapshot"
      />
      <StatChip
        label={t('storageFree')}
        value={bytes(storage.files.free)}
        size="sm"
        testid="storage-free"
      />
      <StatChip
        label={t('storageProjected')}
        value={bytes(storage.projected_bytes)}
        caption={t('storageProjectedHint')}
        size="sm"
        testid="storage-projected"
      />
    </div>
    <p class="caption muted" data-testid="storage-growth">
      {storage.growth_bytes_per_year
        ? t('storageGrowth', { size: bytes(storage.growth_bytes_per_year) })
        : t('storageNoGrowth')}
    </p>

    <div class="scroll">
      <table data-testid="storage-resolutions">
        <caption class="visually-hidden">{t('storageTitle')}</caption>
        <thead>
          <tr>
            <th scope="col">{t('storageResolution')}</th>
            <th scope="col">{t('storageKept')}</th>
            <th scope="col">{t('storageOldest')}</th>
            <th scope="col" class="num">{t('storageRows')}</th>
            <th scope="col" class="num">{t('storageSize')}</th>
            <th scope="col" class="num">{t('storagePerDay')}</th>
          </tr>
        </thead>
        <tbody>
          {#each storage.resolutions as item (item.id)}
            <tr data-resolution={item.id}>
              <th scope="row">{t(`res_${resolutionKey(item)}` as 'res_raw')}</th>
              <td>{kept(item.retention_days)}</td>
              <td>{when(item.oldest)}</td>
              <td class="num">{formatNumber(item.rows, 0, lang)}</td>
              <td class="num">{bytes(item.bytes)}</td>
              <td class="num">{bytes(item.bytes_per_day)}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="retention" data-help="system/data.retention">
      <a href={buildHash('settings', ['data'])} data-testid="storage-settings"
        >{t('storageSettingsLink')}<Icon name="chevronRight" size={16} /></a
      >
    </p>

    <Details summary={t('storageTables')} id="system.data.tables" testid="storage-tables">
      <ul class="tables">
        {#each storage.tables as table (table.name)}
          <li>
            <code>{table.name}</code>
            <span class="num">{bytes(table.bytes)}</span>
          </li>
        {/each}
      </ul>
    </Details>

    <div class="compact" data-help="system/data.compact">
      <p class="caption muted">
        {t('storageCompactText')}
        {#if storage.reclaimable_bytes > 0}
          {t('storageReclaimable', { size: bytes(storage.reclaimable_bytes) })}
        {/if}
      </p>
      <ActionRow>
        <Button onclick={compact} busy={asking || busy} data-testid="storage-compact">
          <Icon name="bolt" size={16} />{busy ? t('storageCompactRunning') : t('storageCompact')}
        </Button>
      </ActionRow>
      {#if message}
        <InlineMessage
          tone={message.tone}
          role={message.tone === 'ok' ? 'status' : 'alert'}
          testid="storage-compact-message">{message.text}</InlineMessage
        >
      {/if}
      {#if compaction?.error}
        <InlineMessage tone="error" testid="storage-compact-error"
          >{t('storageCompactError', { error: compaction.error })}</InlineMessage
        >
      {:else if compaction?.last_at}
        <p class="caption muted" data-testid="storage-compact-last">
          {t('storageCompactLast', {
            when: when(compaction.last_at),
            size: bytes(compaction.freed_bytes),
          })}
        </p>
      {/if}
    </div>
  {/if}
</Card>

<style>
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(10rem, 45%), 1fr));
    gap: var(--space-2);
  }
  .scroll {
    overflow-x: auto;
    margin: var(--space-2) 0;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th,
  td {
    padding: var(--space-1) var(--space-2) var(--space-1) 0;
    text-align: left;
    vertical-align: top;
    white-space: nowrap;
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
  }
  .tables {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-1);
  }
  .tables li {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--fs-caption);
  }
  .compact {
    margin-top: var(--space-3);
    display: grid;
    gap: var(--space-2);
  }
  .compact p {
    margin: 0;
  }
  .retention {
    margin: 0 0 var(--space-2);
  }
  .retention a {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
  }
</style>
