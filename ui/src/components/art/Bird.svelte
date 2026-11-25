<!--
  The hornero from the mark (components/brand/Logo.svelte), for use inside a drawing's <svg>.
  `x`/`y` place its feet, `s` scales it, `flip` turns it to face left. `sleep` tucks the head in
  and closes the eye. The bird takes the theme's ink, so keep it on the ground, not on a light face.
-->
<svelte:options namespace="svg" />

<script lang="ts">
  interface Props {
    x: number;
    y: number;
    s?: number;
    flip?: boolean;
    sleep?: boolean;
    hop?: boolean;
    d?: string;
  }

  let { x, y, s = 1, flip = false, sleep = false, hop = false, d }: Props = $props();
</script>

<g class:hop style={d ? `--d: ${d}` : undefined}>
  <g transform="translate({x} {y}) scale({flip ? -s : s} {s}) translate(-31 -27.2)">
    {#if sleep}
      <g fill="var(--brand-ink)">
        <path d="M25.5 21.5 L18.6 19.4 L19.6 23 Z" />
        <ellipse cx="30.6" cy="22" rx="7" ry="5.2" transform="rotate(-6 30.6 22)" />
        <circle cx="35.8" cy="17.6" r="3.1" />
        <path d="M38.4 18.2 Q40.2 19.6 40.6 21.7 L37.6 19.8 Z" />
      </g>
      <path
        d="M34.4 17.3 Q35.5 18.4 36.7 17.3"
        fill="none"
        stroke="var(--surface)"
        stroke-width="0.8"
        stroke-linecap="round"
      />
    {:else}
      <g fill="var(--brand-ink)">
        <path d="M28.8 20.6 L21.6 26.6 L24.8 27 L28 23.8 Z" />
        <ellipse cx="30.8" cy="17.6" rx="4.2" ry="6.4" transform="rotate(28 30.8 17.6)" />
        <circle cx="34.6" cy="10" r="3" />
        <path d="M37.1 9.1 Q40.2 9.6 42.6 11.4 L37.3 11.1 Z" />
      </g>
      <g stroke="var(--brand-ink)" stroke-width="1.3" stroke-linecap="round">
        <path d="M29.6 23 L29.2 27.2" />
        <path d="M31.8 22.6 L32.5 27.2" />
      </g>
      <circle cx="35.3" cy="9.4" r="0.8" fill="var(--surface)" />
    {/if}
  </g>
</g>
