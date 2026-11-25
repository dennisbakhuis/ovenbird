<!--
  Setpoint: the heating curve on a card behind, the dial in front with the target marked by
  the ember, and the hornero nudging the dial with its beak. On mount the curve draws itself
  and the pointer swings to the target.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';

  const CX = 196;
  const CY = 104;
  const ticks = Array.from({ length: 9 }, (_, i) => {
    const a = ((-120 + i * 30) * Math.PI) / 180;
    const at = (r: number) =>
      `${(CX + r * Math.sin(a)).toFixed(1)} ${(CY - r * Math.cos(a)).toFixed(1)}`;
    return `M${at(25)} L${at(30)}`;
  }).join(' ');
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M10 96 C6 46 76 10 156 12 C238 14 294 46 290 98 C286 146 228 172 144 170 C60 168 14 144 10 96 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="rise">
    <rect x="45" y="35" width="128" height="96" rx="6" fill="var(--brand-cobalt)" />
    <rect x="40" y="30" width="128" height="96" rx="6" fill="var(--brand-sand)" />
    <path
      d="M54 44 V112 H156"
      fill="none"
      stroke="var(--brand-night)"
      stroke-width="2.4"
      stroke-linecap="round"
    />
  </g>
  <path
    class="draw"
    pathLength="1"
    style="--d: 0.3s"
    d="M60 50 C88 58 116 82 152 100"
    fill="none"
    stroke="var(--brand-cobalt)"
    stroke-width="4.5"
    stroke-linecap="round"
  />
  <g class="pop" style="--d: 0.1s">
    <circle cx={CX + 5} cy={CY + 5} r="38" fill="var(--brand-cobalt)" />
    <circle cx={CX} cy={CY} r="38" fill="var(--brand-sand)" />
    <path d={ticks} stroke="var(--brand-night)" stroke-width="2.4" stroke-linecap="round" />
    <circle cx="218.2" cy="77.6" r="4.6" fill="var(--brand-ember)" />
  </g>
  <g
    class="swing"
    style="--from: -150deg; --d: 0.5s; transform-box: view-box; transform-origin: {CX}px {CY}px"
  >
    <path
      d="M196 104 L211.4 85.6"
      stroke="var(--brand-night)"
      stroke-width="4"
      stroke-linecap="round"
    />
    <circle cx={CX} cy={CY} r="6.5" fill="var(--brand-night)" />
  </g>
  <Bird x={244} y={150} s={1.7} flip hop d="0.9s" />
  <Pellet x={30} y={66} r={24} tone="light" d="0.35s" />
  <Pellet x={262} y={46} r={-20} d="0.5s" />
  <Pellet x={120} y={146} r={12} size={8} tone="deep" d="0.62s" />
</svg>
