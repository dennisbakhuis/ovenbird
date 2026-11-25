<!--
  Activity: a clay notice board with cards pinned to it, the hornero on top, and the bell
  beside it with its clapper as the ember. On mount the cards are pinned one by one and the
  bell swings once.
-->
<script lang="ts">
  import './art.css';
  import Bird from './Bird.svelte';
  import Pellet from './Pellet.svelte';

  const CARDS = [
    { x: 56, y: 44, w: 50, h: 34, r: -4 },
    { x: 116, y: 42, w: 54, h: 30, r: 3 },
    { x: 74, y: 88, w: 64, h: 32, r: 2 },
  ];
</script>

<svg class="art" viewBox="0 0 300 180" aria-hidden="true" focusable="false">
  <path
    d="M8 98 C6 48 70 12 150 12 C234 12 294 44 292 96 C290 146 232 172 148 172 C62 172 10 148 8 98 Z"
    fill="var(--brand-ground)"
  />
  <path d="M30 152 H270" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
  <g class="rise">
    <rect x="64" y="128" width="7" height="24" fill="var(--brand-clay-deep)" />
    <rect x="156" y="128" width="7" height="24" fill="var(--brand-clay-deep)" />
    <rect x="49" y="35" width="140" height="98" rx="6" fill="var(--brand-clay-deep)" />
    <rect x="44" y="30" width="140" height="98" rx="6" fill="var(--brand-clay)" />
  </g>
  {#each CARDS as card, i (card.x)}
    <g class="rise" style="--d: {0.25 + i * 0.15}s">
      <g transform="rotate({card.r} {card.x + card.w / 2} {card.y + card.h / 2})">
        <rect
          x={card.x}
          y={card.y}
          width={card.w}
          height={card.h}
          rx="3"
          fill="var(--brand-sand)"
        />
        <g fill="var(--brand-night)">
          <rect x={card.x + 7} y={card.y + 10} width={card.w - 20} height="3.5" rx="1.75" />
          <rect x={card.x + 7} y={card.y + 18} width={card.w - 28} height="3.5" rx="1.75" />
        </g>
        <circle cx={card.x + card.w / 2} cy={card.y + 3} r="3.2" fill="var(--brand-cobalt)" />
      </g>
    </g>
  {/each}
  <g
    class="swing"
    style="--from: 22deg; --d: 0.7s; transform-box: view-box; transform-origin: 238px 66px"
  >
    <circle cx="238" cy="68" r="4" fill="var(--brand-ink)" />
    <path
      d="M224 110 C224 86 226 72 242 72 C256 72 258 86 258 110 L264 118 H218 Z"
      fill="var(--brand-cobalt)"
    />
    <path
      d="M220 106 C220 82 222 70 238 70 C252 70 254 82 254 106 L260 114 H214 Z"
      fill="var(--brand-sand)"
    />
    <circle cx="238" cy="120" r="5.5" fill="var(--brand-ember)" />
  </g>
  <g
    class="fade"
    style="--d: 1s"
    fill="none"
    stroke="var(--brand-ink)"
    stroke-width="2.4"
    stroke-linecap="round"
  >
    <path d="M206 80 Q200 90 206 100" />
    <path d="M270 80 Q276 90 270 100" />
  </g>
  <Bird x={148} y={30} s={1.5} hop d="0.9s" />
  <Pellet x={30} y={72} r={20} tone="light" d="0.35s" />
  <Pellet x={270} y={40} r={-15} d="0.5s" />
  <Pellet x={200} y={140} r={30} size={8} tone="deep" d="0.62s" />
</svg>
