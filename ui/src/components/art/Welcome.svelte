<!--
  Welcome (the help index): the mark itself, the hornero on its oven nest with the ember in
  the door, and a speech bubble with a question mark. On mount the nest rises, the bird hops
  and the bubble pops out.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Nest from './Nest.svelte';
  import Pellet from './Pellet.svelte';
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M10 98 C6 48 74 12 154 12 C236 12 292 46 290 98 C288 146 230 172 146 172 C62 172 14 146 10 98 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="rise"><Nest x={112} y={152} s={2.4} ember /></g>
  <Bird x={112} y={82.9} s={2.4} hop d="0.6s" />
  <g class="pop" style="--d: 0.9s">
    <rect x="187" y="35" width="72" height="56" rx="14" fill="var(--brand-cobalt)" />
    <path d="M192 84 L170 104 L210 88 Z" fill="var(--brand-cobalt)" />
    <rect x="182" y="30" width="72" height="56" rx="14" fill="var(--brand-sand)" />
    <path d="M190 80 L166 100 L206 84 Z" fill="var(--brand-sand)" />
    <path
      d="M209 49 C209 39 227 39 227 48.5 C227 56 218 56 218 64"
      fill="none"
      stroke="var(--brand-night)"
      stroke-width="5.5"
      stroke-linecap="round"
    />
    <circle cx="218" cy="73.5" r="3.6" fill="var(--brand-night)" />
  </g>
  <Pellet x={36} y={70} r={20} tone="light" d="0.35s" />
  <Pellet x={262} y={120} r={-15} d="0.5s" />
  <Pellet x={190} y={136} r={30} size={8} tone="deep" d="0.62s" />
</svg>
