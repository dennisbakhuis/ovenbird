<!--
  NoData: an empty chart frame, a dotted line where the data will be and the ember where it
  will start, and the hornero waiting beside it. On mount the frame rises and the dots fill in.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M10 100 C6 50 72 12 152 12 C234 12 292 44 290 96 C288 146 232 170 148 172 C60 172 14 146 10 100 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="rise">
    <rect x="55" y="37" width="150" height="104" rx="6" fill="var(--brand-cobalt)" />
    <rect x="50" y="32" width="150" height="104" rx="6" fill="var(--brand-sand)" />
    <path
      d="M66 46 V120 H186"
      fill="none"
      stroke="var(--brand-night)"
      stroke-width="2.4"
      stroke-linecap="round"
    />
  </g>
  <path
    class="fade"
    style="--d: 0.5s"
    d="M90 92 H180"
    stroke="var(--brand-cobalt)"
    stroke-width="3.5"
    stroke-linecap="round"
    stroke-dasharray="0.1 9"
  />
  <circle class="pop" style="--d: 0.8s" cx="78" cy="92" r="5.5" fill="var(--brand-ember)" />
  <Bird x={238} y={150} s={1.9} flip hop d="1s" />
  <Pellet x={32} y={64} r={20} tone="light" d="0.35s" />
  <Pellet x={256} y={46} r={-15} d="0.5s" />
  <Pellet x={214} y={20} r={30} size={8} tone="deep" d="0.62s" />
</svg>
