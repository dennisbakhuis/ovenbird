<!--
  StateStrip: a day strip of state lanes (compressor, defrost, hot water, quiet, holds …) on a
  time axis. Build segments with runLengthSegments() from lib/chart (shade = `level`).

  Props: from, to (ms); title; lanes (LaneSpec[]: id, label, color, segments, icon?, states?
  = per-state label/colour, events? = point events, listed as moments instead of spans); now
  (ms, draws a now line; also the time the idle read-out describes); laneHeight (16); axis (x tick labels, default true); labels ('auto' = text labels
  from 480 px, 'icons', 'full'); summary (override); list (show the "Show as list" toggle,
  default true); onselect(t) on click/Enter; oncursor(t | null).
  A11y: role="img" with one sentence per lane ("Compressor: on 4 times, 14 h in total"); the
  segments are always in the DOM as a list (visually hidden until toggled); a slider overlay
  moves a crosshair between segment edges with the arrow keys and reads the state of every lane.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { segmentAt, timeTicks, unionTimes, type Point } from '$lib/core/chart';
  import {
    chartText,
    describeEvent,
    describeLane,
    describeSegment,
    formatClockTime,
  } from '$lib/core/chartSummary';
  import { timeLocale } from '$lib/core/format';
  import { settings } from '$lib/core/settings.svelte';
  import Crosshair from './Crosshair.svelte';
  import LaneRows from './LaneRows.svelte';
  import type { LaneSpec } from './types';

  interface Props {
    from: number;
    to: number;
    title: string;
    lanes: LaneSpec[];
    now?: number | null;
    laneHeight?: number;
    axis?: boolean;
    labels?: 'auto' | 'icons' | 'full';
    summary?: string;
    list?: boolean;
    onselect?: (t: number) => void;
    oncursor?: (t: number | null) => void;
  }

  let {
    from,
    to,
    title,
    lanes,
    now = null,
    laneHeight = 16,
    axis = true,
    labels = 'auto',
    summary,
    list = true,
    onselect,
    oncursor,
  }: Props = $props();

  const GAP = 4;
  let measured = $state(0);
  let cursor = $state<number | null>(null);
  let showList = $state(false);
  const lang = $derived(settings.language);
  const width = $derived(measured > 0 ? measured : 600);
  const compact = $derived(width < 480);
  const full = $derived(labels === 'full' || (labels === 'auto' && !compact));
  const gutter = $derived(full ? 96 : 24);
  const innerW = $derived(Math.max(width - gutter - 8, 10));
  const lanesH = $derived(lanes.length * (laneHeight + GAP) - GAP);
  const svgH = $derived(lanesH + (axis ? 22 : 2));
  const multiDay = $derived(to - from > 40 * 3_600_000);
  function tickLabel(t: number): string {
    const date = new Date(t);
    if (multiDay && date.getHours() === 0 && date.getMinutes() === 0)
      return date.toLocaleDateString(timeLocale(lang), { weekday: 'short', day: 'numeric' });
    return formatClockTime(t, lang);
  }
  const sx = (t: number) => ((t - from) / Math.max(to - from, 1)) * innerW;
  const ticks = $derived(axis ? timeTicks(from, to, compact ? 4 : 6) : []);
  const times = $derived(
    unionTimes(
      lanes.map((lane) =>
        lane.segments.flatMap((s): Point[] => [
          [Math.max(s.from, from), 0],
          [Math.min(s.to, to), 0],
        ]),
      ),
    ),
  );
  const stateAt = (lane: LaneSpec, t: number) => {
    const segment = segmentAt(lane.segments, t);
    if (!segment) return chartText(lang, 'off');
    return lane.states?.[segment.state]?.label ?? chartText(lang, 'on');
  };
  const probe = $derived(cursor ?? (now !== null && now >= from && now <= to ? now : to));
  const readout = $derived(
    `${formatClockTime(probe, lang, multiDay)}: ${lanes.map((l) => (stateAt(l, probe) === l.label ? l.label : `${l.label} ${stateAt(l, probe)}`)).join(', ')}`,
  );
  const text = $derived(
    summary ??
      `${title}, ${formatClockTime(from, lang, multiDay)}–${formatClockTime(to, lang, multiDay)}. ${lanes
        .map((lane) => describeLane(lane, lang))
        .join('. ')}.`,
  );

  $effect(() => {
    oncursor?.(cursor);
  });
</script>

<div class="strip" bind:clientWidth={measured} data-testid="state-strip">
  <div class="head">
    <p class="readout" aria-hidden="true" data-testid="strip-readout">
      <span class="when">{formatClockTime(probe, lang, multiDay)}</span>
      {#each lanes as lane (lane.id)}
        {@const segment = segmentAt(lane.segments, probe)}
        <span class="state" class:active={segment !== null}>
          <i
            style="background: {segment
              ? (lane.states?.[segment.state]?.color ?? lane.color)
              : 'transparent'}"
          ></i>{lane.label}{segment &&
          lane.states?.[segment.state] &&
          lane.states[segment.state]?.label !== lane.label
            ? ` ${lane.states[segment.state]?.label}`
            : ''}
        </span>
      {/each}
    </p>
    {#if list}
      <Button
        variant="link"
        class="ss-link"
        aria-expanded={showList}
        onclick={() => (showList = !showList)}
        data-testid="strip-list-toggle"
        >{chartText(lang, showList ? 'hideList' : 'showList')}</Button
      >
    {/if}
  </div>
  <div class="plot">
    <svg viewBox="0 0 {width} {svgH}" {width} height={svgH} role="img" aria-label={text}>
      <g transform="translate({gutter},0)">
        <LaneRows
          {lanes}
          {sx}
          top={0}
          {innerW}
          {gutter}
          {laneHeight}
          laneGap={GAP}
          showLabels={full}
        />
        {#each ticks as tick (tick)}
          <line x1={sx(tick)} x2={sx(tick)} y1={lanesH} y2={lanesH + 4} class="grid" />
          <text x={sx(tick)} y={lanesH + 16} text-anchor="middle" class="tick"
            >{tickLabel(tick)}</text
          >
        {/each}
        {#if now !== null && now >= from && now <= to}
          <line x1={sx(now)} x2={sx(now)} y1="-2" y2={lanesH + 2} class="now" />
        {/if}
        {#if cursor !== null}
          <line x1={sx(cursor)} x2={sx(cursor)} y1="-2" y2={lanesH + 2} class="cursor" />
        {/if}
      </g>
    </svg>
    <Crosshair
      {from}
      {to}
      {times}
      bind:cursor
      label={chartText(lang, 'cursor', { title })}
      valuetext={cursor === null ? chartText(lang, 'cursorIdle') : readout}
      left={gutter}
      top={0}
      width={innerW}
      height={lanesH}
      onpick={onselect}
    />
  </div>
  <div class:visually-hidden={!showList} class="list" data-testid="strip-list">
    {#each lanes as lane (lane.id)}
      <h4>{lane.label}</h4>
      <ul data-lane={lane.id}>
        {#if lane.events}
          {#each lane.events as event, i (`${event.at}-${i}`)}
            <li>{describeEvent(event, lang, multiDay)}</li>
          {:else}
            <li>{chartText(lang, 'none')}</li>
          {/each}
        {:else}
          {#each lane.segments as segment, i (`${segment.from}-${i}`)}
            <li>
              {describeSegment(
                segment,
                lane.states?.[segment.state]?.label ?? chartText(lang, 'on'),
                lang,
                multiDay,
              )}
            </li>
          {:else}
            <li>{chartText(lang, 'none')}</li>
          {/each}
        {/if}
      </ul>
    {/each}
  </div>
</div>

<style>
  .strip {
    min-width: 0;
  }
  .head {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    margin-bottom: var(--space-1);
  }
  .readout {
    display: flex;
    flex-wrap: wrap;
    gap: var(--chart-space-1) var(--space-3);
    margin: 0;
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    color: var(--muted);
    min-height: 1.3em;
  }
  .when {
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
  .state {
    display: inline-flex;
    align-items: center;
    gap: var(--chart-space-4);
  }
  .state.active {
    color: var(--text);
    font-weight: var(--fw-semibold);
  }
  .state i {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: var(--radius-2xs);
    border: 1px solid var(--border);
  }
  :global(.ss-link) {
    min-height: 28px;
    padding: 0 var(--chart-space-5);
    border: none;
    background: none;
    color: var(--accent);
    font-size: var(--fs-sm);
    font-weight: var(--fw-semibold);
  }
  @media (--narrow), (pointer: coarse) {
    :global(.ss-link) {
      min-height: var(--tap);
      margin-block: var(--chart-bleed);
    }
  }
  .plot {
    position: relative;
  }
  svg {
    display: block;
    width: 100%;
    overflow: visible;
  }
  .grid {
    stroke: var(--border);
  }
  .tick {
    fill: var(--muted);
    font-size: var(--fs-micro);
    font-variant-numeric: tabular-nums;
  }
  .now {
    stroke: var(--text);
    stroke-dasharray: 3 3;
    opacity: 0.6;
  }
  .cursor {
    stroke: var(--text);
    opacity: 0.6;
  }
  .list {
    font-size: var(--fs-md);
    font-variant-numeric: tabular-nums;
  }
  .list h4 {
    margin: var(--space-2) 0 var(--chart-space-3);
    font-size: var(--fs-md);
  }
  .list ul {
    margin: 0;
    padding-left: var(--chart-indent);
  }
</style>
