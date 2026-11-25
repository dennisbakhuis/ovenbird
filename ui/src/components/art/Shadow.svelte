<!--
  Shadow (reads and decides, never sends): the hornero stands back from the outdoor unit,
  watching it along a dotted line of sight, a notepad of ticked notes beside it. Hands off:
  nothing connects the bird to the pump. The ember is the unit's running light.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M10 96 C6 46 76 10 156 12 C238 14 294 46 290 98 C286 146 228 172 144 170 C60 168 14 144 10 96 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="rise">
    <rect x="44" y="80" width="44" height="60" rx="4" fill="var(--brand-cobalt)" />
    <rect x="40" y="76" width="44" height="60" rx="4" fill="var(--brand-sand)" />
    <g fill="var(--brand-night)">
      <circle cx="50" cy="76" r="2.5" />
      <circle cx="62" cy="76" r="2.5" />
      <circle cx="74" cy="76" r="2.5" />
      <rect x="60" y="91" width="18" height="3.5" rx="1.75" />
      <rect x="60" y="105" width="14" height="3.5" rx="1.75" />
      <rect x="60" y="119" width="18" height="3.5" rx="1.75" />
    </g>
    <path
      d="M47 92 l3 3 l5 -6 M47 106 l3 3 l5 -6 M47 120 l3 3 l5 -6"
      fill="none"
      stroke="var(--brand-cobalt)"
      stroke-width="2.2"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </g>
  <path
    class="fade"
    style="--d: 0.8s"
    d="M128 106 L178 104"
    stroke="var(--brand-ink)"
    stroke-width="2.6"
    stroke-linecap="round"
    stroke-dasharray="0.1 8"
  />
  <g class="rise" style="--d: 0.15s">
    <rect x="189" y="77" width="80" height="64" rx="5" fill="var(--brand-cobalt)" />
    <rect x="184" y="72" width="80" height="64" rx="5" fill="var(--brand-sand)" />
    <circle cx="210" cy="104" r="21" fill="var(--brand-night)" />
    <g fill="var(--brand-pale)">
      <ellipse cx="210" cy="94" rx="4.5" ry="9" />
      <ellipse cx="210" cy="94" rx="4.5" ry="9" transform="rotate(120 210 104)" />
      <ellipse cx="210" cy="94" rx="4.5" ry="9" transform="rotate(240 210 104)" />
    </g>
    <g stroke="var(--brand-night)" stroke-width="2.4" stroke-linecap="round">
      <path d="M240 98 H254 M240 106 H254 M240 114 H254 M240 122 H254" />
    </g>
    <circle cx="247" cy="84" r="4" fill="var(--brand-ember)" />
  </g>
  <Bird x={114} y={150} s={1.9} hop d="0.6s" />
  <Pellet x={36} y={54} r={20} tone="light" d="0.35s" />
  <Pellet x={160} y={40} r={-15} d="0.5s" />
  <Pellet x={170} y={144} r={30} size={8} tone="deep" d="0.62s" />
</svg>
