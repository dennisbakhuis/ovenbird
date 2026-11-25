<!--
  EpisodeList: the stretches in which ovenbird and the pump were more than the threshold apart,
  newest first: when and how long, which way and how far ovenbird would have differed, both
  values at the largest difference, ovenbird's reason (at the start and at the largest
  difference), who wrote the pump and how the episode ended. The first few show; the rest sit
  behind a "Show older episodes" disclosure. An administrator can mark an episode as explained
  with a short note (the checklist then stops counting it) or remove the mark.

  Props: episodes (oldest first, as the API sends them), total (episodes_total), thresholdK, now.
-->
<script lang="ts">
  import ActionRow from '$ui/ActionRow.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import { failureKind } from '$lib/core/api';
  import { celsius } from '$lib/core/controlText';
  import { explainEpisode, type EpisodeExplanation } from '$lib/trial/trial';
  import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';
  import { direction, type DivergenceEpisode } from '$lib/shadow/shadow';
  import Details from '$ui/Details.svelte';
  import Pill from '$ui/Pill.svelte';

  interface Props {
    episodes: DivergenceEpisode[];
    total: number;
    thresholdK: number;
    now: number;
  }

  let { episodes, total, thresholdK, now }: Props = $props();

  const FIRST = 3;
  const lang = $derived(settings.language);
  const newest = $derived([...episodes].reverse());
  const head = $derived(newest.slice(0, FIRST));
  const rest = $derived(newest.slice(FIRST));
  const when = (iso: string) => formatDateTime(iso, lang, now);
  const temp = (value: number | null) => (value === null ? '–' : celsius(value, lang));
  const writer = (value: DivergenceEpisode['writer']) =>
    t(
      value === 'ovenbird' || value === 'other'
        ? `shadowWriterBy_${value}`
        : 'shadowWriterBy_unknown',
    );
  const endTone = (end: DivergenceEpisode['ended_by']) =>
    end === 'open' ? 'warn' : end === 'gap' ? 'unknown' : 'good';

  let marks = $state<Record<string, EpisodeExplanation | null>>({});
  let editing = $state<string | null>(null);
  let note = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  const explanation = (ep: DivergenceEpisode) =>
    ep.start in marks ? marks[ep.start] : (ep.explained ?? null);

  function edit(ep: DivergenceEpisode): void {
    editing = ep.start;
    note = '';
    error = null;
  }

  async function save(start: string, text: string | null): Promise<void> {
    busy = true;
    error = null;
    try {
      const result = await explainEpisode(start, text);
      marks = { ...marks, [start]: result.explained };
      editing = null;
    } catch (failure) {
      const kind = failureKind(failure);
      error =
        kind === 'forbidden' || kind === 'unauthorized'
          ? t('shadowExplainForbidden')
          : t('shadowExplainFailed');
    }
    busy = false;
  }
</script>

{#snippet item(ep: DivergenceEpisode)}
  {@const dir = direction(ep.max_diff_k)}
  {@const mark = explanation(ep)}
  <li data-testid="shadow-episode" data-end={ep.ended_by}>
    <div class="head">
      <strong class="span">
        {#if ep.ended_by === 'open'}
          {t('shadowEpisodeOpen', { from: when(ep.start) })}
        {:else}
          {when(ep.start)} – {when(ep.end)}
        {/if}
      </strong>
      <span class="duration">{formatDuration(ep.minutes * 60, lang)}</span>
      <Pill tone={endTone(ep.ended_by)}>{t(`shadowEnd_${ep.ended_by}`)}</Pill>
    </div>
    <p class="diff">
      <span class="dir {dir}">
        {t(`shadowEpisodeDiff_${dir}`, { k: formatNumber(ep.max_abs_k, 1, lang) })}
      </span>
      <span class="muted"
        >{t('shadowEpisodeValues', { ovenbird: temp(ep.ovenbird_c), pump: temp(ep.pump_c) })}</span
      >
    </p>
    <p class="caption muted">
      {#if ep.reason}{t('shadowEpisodeReason', { reason: tc('reason_', ep.reason) })}{/if}
      {#if ep.reason_at_max && ep.reason_at_max !== ep.reason}
        · {t('shadowEpisodeReasonAtMax', { reason: tc('reason_', ep.reason_at_max) })}
      {/if}
      · {t('shadowEpisodeWriter', { writer: writer(ep.writer) })}
    </p>
    {#if mark}
      <p class="explained" data-testid="shadow-episode-explained">
        <Icon name="check" size={16} />
        <span
          >{t('shadowExplained', { note: mark.note ?? '' })}
          <span class="caption muted">{mark.by ? `${mark.by}, ` : ''}{when(mark.at ?? '')}</span
          ></span
        >
        <Button
          variant="link"
          class="ep-link"
          onclick={() => save(ep.start, null)}
          disabled={busy}
          data-testid="shadow-explain-remove">{t('shadowExplainRemove')}</Button
        >
      </p>
    {:else if editing === ep.start}
      <form
        class="explain"
        data-testid="shadow-explain-form"
        onsubmit={(event) => {
          event.preventDefault();
          if (note.trim()) void save(ep.start, note.trim());
        }}
      >
        <label>
          <span class="caption">{t('shadowExplainNote')}</span>
          <TextInput
            type="text"
            maxlength={500}
            bind:value={note}
            placeholder={t('shadowExplainPlaceholder')}
            data-testid="shadow-explain-note"
          />
        </label>
        <ActionRow>
          <Button
            type="submit"
            variant="primary"
            disabled={busy || !note.trim()}
            data-testid="shadow-explain-save">{t('shadowExplainSave')}</Button
          >
          <Button onclick={() => (editing = null)} disabled={busy}>{t('cancel')}</Button>
        </ActionRow>
      </form>
    {:else}
      <p>
        <Button variant="link" class="ep-link" onclick={() => edit(ep)} data-testid="shadow-explain"
          >{t('shadowExplain')}</Button
        >
      </p>
    {/if}
    {#if error && (editing === ep.start || mark)}
      <p class="error caption" role="alert">{error}</p>
    {/if}
  </li>
{/snippet}

{#if episodes.length === 0}
  <p class="muted" data-testid="shadow-episodes-none">
    {t('shadowEpisodesNone', { k: formatNumber(thresholdK, 1, lang) })}
  </p>
{:else}
  {#if total > episodes.length}
    <p class="caption muted">{t('shadowEpisodesCapped', { shown: episodes.length, total })}</p>
  {/if}
  <ul class="episodes" data-testid="shadow-episode-list">
    {#each head as ep (ep.start)}{@render item(ep)}{/each}
  </ul>
  {#if rest.length > 0}
    <Details summary={t('shadowEpisodesMore', { n: rest.length })} testid="shadow-episodes-more">
      <ul class="episodes">
        {#each rest as ep (ep.start)}{@render item(ep)}{/each}
      </ul>
    </Details>
  {/if}
{/if}

<style>
  .episodes {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
  }
  li {
    display: grid;
    gap: 0.2rem;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
    min-width: 0;
  }
  li:last-child {
    border-bottom: none;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-3);
  }
  .duration {
    font-variant-numeric: tabular-nums;
    color: var(--muted);
  }
  p {
    margin: 0;
  }
  .diff {
    display: flex;
    flex-wrap: wrap;
    gap: 0 var(--space-3);
  }
  .dir {
    font-weight: var(--fw-semibold);
  }
  .explained {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    color: var(--status-ok);
  }
  .explained > span {
    color: var(--text);
  }
  .explain {
    display: grid;
    gap: var(--space-1);
    max-width: 32rem;
  }
  .explain label {
    display: grid;
    gap: 0.2rem;
  }
  :global(.ep-link) {
    text-decoration: underline;
    min-height: var(--tap);
  }
  .error {
    color: var(--status-stopped);
  }
</style>
