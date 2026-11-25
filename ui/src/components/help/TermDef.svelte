<!--
  An opened glossary definition: the term in bold, its short text and "More", which opens
  the full entry in the drawer.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { plainText } from '$lib/help/markup';
  import { t } from '$lib/core/settings.svelte';
  import { useGlossary } from './context';

  let { id, uid }: { id: string; uid: string } = $props();

  const glossary = useGlossary();
  const entry = $derived(glossary?.get(id));
</script>

{#if entry && glossary}<span class="def" id={uid} role="note" data-testid="help-term-def"
    ><strong>{entry.term}</strong>
    {plainText(entry.short)}
    <Button class="termdef-more" onclick={() => glossary.more(id)} data-testid="help-term-more"
      >{t('helpTermMore')}</Button
    ></span
  >{/if}

<style>
  .def {
    display: block;
    margin: var(--space-1) 0 var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-left: 3px solid var(--accent);
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    background: var(--surface-2);
    font-size: var(--fs-body);
  }
  :global(.termdef-more) {
    display: inline;
    min-height: 0;
    padding: 0;
    border: none;
    background: none;
    color: var(--accent);
    font: inherit;
    font-weight: var(--fw-semibold);
    text-decoration: underline;
    cursor: pointer;
  }
  @media (--narrow), (pointer: coarse) {
    :global(.termdef-more) {
      display: inline-block;
      min-height: 0;
      padding: 0.6rem var(--space-1);
      margin: -0.6rem 0;
    }
  }
</style>
