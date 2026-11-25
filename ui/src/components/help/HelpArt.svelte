<!--
  The illustration slot of the drawer. Drawings come from components/art (loaded on demand);
  the slot stays empty when that package is not there.
-->
<script lang="ts">
  import type { Component } from 'svelte';
  import type { ArtName } from '$lib/help/types';

  type ArtModule = { loadArt: (name: ArtName) => Promise<Component> };

  const modules = import.meta.glob<ArtModule>('$components/art/index.ts');
  const loadIndex = Object.values(modules)[0];

  let { name }: { name: ArtName } = $props();

  let Art = $state<Component | null>(null);

  $effect(() => {
    const wanted = name;
    let current = true;
    if (!loadIndex) return;
    loadIndex()
      .then((module) => module.loadArt(wanted))
      .then((component) => {
        if (current) Art = component;
      })
      .catch(() => {
        if (current) Art = null;
      });
    return () => {
      current = false;
    };
  });
</script>

{#if loadIndex}
  <div class="art-slot" aria-hidden="true" data-art={name}>
    {#if Art}<Art />{/if}
  </div>
{/if}

<style>
  .art-slot {
    height: 7.5rem;
    margin: 0 0 var(--space-3);
    border-radius: var(--radius);
    background: var(--brand-ground);
    overflow: hidden;
  }
  .art-slot :global(svg) {
    display: block;
    width: 100%;
    height: 100%;
  }
</style>
