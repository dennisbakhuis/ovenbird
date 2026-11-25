<!--
  Search results over topics, sections, questions and the glossary.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import type { HelpHit } from '$lib/help/search';
  import { t } from '$lib/core/settings.svelte';

  interface Props {
    hits: HelpHit[];
    query: string;
    onPick: (hit: HelpHit) => void;
  }

  let { hits, query, onPick }: Props = $props();
</script>

<p class="count" role="status">
  {hits.length ? t('helpResults', { n: hits.length }) : t('helpNoResults', { query })}
</p>
{#if hits.length}
  <ul class="hits" data-testid="help-results">
    {#each hits as hit, index (index)}
      <li>
        <Button class="help-res-hit-row" onclick={() => onPick(hit)} data-kind={hit.kind}>
          <span class="where">
            {hit.kind === 'term'
              ? t('helpHitTerm')
              : hit.kind === 'topic'
                ? hit.title
                : hit.context}
          </span>
          {#if hit.kind !== 'topic'}<span class="title">{hit.title}</span>{/if}
          <span class="snippet">{hit.snippet}</span>
        </Button>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .count {
    margin: 0 0 var(--space-2);
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .hits {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .hits li + li {
    margin-top: var(--space-1);
  }
  :global(.help-res-hit-row) {
    display: grid;
    gap: 0.1rem;
    width: 100%;
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  :global(.help-res-hit-row):hover {
    border-color: var(--accent);
  }
  .where {
    color: var(--muted);
    font-size: var(--fs-caption);
    font-weight: var(--fw-bold);
  }
  :global(.help-res-hit-row[data-kind='topic']) .where {
    color: var(--text);
    font-size: var(--fs-body);
  }
  .title {
    font-weight: var(--fw-bold);
  }
  .snippet {
    color: var(--muted);
    font-size: var(--fs-caption);
    line-height: var(--lh-body);
  }
</style>
