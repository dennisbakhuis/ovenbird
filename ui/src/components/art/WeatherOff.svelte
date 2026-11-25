<!--
  WeatherOff: the forecast is switched off. A cloud with its cable unplugged from the socket,
  a low sun (the ember) peeking out behind it and the hornero looking on, unbothered. Calm on
  purpose: nothing is wrong. On mount the plug eases out of the socket.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';

  const LAYERS = [
    { o: 4, fill: 'var(--brand-cobalt)' },
    { o: 0, fill: 'var(--brand-sand)' },
  ];
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M8 98 C6 48 72 10 150 12 C234 14 294 42 292 94 C290 146 230 172 148 172 C62 172 10 148 8 98 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <circle class="rise" cx="82" cy="50" r="15" fill="var(--brand-ember)" />
  <g class="rise" style="--d: 0.1s">
    {#each LAYERS as layer (layer.o)}
      <g transform="translate({layer.o} {layer.o})" fill={layer.fill}>
        <rect x="70" y="62" width="96" height="28" rx="14" />
        <circle cx="96" cy="62" r="17" />
        <circle cx="124" cy="52" r="23" />
        <circle cx="150" cy="66" r="14" />
      </g>
    {/each}
  </g>
  <path
    d="M120 94 C120 126 150 132 168 126"
    fill="none"
    stroke="var(--brand-ink)"
    stroke-width="2.6"
    stroke-linecap="round"
  />
  <g class="slide" style="--dx: 22px; --d: 0.5s">
    <rect x="166" y="118" width="16" height="16" rx="3" fill="var(--brand-ink)" />
    <path
      d="M182 122 H189 M182 130 H189"
      stroke="var(--brand-ink)"
      stroke-width="2.6"
      stroke-linecap="round"
    />
  </g>
  <rect x="216" y="113" width="22" height="30" rx="4" fill="var(--brand-cobalt)" />
  <rect x="212" y="109" width="22" height="30" rx="4" fill="var(--brand-sand)" />
  <g fill="var(--brand-night)">
    <rect x="215" y="120" width="6" height="2.6" rx="1.3" />
    <rect x="215" y="128" width="6" height="2.6" rx="1.3" />
  </g>
  <Bird x={262} y={150} s={1.5} flip />
  <Pellet x={196} y={44} r={20} tone="light" d="0.35s" />
  <Pellet x={40} y={110} r={-15} d="0.5s" />
  <Pellet x={92} y={140} r={30} size={8} tone="deep" d="0.62s" />
</svg>
