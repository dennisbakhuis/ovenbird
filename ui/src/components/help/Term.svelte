<!--
  A glossary term inside a help text: a dotted-underlined button. Inside a HelpText the
  definition opens below the paragraph (the slot); elsewhere it unfolds in place. Unknown
  ids stay text.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { useGlossary } from './context';
  import type { TermSlot } from './termSlot';
  import TermDef from './TermDef.svelte';

  let { id, text, slot }: { id: string; text: string; slot?: TermSlot } = $props();

  const glossary = useGlossary();
  const entry = $derived(glossary?.get(id));
  const uid = `term-${Math.random().toString(36).slice(2, 8)}`;
  let local = $state(false);
  const open = $derived(slot ? slot.openId === id : local);
  const controls = $derived(slot ? slot.controls : uid);

  function toggle(): void {
    if (slot) slot.toggle(id);
    else local = !local;
  }
</script>

{#if entry && glossary}<Button
    class="term-term"
    aria-expanded={open}
    aria-controls={open ? controls : undefined}
    onclick={toggle}
    data-testid="help-term"
    data-term={id}>{text}</Button
  >{#if open && !slot}<TermDef {id} {uid} />{/if}{:else}{text}{/if}

<style>
  :global(.term-term) {
    display: inline;
    min-height: 0;
    padding: 0;
    margin: 0;
    border: none;
    border-radius: var(--radius-2xs);
    background: none;
    color: inherit;
    font: inherit;
    text-decoration: underline dotted;
    text-decoration-color: var(--accent);
    text-decoration-thickness: 2px;
    text-underline-offset: 3px;
    cursor: help;
  }
  :global(.term-term):hover,
  :global(.term-term[aria-expanded='true']) {
    color: var(--accent);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.term-term) {
      min-height: 0;
    }
  }
</style>
