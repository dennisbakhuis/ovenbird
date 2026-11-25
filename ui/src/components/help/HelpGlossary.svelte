<!--
  The glossary: every term with its short definition, or one entry with its longer text and
  related terms.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { plainText } from '$lib/help/markup';
  import type { GlossaryEntry } from '$lib/help/types';
  import { t } from '$lib/core/settings.svelte';
  import HelpText from './HelpText.svelte';

  interface Props {
    entries: GlossaryEntry[];
    entry?: string;
    onEntry: (id: string) => void;
  }

  let { entries, entry, onEntry }: Props = $props();

  const current = $derived(entry ? entries.find((e) => e.id === entry) : undefined);
  const related = $derived(
    (current?.related ?? [])
      .map((id) => entries.find((e) => e.id === id))
      .filter((e): e is GlossaryEntry => e !== undefined),
  );
</script>

{#if current}
  <div class="entry" data-testid="help-glossary-entry" data-term={current.id}>
    {#if current.body}<HelpText body={current.body} />{/if}
    {#if related.length}
      <h3>{t('helpSeeAlso')}</h3>
      <ul class="chips">
        {#each related as other (other.id)}
          <li>
            <Button class="glos-chip" onclick={() => onEntry(other.id)}>{other.term}</Button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{:else}
  <dl class="list" data-testid="help-glossary">
    {#each entries as item (item.id)}
      <div>
        <dt>
          <Button class="glos-term" onclick={() => onEntry(item.id)}>{item.term}</Button>
        </dt>
        <dd>{plainText(item.short)}</dd>
      </div>
    {/each}
  </dl>
{/if}

<style>
  h3 {
    margin: var(--space-5) 0 var(--space-2);
    color: var(--muted);
    font-size: var(--fs-caption);
    font-weight: var(--fw-bold);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .entry {
    line-height: var(--lh-body);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  :global(.glos-chip) {
    min-height: 36px;
    padding: 0 0.8rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface);
    color: var(--text);
    font-weight: var(--fw-semibold);
  }
  :global(.glos-chip):hover {
    border-color: var(--accent);
    color: var(--accent);
  }
  .list {
    margin: 0;
  }
  .list > div {
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .list > div:last-child {
    border-bottom: none;
  }
  dt {
    margin: 0;
  }
  dd {
    margin: 0.15rem 0 0;
    color: var(--muted);
    line-height: var(--lh-body);
  }
  :global(.glos-term) {
    min-height: 0;
    padding: 0;
    border: none;
    background: none;
    color: var(--accent);
    font: inherit;
    font-weight: var(--fw-bold);
    text-align: left;
    cursor: pointer;
  }
  :global(.glos-term):hover {
    text-decoration: underline;
  }
  @media (--narrow), (pointer: coarse) {
    :global(.glos-chip) {
      min-height: var(--tap);
    }
    :global(.glos-term) {
      min-height: 32px;
    }
  }
</style>
