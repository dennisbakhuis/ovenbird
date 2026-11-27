<!--
  House: what the learned house model says, in three tabs. Overview: the indicative insulation
  score, the other learned figures and a line about the model in use. Model: the energy signature
  and the model's quality. Learning: the learner and its run now button, how the model is learned
  (errors, left-out periods, data) and the curve suggestion (opened as a settings draft, never
  applied here). Before a model exists the page shows what is missing and the learner; on an
  older service one card says so. Loads insight/house and insight/house/history, refreshed
  every 30 minutes and after a learner run.
-->
<script lang="ts">
  import FactsCard from '$components/house/FactsCard.svelte';
  import HouseSchematic from '$components/house/HouseSchematic.svelte';
  import PredictionChart from '$components/house/PredictionChart.svelte';
  import WhatIfCard from '$components/house/WhatIfCard.svelte';
  import HouseInputCard from '$components/house/HouseInputCard.svelte';
  import LearningCard from '$components/house/LearningCard.svelte';
  import ProposalCard from '$components/house/ProposalCard.svelte';
  import QualityCard from '$components/house/QualityCard.svelte';
  import RunCard from '$components/house/RunCard.svelte';
  import ScoreCard from '$components/house/ScoreCard.svelte';
  import SignatureChart from '$components/house/SignatureChart.svelte';
  import StatusLine from '$components/house/StatusLine.svelte';
  import TimelineCard from '$components/house/TimelineCard.svelte';
  import Tabs from '$ui/Tabs.svelte';
  import { fetchVersions } from '$lib/core/api';
  import { fetchHouseBalance, type BalanceResult } from '$lib/house/balance';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import {
    fetchHouse,
    fetchHouseHistory,
    type HouseHistory,
    type HouseResult,
  } from '$lib/house/house';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { buildHash, router } from '$lib/core/router.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { t } from '$lib/core/settings.svelte';
  import { SUBSET_GROUP, changedSinceRun, modelMadeAt, type Subset } from '$lib/house/settings';
  import type { ConfigVersion } from '$lib/core/types';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const REFRESH_MS = 1_800_000;
  const BALANCE_REFRESH_MS = 60_000;
  const TABS = ['overview', 'model', 'learning', 'what-if'] as const;
  type Tab = (typeof TABS)[number];

  const active = $derived<Tab>(TABS.find((tab) => tab === router.location.sub[0]) ?? 'overview');
  const items = $derived(
    TABS.filter((tab) => tab !== 'what-if' || balance?.kind !== 'absent').map((tab) => ({
      id: tab,
      label: t(`houseTab_${tab}` as 'houseTab_overview'),
      href: buildHash('house', tab === 'overview' ? [] : [tab]),
    })),
  );

  let result = $state<HouseResult | null>(null);
  let history = $state<HouseHistory | null>(null);
  let failed = $state(false);
  let reload = $state(0);
  let versions = $state<ConfigVersion[]>([]);
  let balance = $state<BalanceResult | null>(null);
  let balanceFailed = $state(false);

  function openFacts(): void {
    document
      .querySelector('[data-testid="house-facts-input"]')
      ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  $effect(() => {
    void live.configVersion;
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async () => {
      try {
        balance = await fetchHouseBalance(controller.signal);
        balanceFailed = false;
      } catch {
        if (controller.signal.aborted) return;
        balanceFailed = true;
      }
      timer = window.setTimeout(load, BALANCE_REFRESH_MS);
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  });

  $effect(() => {
    void cfg.loadSchema();
  });

  $effect(() => {
    void live.configVersion;
    void ctl.config?.version;
    const controller = new AbortController();
    fetchVersions(10, controller.signal)
      .then((body) => (versions = body.versions))
      .catch(() => {
        if (!controller.signal.aborted) versions = [];
      });
    return () => controller.abort();
  });

  const comfortC = $derived.by(() => {
    const value = ctl.config?.fields['control_comfort_c']?.value;
    return typeof value === 'number' ? value : 21;
  });
  const schema = $derived(cfg.schema);
  const config = $derived(ctl.config);
  const available = (subset: Subset) =>
    schema !== null &&
    config !== null &&
    Object.values(schema.fields).some((def) => def.group === SUBSET_GROUP[subset]);
  const changedSince = $derived(
    changedSinceRun(versions, modelMadeAt(result?.kind === 'ready' ? result.data : null)),
  );

  $effect(() => {
    void live.configVersion;
    void reload;
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
  <div class="grid">
    {#if balance?.kind !== 'absent'}
      <HouseSchematic {balance} failed={balanceFailed} onfacts={openFacts} />
    {/if}
    <LearningCard
      kind={result.data.state === 'not_run' ? 'not_run' : 'learning'}
      data={result.data}
    />
    {#if available('facts') && schema && config}
      <HouseInputCard subset="facts" {schema} {config} showRun={false} />
    {/if}
    <RunCard waiting onsettled={() => (reload += 1)} />
  </div>
{:else}
  <Tabs {items} {active} label={t('houseTabs')} />
  {#if active === 'model'}
    <div class="grid" data-testid="house-page" data-tab="model">
      <SignatureChart house={result.data} />
      <PredictionChart />
      <QualityCard house={result.data} {history} />
      {#if available('bounds') && schema && config}
        <HouseInputCard
          subset="bounds"
          {schema}
          {config}
          house={result.data}
          {changedSince}
          onstarted={() => (reload += 1)}
        />
      {/if}
    </div>
  {:else if active === 'learning'}
    <div class="grid" data-testid="house-page" data-tab="learning">
      <RunCard credibility={result.data.credibility} onsettled={() => (reload += 1)} />
      {#if available('learning') && schema && config}
        <HouseInputCard
          subset="learning"
          {schema}
          {config}
          house={result.data}
          {changedSince}
          showRun={false}
        />
      {/if}
      <TimelineCard house={result.data} {schema} {config} />
      <ProposalCard house={result.data} {ctl} />
    </div>
  {:else if active === 'what-if'}
    <div class="grid" data-testid="house-page" data-tab="what-if">
      <WhatIfCard {comfortC} onoverview={() => router.navigate('house')} />
    </div>
  {:else}
    <StatusLine house={result.data} />
    <div class="grid" data-testid="house-page" data-tab="overview">
      {#if balance?.kind !== 'absent'}
        <HouseSchematic {balance} failed={balanceFailed} onfacts={openFacts} />
      {/if}
      <ScoreCard house={result.data} />
      <FactsCard house={result.data} />
      {#if available('facts') && schema && config}
        <HouseInputCard
          subset="facts"
          {schema}
          {config}
          house={result.data}
          {changedSince}
          onstarted={() => (reload += 1)}
        />
      {/if}
    </div>
  {/if}
{/if}

{#if draft.count > 0}<div class="spacer" aria-hidden="true"></div>{/if}

<style>
  .spacer {
    height: 4.5rem;
  }
  .lead {
    margin: calc(-1 * var(--space-2)) 0 var(--space-4);
    max-width: 48rem;
  }
</style>
