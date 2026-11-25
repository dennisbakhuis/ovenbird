<!--
  ArtGallery: every drawing at 300 and 120 px wide, plus the EmptyState layouts; shown on the
  mock-only #/dev-charts gallery. English on purpose: never shipped to users.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import { ART_NAMES, loadArt } from './index';
</script>

<Card bare class="art-gallery-wide" data-testid="dev-art">
  <h2>Illustrations</h2>
  <div class="art-grid">
    {#each ART_NAMES as name (name)}
      <figure data-testid="dev-art-{name}">
        {#await loadArt(name) then Art}
          <div class="big"><Art /></div>
          <div class="small"><Art /></div>
        {/await}
        <figcaption>{name}</figcaption>
      </figure>
    {/each}
  </div>
  <h3>EmptyState</h3>
  <div class="states">
    <EmptyState art="allQuiet" title="No active alarms." text="Everything is within its limits." />
    <EmptyState art="noData" text="No data in this window yet." size="small" />
  </div>
</Card>

<style>
  :global(.art-gallery-wide) {
    grid-column: 1 / -1;
  }
  .art-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 27rem), 1fr));
    gap: var(--space-4);
  }
  figure {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-4);
    padding: var(--space-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-control);
  }
  .big {
    width: 300px;
    max-width: 100%;
  }
  .small {
    width: 120px;
  }
  figcaption {
    width: 100%;
    font-size: var(--fs-md);
    color: var(--muted);
  }
  .states {
    display: grid;
    gap: var(--space-4);
  }
  h3 {
    font-size: var(--fs-xl);
    margin-top: var(--space-4);
  }
</style>
