<!--
  Home: the house with the warm room (the ember in its door, as in the nest), the room
  thermometer in the window, and the outdoor unit feeding the water loop. The hornero keeps
  watch from the roof. On mount the house rises, the fan turns once and the pellets tumble in.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M8 100 C4 50 70 12 152 12 C236 12 294 44 292 96 C290 144 232 172 146 172 C62 172 12 146 8 100 Z"
    fill="var(--brand-ground)"
  />
  <g class="rise">
    <rect x="74" y="88" width="96" height="64" fill="var(--brand-cobalt)" />
    <rect x="70" y="84" width="96" height="64" fill="var(--brand-sand)" />
    <path d="M66 92 L122 44 L178 92 Z" fill="var(--brand-clay-deep)" />
    <path d="M60 88 L118 38 L176 88 Z" fill="var(--brand-clay)" />
    <path
      d="M76 80 L112 49"
      stroke="var(--brand-clay-light)"
      stroke-width="3"
      stroke-linecap="round"
    />
    <path d="M82 148 V124 A11 11 0 0 1 104 124 V148 Z" fill="var(--brand-night)" />
    <path
      class="flame"
      d="M93 146 C88 146 88 139.5 93 133.5 C98 139.5 98 146 93 146 Z"
      fill="var(--brand-ember)"
    />
    <rect x="116" y="98" width="38" height="32" rx="3" fill="var(--brand-pale)" />
    <rect x="133" y="103" width="6" height="20" rx="3" fill="var(--brand-night)" />
    <circle cx="136" cy="123" r="5" fill="var(--brand-night)" />
    <rect x="134.8" y="110" width="2.4" height="13" rx="1.2" fill="var(--brand-clay)" />
    <circle cx="136" cy="123" r="3" fill="var(--brand-clay)" />
  </g>
  <g stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round">
    <path d="M170 124 H198" />
    <path d="M170 136 H198" />
    <path d="M30 152 H270" />
  </g>
  <g class="rise" style="--d: 0.15s">
    <rect x="202" y="112" width="58" height="40" rx="4" fill="var(--brand-cobalt)" />
    <rect x="198" y="108" width="58" height="40" rx="4" fill="var(--brand-sand)" />
    <g stroke="var(--brand-night)" stroke-width="2.4" stroke-linecap="round">
      <path d="M240 118 H249 M240 125 H249 M240 132 H249 M240 139 H249" />
    </g>
  </g>
  <g class="swing" style="--from: -300deg; --d: 0.4s">
    <circle cx="217" cy="128" r="14" fill="var(--brand-night)" />
    <g fill="var(--brand-pale)">
      <ellipse cx="217" cy="121.5" rx="3.4" ry="6.5" />
      <ellipse cx="217" cy="121.5" rx="3.4" ry="6.5" transform="rotate(120 217 128)" />
      <ellipse cx="217" cy="121.5" rx="3.4" ry="6.5" transform="rotate(240 217 128)" />
    </g>
  </g>
  <Bird x={118} y={39} s={1.6} hop d="0.7s" />
  <Pellet x={40} y={70} r={20} tone="light" d="0.35s" />
  <Pellet x={262} y={64} r={-15} d="0.5s" />
  <Pellet x={204} y={42} r={30} size={8} tone="deep" d="0.62s" />
</svg>
