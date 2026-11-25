<script lang="ts">
  import ModeCard from '$components/system/ModeCard.svelte';
  import Tabs from '$ui/Tabs.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { buildHash, router } from '$lib/core/router.svelte';
  import { t } from '$lib/core/settings.svelte';
  import Health from './Health.svelte';
  import Signals from './Signals.svelte';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const TABS = ['overview', 'signals', 'shadow', 'trial', 'replay', 'data'] as const;
  type Tab = (typeof TABS)[number];
  const active = $derived<Tab>(TABS.find((tab) => tab === router.location.sub[0]) ?? 'overview');
  const items = $derived(
    TABS.map((tab) => ({
      id: tab,
      label: t(`tab_${tab}` as 'tab_overview'),
      href: buildHash('system', tab === 'overview' ? [] : [tab]),
    })),
  );

  const loadShadow = () => import('./Shadow.svelte');
  const loadTrial = () => import('./Trial.svelte');
  const loadReplay = () => import('./Replay.svelte');
  const loadData = () => import('./Data.svelte');
  const loadSystemTiles = () => import('./SystemTiles.svelte');
</script>

<h1>{t('systemTitle')}</h1>

<Tabs {items} {active} label={t('systemTabs')} />

{#if active === 'signals'}
  <Signals {live} />
{:else if active === 'shadow'}
  {#await loadShadow() then page}<page.default {live} {ctl} />{/await}
{:else if active === 'replay'}
  {#await loadReplay() then page}<page.default {live} {ctl} />{/await}
{:else if active === 'data'}
  {#await loadData() then page}<page.default {live} />{/await}
{:else if active === 'trial'}
  {#await loadTrial() then page}<page.default {live} {ctl} />{/await}
{:else}
  <div class="grid">
    <div class="span-6" data-help="system.mode"><ModeCard {ctl} {live} /></div>
    <div class="span-6" data-help="system.health"><Health {live} /></div>
  </div>
  {#await loadSystemTiles() then tiles}<tiles.default {live} {ctl} />{/await}
{/if}
