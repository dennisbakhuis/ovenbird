<script lang="ts">
  import type { Inline } from '$lib/help/markup';
  import HelpInline from './HelpInline.svelte';
  import Term from './Term.svelte';
  import type { TermSlot } from './termSlot';

  let { nodes, slot }: { nodes: Inline[]; slot?: TermSlot } = $props();
</script>

{#each nodes as node, index (index)}{#if node.kind === 'text'}{node.text}{:else if node.kind === 'bold'}<strong
      ><HelpInline nodes={node.children} {slot} /></strong
    >{:else if node.kind === 'term'}<Term id={node.id} text={node.text} {slot} />{:else}<a
      class="help-link"
      href={node.href}>{node.text}</a
    >{/if}{/each}
