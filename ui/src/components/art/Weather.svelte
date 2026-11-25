<!--
  Weather: the sun (the ember) behind a cloud, the hornero on a weather vane looking ahead,
  and a strip of forecast days below. On mount the sun and cloud rise, the vane swings into
  the wind and the forecast cards come up one by one.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';

  const LAYERS = [
    { o: 4, fill: 'var(--brand-cobalt)' },
    { o: 0, fill: 'var(--brand-sand)' },
  ];
  const DAYS = [0, 1, 2, 3];
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M8 98 C6 48 72 10 150 12 C234 14 294 42 292 94 C290 146 230 172 148 172 C62 172 10 148 8 98 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="rise">
    <g stroke="var(--brand-clay-light)" stroke-width="3.5" stroke-linecap="round">
      <path d="M92 20 V28 M62 52 H70 M70 30 L76 36 M114 30 L108 36 M70 74 L76 68" />
    </g>
    <circle cx="92" cy="52" r="18" fill="var(--brand-ember)" />
  </g>
  <g class="rise" style="--d: 0.15s">
    {#each LAYERS as layer (layer.o)}
      <g transform="translate({layer.o} {layer.o})" fill={layer.fill}>
        <rect x="88" y="70" width="80" height="24" rx="12" />
        <circle cx="110" cy="70" r="14" />
        <circle cx="134" cy="62" r="19" />
        <circle cx="155" cy="74" r="12" />
      </g>
    {/each}
  </g>
  {#each DAYS as day (day)}
    {@const x = 40 + day * 34}
    <g class="rise" style="--d: {0.4 + day * 0.1}s">
      <rect x={x + 3} y="113" width="28" height="34" rx="4" fill="var(--brand-cobalt)" />
      <rect {x} y="110" width="28" height="34" rx="4" fill="var(--brand-sand)" />
      <rect x={x + 8} y="134" width="12" height="3" rx="1.5" fill="var(--brand-night)" />
    </g>
  {/each}
  <circle cx="54" cy="123" r="5.5" fill="var(--brand-clay-light)" />
  <g fill="var(--brand-cobalt)">
    <rect x="80" y="121" width="16" height="7" rx="3.5" />
    <circle cx="86" cy="120" r="4.5" />
  </g>
  <path
    d="M122 116 V130 M116 119.5 L128 126.5 M116 126.5 L128 119.5"
    stroke="var(--brand-cobalt)"
    stroke-width="2"
    stroke-linecap="round"
  />
  <g fill="var(--brand-cobalt)">
    <rect x="148" y="117" width="16" height="7" rx="3.5" />
    <circle cx="154" cy="116" r="4.5" />
  </g>
  <path
    d="M150 128 l-1.5 3 M156 128 l-1.5 3 M162 128 l-1.5 3"
    stroke="var(--brand-cobalt)"
    stroke-width="1.8"
    stroke-linecap="round"
  />
  <path d="M226 150 V80" stroke="var(--brand-ink)" stroke-width="3" stroke-linecap="round" />
  <g
    class="swing"
    style="--from: -14deg; --d: 0.5s; transform-box: view-box; transform-origin: 226px 80px"
  >
    <path d="M198 80 H252" stroke="var(--brand-ink)" stroke-width="3" stroke-linecap="round" />
    <path d="M250 74 L262 80 L250 86 Z" fill="var(--brand-ink)" />
    <path d="M194 70 L206 80 L194 90 L200 80 Z" fill="var(--brand-cobalt)" />
    <Bird x={226} y={79} s={1.5} />
  </g>
  <Pellet x={262} y={124} r={20} tone="light" d="0.35s" />
  <Pellet x={186} y={34} r={-15} d="0.5s" />
  <Pellet x={190} y={128} r={30} size={8} tone="deep" d="0.62s" />
</svg>
