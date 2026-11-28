<!--
  House: the heat loss of the house now, the heat the heat pump gives it, how the heat loss was
  measured and the heat production by outside temperature, then (last) the facts about the house
  (the owner's answers, editable). Facts go through the settings draft and the draft bar.
-->
<script lang="ts">
  import HouseBasics from '$components/house/HouseBasics.svelte';
  import HouseInputCard from '$components/house/HouseInputCard.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { t } from '$lib/core/settings.svelte';

  let { ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const schema = $derived(cfg.schema);
  const config = $derived(ctl.config);

  $effect(() => {
    void cfg.loadSchema();
  });
</script>

<h1>{t('houseTitle')}</h1>
<p class="lead muted">{t('houseLead')}</p>

<div class="grid" data-testid="house-page">
  <HouseBasics />
  {#if schema && config}
    <HouseInputCard {schema} {config} />
  {/if}
</div>

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
