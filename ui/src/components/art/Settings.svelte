<!--
  Settings: a panel of sliders, one knob glowing (the ember), and the hornero carrying a small
  heating curve to it like a twig for the nest. On mount the knobs slide to their places.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';

  const ROWS = [
    { y: 62, at: 126, fill: 'var(--brand-clay)' },
    { y: 86, at: 92, fill: 'var(--brand-ember)' },
    { y: 110, at: 142, fill: 'var(--brand-clay)' },
  ];
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M10 100 C6 50 72 12 152 12 C234 12 292 44 290 96 C288 146 232 170 148 172 C60 172 14 146 10 100 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="rise">
    <rect x="45" y="39" width="140" height="98" rx="8" fill="var(--brand-cobalt)" />
    <rect x="40" y="34" width="140" height="98" rx="8" fill="var(--brand-sand)" />
  </g>
  {#each ROWS as row, i (row.y)}
    <path d="M60 {row.y} H160" stroke="var(--brand-pale)" stroke-width="5" stroke-linecap="round" />
    <path
      d="M60 {row.y} H{row.at}"
      stroke="var(--brand-cobalt)"
      stroke-width="5"
      stroke-linecap="round"
    />
    <g class="slide" style="--d: {0.3 + i * 0.12}s; --dx: {60 - row.at}px">
      <circle cx={row.at + 2} cy={row.y + 2} r="8" fill="var(--brand-night)" />
      <circle cx={row.at} cy={row.y} r="8" fill={row.fill} />
    </g>
  {/each}
  <Bird x={234} y={150} s={1.7} flip />
  <path
    class="draw"
    pathLength="1"
    style="--d: 0.8s"
    d="M200 111 Q209 126 232 130"
    fill="none"
    stroke="var(--brand-cobalt)"
    stroke-width="4"
    stroke-linecap="round"
  />
  <Pellet x={30} y={62} r={20} tone="light" d="0.35s" />
  <Pellet x={256} y={52} r={-15} d="0.5s" />
  <Pellet x={206} y={30} r={30} size={8} tone="deep" d="0.62s" />
</svg>
