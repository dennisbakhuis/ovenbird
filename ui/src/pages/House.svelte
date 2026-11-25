<!--
  House: what the learned house model says. The indicative insulation score, the other learned
  figures, the energy signature, the curve suggestion (opened as a settings draft, never applied
  here) and the model's quality. Before a model exists, or on an older service, one card says so.
  Loads insight/house and insight/house/history, refreshed every 30 minutes.
-->
<script lang="ts">
  import FactsCard from '$components/house/FactsCard.svelte';
  import LearningCard from '$components/house/LearningCard.svelte';
  import ProposalCard from '$components/house/ProposalCard.svelte';
  import QualityCard from '$components/house/QualityCard.svelte';
  import ScoreCard from '$components/house/ScoreCard.svelte';
  import SignatureChart from '$components/house/SignatureChart.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import {
    fetchHouse,
    fetchHouseHistory,
    type HouseHistory,
    type HouseResult,
  } from '$lib/house/house';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { t } from '$lib/core/settings.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const REFRESH_MS = 1_800_000;

  let result = $state<HouseResult | null>(null);
  let history = $state<HouseHistory | null>(null);
  let failed = $state(false);

  $effect(() => {
    void live.configVersion;
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        const [house, models] = await Promise.all([
          fetchHouse(controller.signal),
          fetchHouseHistory(controller.signal).catch(() => null),
        ]);
        result = house;
        history = models;
        failed = false;
      } catch {
        if (controller.signal.aborted) return;
        failed = result === null;
      }
      timer = window.setTimeout(load, REFRESH_MS);
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  });
</script>

<h1>{t('houseTitle')}</h1>
<p class="lead muted">{t('houseLead')}</p>

{#if failed}
  <LearningCard kind="failed" />
{:else if result === null}
  <p class="muted" data-testid="house-loading">{t('loading')}</p>
{:else if result.kind === 'missing'}
  <LearningCard kind="missing" />
{:else if result.kind === 'learning'}
  <LearningCard
    kind={result.data.state === 'not_run' ? 'not_run' : 'learning'}
    data={result.data}
  />
{:else}
  <div class="grid" data-testid="house-page">
    <ScoreCard house={result.data} />
    <FactsCard house={result.data} />
    <SignatureChart house={result.data} />
    <ProposalCard house={result.data} {ctl} />
    <QualityCard house={result.data} {history} />
  </div>
{/if}

<style>
  .lead {
    margin: calc(-1 * var(--space-2)) 0 var(--space-4);
    max-width: 48rem;
  }
</style>
