<!--
  HouseBasics: the heat-loss and heat-pump part of the House page. Loads api/v1/insight/basics
  (refreshed every minute) and shows the state it is in: loading, request error, older service,
  off, collecting, provisional or credible.

  Props: none.
-->
<script lang="ts">
  import { basicsView } from '$lib/house/basics';
  import BasicsStates from './BasicsStates.svelte';
  import ByWeatherCard from './ByWeatherCard.svelte';
  import HeatPumpCard from './HeatPumpCard.svelte';
  import LossFitCard from './LossFitCard.svelte';
  import LossNowCard from './LossNowCard.svelte';
  import { createBasics } from '$lib/house/useBasics.svelte';

  const basics = createBasics();
  $effect(() => basics.start());

  const data = $derived(basics.state.data);
  const view = $derived(data ? basicsView(data) : null);
</script>

{#if basics.state.phase === 'loading'}
  <BasicsStates kind="loading" />
{:else if basics.state.phase === 'failed'}
  <BasicsStates kind="failed" onretry={basics.retry} />
{:else if basics.state.phase === 'missing'}
  <BasicsStates kind="missing" />
{:else if data && view === 'disabled'}
  <BasicsStates kind="disabled" />
{:else if data && view}
  {#if view === 'collecting'}
    <BasicsStates kind="collecting" {data} />
  {:else}
    <LossNowCard {data} />
  {/if}
  {#if data.heat_pump}<HeatPumpCard {data} span={view === 'collecting' ? 12 : 7} />{/if}
  {#if view !== 'collecting'}<LossFitCard {data} />{/if}
  {#if data.by_weather}<ByWeatherCard bins={data.by_weather} />{/if}
{/if}
