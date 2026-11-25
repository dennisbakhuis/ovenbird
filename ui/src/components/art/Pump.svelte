<!--
  Pump: the outdoor unit with its compressor glowing (the ember), and the water loop running
  to the house and back. On mount the fan turns once and the flow arrows light up in the
  direction the water goes: out along the top pipe, back along the bottom one.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';

  const OUT = [168, 184, 200];
  const BACK = [200, 184, 168];
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M8 96 C6 46 74 12 154 12 C236 12 294 46 290 98 C288 146 230 172 146 172 C60 172 10 144 8 96 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g stroke="var(--brand-cobalt)" stroke-width="6" stroke-linecap="round">
    <path d="M150 92 H216" />
    <path d="M150 120 H216" />
  </g>
  <g
    fill="none"
    stroke="var(--brand-pale)"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
  >
    {#each OUT as x, i (x)}
      <path class="fade" style="--d: {0.7 + i * 0.12}s" d="M{x - 2} 89 L{x + 1} 92 L{x - 2} 95" />
    {/each}
    {#each BACK as x, i (x)}
      <path
        class="fade"
        style="--d: {1.06 + i * 0.12}s"
        d="M{x + 2} 117 L{x - 1} 120 L{x + 2} 123"
      />
    {/each}
  </g>
  <g class="rise">
    <rect x="45" y="71" width="112" height="76" rx="6" fill="var(--brand-cobalt)" />
    <rect x="40" y="66" width="112" height="76" rx="6" fill="var(--brand-sand)" />
    <rect x="112" y="78" width="30" height="54" rx="4" fill="var(--brand-night)" />
    <path class="flame" d="M119 124 V108 A8 8 0 0 1 135 108 V124 Z" fill="var(--brand-ember)" />
    <g stroke="var(--brand-pale)" stroke-width="2" stroke-linecap="round">
      <path d="M118 86 H136 M118 93 H136" />
    </g>
  </g>
  <g class="swing" style="--from: -300deg; --d: 0.3s">
    <circle cx="76" cy="104" r="27" fill="var(--brand-night)" />
    <g fill="var(--brand-pale)">
      <ellipse cx="76" cy="91" rx="6" ry="12" />
      <ellipse cx="76" cy="91" rx="6" ry="12" transform="rotate(120 76 104)" />
      <ellipse cx="76" cy="91" rx="6" ry="12" transform="rotate(240 76 104)" />
    </g>
    <circle cx="76" cy="104" r="4" fill="var(--brand-night)" />
  </g>
  <g class="rise" style="--d: 0.15s">
    <rect x="220" y="90" width="48" height="62" fill="var(--brand-cobalt)" />
    <rect x="216" y="86" width="48" height="62" fill="var(--brand-sand)" />
    <path d="M214 94 L242 62 L274 94 Z" fill="var(--brand-clay-deep)" />
    <path d="M208 90 L240 58 L272 90 Z" fill="var(--brand-clay)" />
    <rect x="236" y="104" width="16" height="16" rx="2" fill="var(--brand-pale)" />
  </g>
  <Bird x={60} y={66} s={1.6} hop d="0.8s" />
  <Pellet x={186} y={46} r={20} tone="light" d="0.35s" />
  <Pellet x={26} y={120} r={-15} d="0.5s" />
  <Pellet x={180} y={140} r={30} size={8} tone="deep" d="0.62s" />
</svg>
