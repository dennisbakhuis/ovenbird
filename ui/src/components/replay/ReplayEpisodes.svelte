<!--
  ReplayEpisodes: the stretches in which the replayed setpoint lay more than the threshold from
  the pump's target, newest first: when and how long, which way and how far, the replayed,
  recorded and pump values at the largest difference, the replayed reason and how the episode
  ended. The first few show; the rest sit behind a disclosure.

  Props: episodes (oldest first, as the API sends them), total (episodes_total), thresholdK, now.
-->
<script lang="ts">
  import Details from '$ui/Details.svelte';
  import Pill from '$ui/Pill.svelte';
  import { celsius } from '$lib/core/controlText';
  import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import type { ReplayEpisode } from '$lib/replay/replay';
  import { direction } from '$lib/shadow/shadow';

  interface Props {
    episodes: ReplayEpisode[];
    total: number;
    thresholdK: number;
    now: number;
  }

  let { episodes, total, thresholdK, now }: Props = $props();

  const FIRST = 4;
  const lang = $derived(settings.language);
  const newest = $derived([...episodes].reverse());
  const head = $derived(newest.slice(0, FIRST));
  const rest = $derived(newest.slice(FIRST));
  const when = (iso: string) => formatDateTime(iso, lang, now);
  const temp = (value: number | null) => (value === null ? '–' : celsius(value, lang, 0));
  const endTone = (end: ReplayEpisode['ended_by']) =>
    end === 'open' ? 'warn' : end === 'gap' ? 'unknown' : 'good';
</script>

{#snippet item(ep: ReplayEpisode)}
  {@const dir = direction(ep.max_diff_k)}
  <li data-testid="replay-episode" data-end={ep.ended_by}>
    <div class="head">
      <strong>{when(ep.start)} – {when(ep.end)}</strong>
      <span class="muted">{formatDuration(ep.minutes * 60, lang)}</span>
      <Pill tone={endTone(ep.ended_by)}>{t(`shadowEnd_${ep.ended_by}`)}</Pill>
    </div>
    <p class="diff">
      <span class="dir {dir}">
        {t(`replayEpisodeDiff_${dir}`, { k: formatNumber(ep.max_abs_k, 1, lang) })}
      </span>
      <span class="muted">
        {t('replayEpisodeValues', {
          replayed: temp(ep.ovenbird_c),
          recorded: temp(ep.recorded_c),
          pump: temp(ep.pump_c),
        })}
      </span>
    </p>
    {#if ep.reason}
      <p class="caption muted">
        {t('replayEpisodeReason', { reason: tc('reason_', ep.reason) })}
        {#if ep.reason_at_max && ep.reason_at_max !== ep.reason}
          · {t('replayEpisodeReasonAtMax', { reason: tc('reason_', ep.reason_at_max) })}
        {/if}
      </p>
    {/if}
  </li>
{/snippet}

<div class="episodes" data-testid="replay-episodes">
  {#if episodes.length === 0}
    <p class="muted" data-testid="replay-episodes-none">
      {t('replayEpisodesNone', { k: formatNumber(thresholdK, 1, lang) })}
    </p>
  {:else}
    <ul>
      {#each head as ep (ep.start)}{@render item(ep)}{/each}
    </ul>
    {#if rest.length}
      <Details summary={t('replayEpisodesOlder', { n: rest.length })} testid="replay-episodes-more">
        <ul>
          {#each rest as ep (ep.start)}{@render item(ep)}{/each}
        </ul>
      </Details>
    {/if}
    {#if total > episodes.length}
      <p class="caption muted">
        {t('replayEpisodesCapped', { shown: episodes.length, total })}
      </p>
    {/if}
  {/if}
</div>

<style>
  .episodes {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
  }
  ul {
    display: grid;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: grid;
    gap: var(--space-1);
    padding-bottom: var(--space-3);
    border-bottom: 1px solid var(--border);
  }
  li:last-child {
    border-bottom: none;
    padding-bottom: 0;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
  }
  p {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .diff {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-2);
  }
  .dir {
    font-weight: var(--fw-semibold);
  }
</style>
