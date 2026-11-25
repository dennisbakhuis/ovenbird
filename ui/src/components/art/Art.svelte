<!--
  Art: one drawing, loaded on demand. The box keeps the drawing's 300 × 180 shape while it
  loads, so nothing jumps. Decorative: the text around it carries the meaning.

  Props: name (ArtName), width (CSS length, default 100%).
-->
<script lang="ts">
  import type { ArtName } from '$lib/help/types';
  import { loadArt } from './index';

  let { name, width = '100%' }: { name: ArtName; width?: string } = $props();

  const drawing = $derived(loadArt(name));
</script>

<div class="art-box" style:width aria-hidden="true">
  {#await drawing then Drawing}<Drawing />{/await}
</div>

<style>
  .art-box {
    aspect-ratio: 300 / 180;
    max-width: 100%;
  }
</style>
