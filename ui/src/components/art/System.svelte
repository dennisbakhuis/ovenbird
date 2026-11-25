<!--
  System: the HeishaMon board on the left, wired to the ovenbird service on the right (its
  nest carries the ember). Readings travel to the service as cobalt dots on the top wire;
  commands go back as clay dots on the bottom one. On mount the dots light up in order.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Nest from './Nest.svelte';
  import Pellet from './Pellet.svelte';

  const PINS = [52, 62, 72, 82];
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M8 100 C4 50 70 12 152 12 C236 12 294 44 292 96 C290 144 232 172 146 172 C62 172 12 146 8 100 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g stroke="var(--brand-ink)" stroke-width="2.4" stroke-linecap="round">
    <path d="M118 86 H196" />
    <path d="M118 108 H196" />
  </g>
  {#each [136, 156, 176] as x, i (x)}
    <circle
      class="pop"
      style="--d: {0.6 + i * 0.15}s"
      cx={x}
      cy="86"
      r="4.5"
      fill="var(--brand-cobalt)"
    />
  {/each}
  {#each [172, 146] as x, i (x)}
    <circle
      class="pop"
      style="--d: {1.1 + i * 0.15}s"
      cx={x}
      cy="108"
      r="4"
      fill="var(--brand-clay)"
    />
  {/each}
  <g class="rise">
    <rect x="43" y="65" width="78" height="64" rx="4" fill="var(--brand-cobalt)" />
    <rect x="38" y="60" width="78" height="64" rx="4" fill="var(--brand-sand)" />
    <rect x="50" y="74" width="30" height="30" rx="2" fill="var(--brand-night)" />
    <g stroke="var(--brand-night)" stroke-width="2" stroke-linecap="round">
      <path d="M56 70 V72 M65 70 V72 M74 70 V72 M56 106 V108 M65 106 V108 M74 106 V108" />
    </g>
    <path
      d="M90 70 H106 V77 H94 V84 H106"
      fill="none"
      stroke="var(--brand-cobalt)"
      stroke-width="2.4"
      stroke-linejoin="round"
    />
    {#each PINS as x (x)}
      <rect {x} y="113" width="5" height="5" fill="var(--brand-night)" />
    {/each}
    <circle cx="102" cy="100" r="3.5" fill="var(--brand-cobalt)" />
  </g>
  <g class="rise" style="--d: 0.15s">
    <rect x="201" y="51" width="64" height="96" rx="6" fill="var(--brand-cobalt)" />
    <rect x="196" y="46" width="64" height="96" rx="6" fill="var(--brand-sand)" />
    <g fill="var(--brand-night)">
      <rect x="206" y="58" width="36" height="4" rx="2" />
      <rect x="206" y="68" width="26" height="4" rx="2" />
      <rect x="206" y="78" width="32" height="4" rx="2" />
    </g>
    <Nest x={228} y={134} s={0.95} ember />
  </g>
  <Bird x={244} y={46} s={1.4} hop d="0.9s" />
  <Pellet x={34} y={48} r={20} tone="light" d="0.35s" />
  <Pellet x={160} y={42} r={-15} d="0.5s" />
  <Pellet x={150} y={140} r={30} size={8} tone="deep" d="0.62s" />
</svg>
