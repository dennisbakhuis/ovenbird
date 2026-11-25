<!--
  System → Data: what history.db holds and costs (storage card, with "Free space now"), the
  downloads (export card: series, journals and the full archive) and the yearly archive of frozen
  months. Each part loads on its own; an older service without the endpoints gets a calm line
  instead.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import ArchiveCard from '$components/system/ArchiveCard.svelte';
  import ExportCard from '$components/system/ExportCard.svelte';
  import StorageCard from '$components/system/StorageCard.svelte';
  import { fetchArchive, fetchHistorySignals, fetchStorage } from '$lib/core/api';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { t } from '$lib/core/settings.svelte';
  import type { ArchiveStatus, HistorySignals, HistoryStorage } from '$lib/core/types';

  let { live }: { live: LiveStore } = $props();

  type Phase = 'loading' | 'failed' | 'ok';

  const REFRESH_MS = 60_000;

  let storage = $state<HistoryStorage | null>(null);
  let storagePhase = $state<Phase>('loading');
  let signals = $state<HistorySignals | null>(null);
  let signalsPhase = $state<Phase>('loading');
  let archive = $state<ArchiveStatus | null>(null);
  let archivePhase = $state<Phase>('loading');
  let controller: AbortController | null = null;

  async function loadStorage(): Promise<void> {
    const signal = controller?.signal;
    try {
      const body = await fetchStorage(signal);
      if (signal?.aborted) return;
      storage = body;
      storagePhase = 'ok';
    } catch {
      if (!signal?.aborted && storagePhase !== 'ok') storagePhase = 'failed';
    }
  }

  async function loadArchive(): Promise<void> {
    const signal = controller?.signal;
    try {
      const body = await fetchArchive(signal);
      if (signal?.aborted) return;
      archive = body;
      archivePhase = 'ok';
    } catch {
      if (!signal?.aborted && archivePhase !== 'ok') archivePhase = 'failed';
    }
  }

  async function loadSignals(): Promise<void> {
    const signal = controller?.signal;
    try {
      const body = await fetchHistorySignals(signal);
      if (signal?.aborted) return;
      signals = body;
      signalsPhase = 'ok';
    } catch {
      if (!signal?.aborted) signalsPhase = 'failed';
    }
  }

  $effect(() => {
    controller = new AbortController();
    untrack(() => {
      void loadStorage();
      void loadSignals();
      void loadArchive();
    });
    const timer = window.setInterval(() => {
      void loadStorage();
      void loadArchive();
    }, REFRESH_MS);
    return () => {
      controller?.abort();
      window.clearInterval(timer);
    };
  });
</script>

<p class="page-lead muted">{t('dataLead')}</p>

<div class="grid">
  <div class="span-12 stack">
    <StorageCard {storage} phase={storagePhase} onrefresh={() => void loadStorage()} />
  </div>
  <div class="span-12 stack">
    <ExportCard
      signals={signals?.signals ?? null}
      phase={signalsPhase}
      now={Math.floor(live.clock / 60_000) * 60_000}
    />
  </div>
  <div class="span-12 stack">
    <ArchiveCard
      {archive}
      phase={archivePhase}
      now={live.clock}
      onchange={(next) => (archive = next)}
      onrefresh={() => void loadArchive()}
    />
  </div>
</div>
