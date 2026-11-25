<!--
  LaneRows: SVG fragment drawing state lanes (one row per lane, run-length segments, intensity
  as opacity) with an icon and optional text label in the left gutter. Shared by TimeChart's
  lane panels and StateStrip; render inside an <svg> group translated to the plot origin.
-->
<svelte:options namespace="svg" />

<script lang="ts">
  import type { LaneSpec } from './types';

  interface Props {
    lanes: LaneSpec[];
    sx: (t: number) => number;
    top: number;
    innerW: number;
    gutter: number;
    laneHeight: number;
    laneGap: number;
    showLabels: boolean;
  }

  let { lanes, sx, top, innerW, gutter, laneHeight, laneGap, showLabels }: Props = $props();

  const iconSize = $derived(Math.min(laneHeight, 14));
</script>

{#each lanes as lane, index (lane.id)}
  {@const y = top + index * (laneHeight + laneGap)}
  <g class="lane" data-lane={lane.id}>
    <rect x="0" {y} width={innerW} height={laneHeight} rx="2" class="track" />
    {#each lane.segments as segment, i (`${segment.from}-${i}`)}
      {@const x0 = Math.max(sx(segment.from), 0)}
      {@const x1 = Math.min(sx(segment.to), innerW)}
      {#if x1 > x0 - 1.5}
        <rect
          x={x0}
          {y}
          width={Math.max(x1 - x0, 1.5)}
          height={laneHeight}
          fill={lane.states?.[segment.state]?.color ?? lane.color}
          fill-opacity={segment.level === undefined
            ? 0.9
            : Number((0.3 + 0.7 * segment.level).toFixed(2))}
          data-state={segment.state}
        />
      {/if}
    {/each}
    {#if lane.icon}
      <path
        d={lane.icon}
        transform="translate({-gutter + 2},{y + (laneHeight - iconSize) / 2}) scale({iconSize /
          24})"
        class="icon"
        stroke-width={1.5 * (24 / iconSize)}
      />
    {/if}
    {#if showLabels || !lane.icon}
      <text
        x={-gutter + (lane.icon ? iconSize + 6 : 2)}
        y={y + laneHeight / 2}
        dy="0.34em"
        class="label">{showLabels ? lane.label : lane.label.slice(0, 3)}</text
      >
    {/if}
  </g>
{/each}

<style>
  .track {
    fill: color-mix(in srgb, var(--border) 45%, transparent);
  }
  .icon {
    fill: none;
    stroke: var(--muted);
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .label {
    fill: var(--muted);
    font-size: var(--fs-micro);
  }
</style>
