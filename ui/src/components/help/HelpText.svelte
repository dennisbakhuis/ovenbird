<!--
  Renders help markup (lib/help/markup.ts) as nodes: paragraphs, lists, bold, glossary terms
  and in-app links. Never HTML.
-->
<script lang="ts">
  import { parseBody } from '$lib/help/markup';
  import HelpInline from './HelpInline.svelte';
  import TermDef from './TermDef.svelte';
  import type { TermSlot } from './termSlot';

  let { body }: { body: string } = $props();

  const blocks = $derived(parseBody(body));
  const uid = `term-${Math.random().toString(36).slice(2, 8)}`;
  let opened = $state<{ block: number; id: string } | null>(null);

  function slotFor(block: number): TermSlot {
    return {
      get openId() {
        return opened?.block === block ? opened.id : null;
      },
      controls: `${uid}-${block}`,
      toggle: (id: string) => {
        opened = opened?.block === block && opened.id === id ? null : { block, id };
      },
    };
  }
</script>

<div class="help-text">
  {#each blocks as block, index (index)}
    {#if block.kind === 'p'}
      <p><HelpInline nodes={block.content} slot={slotFor(index)} /></p>
    {:else}
      <ul>
        {#each block.items as item, i (i)}<li>
            <HelpInline nodes={item} slot={slotFor(index)} />
          </li>{/each}
      </ul>
    {/if}
    {#if opened?.block === index}<TermDef id={opened.id} uid="{uid}-{index}" />{/if}
  {/each}
</div>

<style>
  .help-text :global(p),
  .help-text :global(ul) {
    margin: 0 0 var(--space-2);
  }
  .help-text :global(:last-child) {
    margin-bottom: 0;
  }
  .help-text ul {
    padding-left: 1.2rem;
  }
  .help-text li + li {
    margin-top: 0.2rem;
  }
  .help-text :global(.help-link) {
    color: var(--accent);
    font-weight: var(--fw-semibold);
  }
</style>
