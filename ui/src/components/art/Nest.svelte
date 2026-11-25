<!--
  The clay oven nest from the mark, for use inside a drawing's <svg>. `x`/`y` place the middle
  of its base, `s` scales it (1 = 46 × 29 units). `ember` lights the door; a drawing has one
  ember, so leave it off when the heat sits elsewhere. The top of the dome is at y − 29·s.
-->
<svelte:options namespace="svg" />

<script lang="ts">
  interface Props {
    x: number;
    y: number;
    s?: number;
    ember?: boolean;
  }

  let { x, y, s = 1, ember = false }: Props = $props();
</script>

<g transform="translate({x} {y}) scale({s}) translate(-31 -56)">
  <path d="M10 56 C10 39 19.5 29 33 29 C46.5 29 56 39 56 56 Z" fill="var(--brand-clay-deep)" />
  <path d="M8 54 C8 37 17.5 27 31 27 C44.5 27 54 37 54 54 Z" fill="var(--brand-clay)" />
  <path
    d="M13 44 C14.5 36.5 20.5 31.5 27 30.3"
    fill="none"
    stroke="var(--brand-clay-light)"
    stroke-width="2"
    stroke-linecap="round"
  />
  <path d="M24 54 V47.5 A7 7 0 0 1 38 47.5 V54 Z" fill="var(--brand-night)" />
  {#if ember}
    <path
      class="flame"
      d="M31 53.6 C27.6 53.6 27.6 49.2 31 45.6 C34.4 49.2 34.4 53.6 31 53.6 Z"
      fill="var(--brand-ember)"
    />
  {/if}
</g>
