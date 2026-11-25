<script lang="ts">
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import SignalRow from '$components/activity/SignalRow.svelte';
  import { MediaQuery } from 'svelte/reactivity';
  import Details from '$ui/Details.svelte';
  import { hotWater } from '$lib/core/hotWater.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { t, tOpt } from '$lib/core/settings.svelte';
  import {
    freshness,
    humanizeId,
    isHotWaterSignal,
    isInternalSignal,
    shortId,
    signalGroup,
    SIGNAL_GROUPS,
    type SignalGroup,
  } from '$lib/core/signalView';
  import type { Signal } from '$lib/core/types';

  let { live }: { live: LiveStore } = $props();

  let query = $state('');
  let onlyAttention = $state(false);

  const COLLAPSED: SignalGroup[] = ['settings', 'other'];
  const PHONE_OPEN_ROWS = 8;
  const phone = new MediaQuery('max-width: 640px', false);
  const collapsed = (group: SignalGroup, rows: number) =>
    COLLAPSED.includes(group) || (phone.current && rows > PHONE_OPEN_ROWS);
  const filtering = $derived(query.trim() !== '' || onlyAttention);

  const all = $derived(live.snapshot?.signals ?? {});
  const visible = $derived(
    Object.entries(all).filter(
      ([id]) => !isInternalSignal(id) && (hotWater.shown || !isHotWaterSignal(id)),
    ),
  );

  const nameOf = (id: string) => tOpt(`sig_${shortId(id)}`) ?? humanizeId(id);

  const matches = $derived.by(() => {
    const needle = query.trim().toLowerCase();
    return visible.filter(([id, s]) => {
      if (onlyAttention && freshness(s) === 'fresh') return false;
      if (!needle) return true;
      return [id, nameOf(id), s.label ?? '', s.source, String(s.value)].some((part) =>
        part.toLowerCase().includes(needle),
      );
    });
  });

  const groups = $derived.by(() => {
    const out: { group: SignalGroup; rows: [string, Signal][] }[] = [];
    for (const group of SIGNAL_GROUPS) {
      const rows = matches
        .filter(([id, s]) => signalGroup(id, s) === group)
        .sort(([a], [b]) => nameOf(a).localeCompare(nameOf(b)));
      if (rows.length > 0) out.push({ group, rows });
    }
    return out;
  });
</script>

<div class="toolbar" data-help="system/signals.toolbar">
  <label class="search">
    <span class="visually-hidden">{t('search')}</span>
    <TextInput width="100%" type="search" bind:value={query} placeholder={t('search')} />
  </label>
  <Button
    class="signals-chip"
    aria-pressed={onlyAttention}
    data-testid="signals-attention"
    onclick={() => (onlyAttention = !onlyAttention)}
  >
    {t('signalsAttention')}
  </Button>
  <p class="muted count" aria-live="polite">
    {t('signalCount', { shown: matches.length, total: visible.length })}
  </p>
</div>

{#snippet rowList(rows: [string, Signal][])}
  <ul>
    {#each rows as [id, signal] (id)}
      <SignalRow {id} {signal} {all} receivedAt={live.receivedAt} now={live.now} />
    {/each}
  </ul>
{/snippet}

<div class="groups" data-testid="signals-table" data-help="system/signals.groups">
  {#each groups as { group, rows } (group)}
    {@const label = t(`signalGroup_${group}` as 'signalGroup_room')}
    <Card bare class="signals-group" data-group={group} aria-label={label}>
      {#if collapsed(group, rows.length)}
        <Details
          id="signals-group-{group}"
          summary={label}
          meta={rows.length}
          open={filtering}
          testid="signals-group-{group}"
        >
          {@render rowList(rows)}
        </Details>
      {:else}
        <h2>{label}</h2>
        {@render rowList(rows)}
      {/if}
    </Card>
  {:else}
    <p class="muted">{t('noMatches')}</p>
  {/each}
</div>

<style>
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    margin: var(--space-3) 0;
  }
  .search {
    flex: 1 1 14rem;
  }
  :global(.signals-chip[aria-pressed='true']) {
    background: var(--status-manual-bg);
    border-color: var(--status-manual);
    font-weight: var(--fw-semibold);
  }
  .count {
    margin: 0;
    font-size: var(--fs-caption);
  }
  .groups {
    display: grid;
    gap: var(--space-2);
  }
  :global(.signals-group) {
    padding-block: var(--space-2);
    container: sigcard / inline-size;
  }
  @media (--wide) {
    .groups {
      display: block;
      columns: 2;
      column-gap: var(--space-3);
    }
    :global(.signals-group) {
      break-inside: avoid;
      margin-bottom: var(--space-3);
    }
  }
  h2 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-emph);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
</style>
