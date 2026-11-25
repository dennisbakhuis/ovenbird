<!--
  A small clay pellet that tumbles into place when the drawing appears (the DinkelLabs cubes,
  in clay). `x`/`y` is its centre, `r` its resting angle, `tone` its clay shade, `d` the delay.
-->
<svelte:options namespace="svg" />

<script lang="ts">
  interface Props {
    x: number;
    y: number;
    r?: number;
    size?: number;
    tone?: 'clay' | 'light' | 'deep';
    d?: string;
  }

  let { x, y, r = 0, size = 10, tone = 'clay', d }: Props = $props();

  const FILL = {
    clay: 'var(--brand-clay)',
    light: 'var(--brand-clay-light)',
    deep: 'var(--brand-clay-deep)',
  };
</script>

<g class="pellet" style={d ? `--d: ${d}` : undefined}>
  <rect
    x={x - size / 2}
    y={y - size * 0.35}
    width={size}
    height={size * 0.7}
    rx={size * 0.32}
    transform="rotate({r} {x} {y})"
    fill={FILL[tone]}
  />
</g>
