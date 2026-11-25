<!--
  AllQuiet (no alarms): the hornero asleep on its nest under the moon and a few stars, the
  ember glowing low in the door. On mount the stars come out one by one.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Nest from './Nest.svelte';
  import Pellet from './Pellet.svelte';

  const STAR = 'M0 -6 L1.6 -1.6 L6 0 L1.6 1.6 L0 6 L-1.6 1.6 L-6 0 L-1.6 -1.6 Z';
  const STARS = [
    { x: 60, y: 48, s: 1 },
    { x: 188, y: 40, s: 0.8 },
    { x: 252, y: 92, s: 1.1 },
    { x: 44, y: 104, s: 0.7 },
    { x: 154, y: 30, s: 0.6 },
  ];
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M10 98 C6 48 74 12 154 12 C236 12 292 46 290 98 C288 146 230 172 146 172 C62 172 14 146 10 98 Z"
    fill="var(--brand-ground)"
  />
  <path d="M40 152 H260" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="fade">
    <circle cx="228" cy="50" r="18" fill="var(--brand-sand)" />
    <circle cx="237" cy="43" r="15" fill="var(--brand-ground)" />
  </g>
  {#each STARS as star, i (star.x)}
    <g transform="translate({star.x} {star.y}) scale({star.s})">
      <path class="pop" style="--d: {0.4 + i * 0.15}s" d={STAR} fill="var(--brand-cobalt)" />
    </g>
  {/each}
  <Nest x={130} y={152} s={2.3} ember />
  <Bird x={130} y={86} s={2.3} sleep />
  <g
    class="fade"
    style="--d: 1.2s"
    fill="none"
    stroke="var(--brand-ink)"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    <path d="M160 52 H168 L160 60 H168" />
    <path d="M174 38 H180 L174 44 H180" />
  </g>
  <Pellet x={232} y={140} r={-15} d="0.5s" />
  <Pellet x={44} y={138} r={20} size={8} tone="light" d="0.62s" />
</svg>
