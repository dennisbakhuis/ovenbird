<!--
  DownloadCsv: a small "CSV" button that downloads an API journal as CSV (`?format=csv`) for the
  window on screen, with the service's file name. Failures show inline (an older service without
  CSV exports, or a role that may not read the journal).

  Props: path (API path with its window, without `format`), name (fallback file name), label
  (accessible name, e.g. "Download the alarm journal as CSV"), testid; or, for rows the page
  already has (the hold history), table () -> { header, rows } instead of path: saved locally.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import type { FailureKind } from '$lib/core/api';
  import { csvPath, downloadFrom, saveBlob, toCsv } from '$lib/core/download';
  import { t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  type Cell = string | number | null | undefined;

  interface Props {
    path?: string;
    table?: () => { header: string[]; rows: Cell[][] };
    name: string;
    label: string;
    testid?: string;
  }

  let { path, table, name, label, testid }: Props = $props();

  let busy = $state(false);
  let failure = $state<FailureKind | null>(null);

  async function download(): Promise<void> {
    if (table) {
      const { header, rows } = table();
      saveBlob(new Blob([toCsv(header, rows)], { type: 'text/csv;charset=utf-8' }), name);
      return;
    }
    if (!path) return;
    busy = true;
    failure = await downloadFrom(csvPath(path), name);
    busy = false;
  }
</script>

<span class="csv">
  <Button
    size="sm"
    onclick={download}
    disabled={busy}
    aria-label={label}
    title={label}
    data-testid={testid}
  >
    <Icon name="download" size={16} /><span>CSV</span>
  </Button>
  {#if failure}
    <span class="err" role="alert"
      >{failure === 'forbidden' || failure === 'unauthorized'
        ? t('csvForbidden')
        : failure === 'missing' || failure === 'invalid'
          ? t('csvMissing')
          : t('actionFailed')}</span
    >
  {/if}
</span>

<style>
  .csv {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
  }
  .err {
    color: var(--err-text);
    font-size: var(--fs-caption);
  }
</style>
