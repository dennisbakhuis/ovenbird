<!--
  TimeChart v2: time series on stacked panels that share one x axis.

  Legacy props (v1, still supported): from, to, title, lines, bands, markers, now, nowLabel,
  height, unit, rightUnit, selected, onselect, maxGapMs. Without `panels` the chart is one panel
  built from `lines`/`bands` (right axis allowed for v1 callers only).

  New props:
  - panels: PanelSpec[] — each panel has its own y scale (label, unit, lines, bands with number
    or point bounds, rules = horizontal reference lines with a label at the left end, drawn above
    the lines, min/max/zero/snap, height in px) or is a
    lane panel (`lanes`: state lanes). Prefer one panel per unit instead of a right axis.
  - spans: SpanSpec[] shaded time ranges across all panels; night: Interval[] (see
    nightIntervals/nightByHours in lib/chart).
  - markers: MarkerSpec[] with optional `icon` (24-grid path); labels are laid out left to right
    (right-aligned near the edge); a label that would overlap drops to icon-only on a second row
    (the label stays in the tooltip, the read-out and the table).
  - legend: 'chips' (default; toggle buttons that also show the value at the crosshair, or the
    latest) | 'none'; hidden: initially hidden series ids; ontoggle(id, visible).
  - table (default true): "Show as table" toggle; summary: overrides the generated text.
  - oncursor(t | null): crosshair moves (for scrubbing); digits: default decimals.
  A11y: the SVG is role="img" with a generated summary; a slider overlay gives a keyboard
  crosshair (arrows, Shift/PageUp/PageDown, Home/End, Esc, Enter = onselect) whose
  aria-valuetext is the read-out; colour is backed by labels in chips, panels and lanes.
-->
<script lang="ts" module>
  import Button from '$ui/Button.svelte';
  import type * as Kit from './types';

  export type BandSpec = Kit.BandSpec;
  export type LaneSpec = Kit.LaneSpec;
  export type LineSpec = Kit.LineSpec;
  export type MarkerSpec = Kit.MarkerSpec;
  export type PanelSpec = Kit.PanelSpec;
  export type RuleSpec = Kit.RuleSpec;
  export type SpanSpec = Kit.SpanSpec;
</script>

<script lang="ts">
  import Pill from '$ui/Pill.svelte';
  import {
    areaPath,
    asPoints,
    axisFor,
    layoutMarkers,
    nearestIndex,
    niceStep,
    niceTicks,
    panelLayout,
    segmentAt,
    stepPath,
    timeTicks,
    unionTimes,
    valueAt,
    type Axis,
    type Interval,
    type Point,
  } from '$lib/core/chart';
  import {
    chartText,
    describeSegment,
    describeTimeChart,
    formatClockTime,
    formatNum,
    formatValue,
    tableRows,
    csvRows,
  } from '$lib/core/chartSummary';
  import { saveBlob, toCsv } from '$lib/core/download';
  import { DOWNLOAD_PREFIX } from '$lib/core/brand';
  import { timeLocale } from '$lib/core/format';
  import { settings } from '$lib/core/settings.svelte';
  import Crosshair from './Crosshair.svelte';
  import LaneRows from './LaneRows.svelte';
  import { NIGHT_FILL } from './palette';

  interface Props {
    from: number;
    to: number;
    title: string;
    lines?: LineSpec[];
    bands?: BandSpec[];
    panels?: PanelSpec[];
    markers?: MarkerSpec[];
    spans?: SpanSpec[];
    night?: Interval[];
    now?: number | null;
    nowLabel?: string;
    height?: number;
    unit?: string;
    rightUnit?: string;
    selected?: number | null;
    onselect?: (t: number) => void;
    oncursor?: (t: number | null) => void;
    maxGapMs?: number;
    legend?: 'chips' | 'none';
    hidden?: string[];
    ontoggle?: (id: string, visible: boolean) => void;
    table?: boolean;
    summary?: string;
    digits?: number;
  }

  let {
    from,
    to,
    title,
    lines = [],
    bands = [],
    panels,
    markers = [],
    spans = [],
    night = [],
    now = null,
    nowLabel = '',
    height = 240,
    unit = '°C',
    rightUnit = '°C',
    selected = null,
    onselect,
    oncursor,
    maxGapMs,
    legend = 'chips',
    hidden: initiallyHidden = [],
    ontoggle,
    table = true,
    summary,
    digits = 1,
  }: Props = $props();

  const uid = $props.id();
  const LANE_HEIGHT = 14;
  const LANE_GAP = 4;
  const PANEL_GAP = 22;
  const BOTTOM = 22;

  let measured = $state(0);
  let cursor = $state<number | null>(null);
  let showTable = $state(false);
  let toggled = $state<string[]>([]);

  const visible = (id: string) => initiallyHidden.includes(id) === toggled.includes(id);
  const width = $derived(measured > 0 ? measured : 600);
  const compact = $derived(width < 480);
  const lang = $derived(settings.language);
  const legacy = $derived(panels === undefined);
  const specs = $derived<PanelSpec[]>(panels ?? [{ id: 'main', unit, rightUnit, lines, bands }]);
  const allLanes = $derived(specs.flatMap((p) => p.lanes ?? []));
  const gutter = $derived(allLanes.length > 0 && !compact ? 96 : 38);
  const hasRight = $derived(
    specs.some((p) => (p.lines ?? []).some((l) => l.axis === 'right' && visible(l.id))),
  );
  const pad = $derived({
    left: gutter,
    right: hasRight ? 38 : 10,
    top:
      (markers.length > 0 ? 30 : nowLabel ? 14 : 6) +
      (!legacy && (specs[0]?.label || specs[0]?.unit) && !specs[0]?.lanes?.length ? 14 : 0),
    bottom: BOTTOM,
  });
  const innerW = $derived(Math.max(width - pad.left - pad.right, 10));
  const gapMs = $derived(maxGapMs ?? Math.max((to - from) / 60, 20 * 60_000));
  const multiDay = $derived(to - from > 40 * 3_600_000);

  const heights = $derived.by(() => {
    if (legacy) return [Math.max(height - pad.top - pad.bottom, 40)];
    return specs.map((p) =>
      p.lanes && p.lanes.length > 0
        ? p.lanes.length * (LANE_HEIGHT + LANE_GAP) - LANE_GAP
        : (p.height ?? (compact ? 110 : 140)),
    );
  });
  const boxes = $derived(panelLayout(heights, PANEL_GAP, 0));
  const plotH = $derived.by(() => {
    const last = boxes[boxes.length - 1];
    return last ? last.top + last.height : 0;
  });
  const svgH = $derived(pad.top + plotH + pad.bottom);

  const sx = (t: number) => ((t - from) / Math.max(to - from, 1)) * innerW;

  function boundPoints(band: BandSpec): { upper: Point[]; lower: Point[] } {
    const upperList = typeof band.upper === 'number' ? null : band.upper;
    const lowerList = typeof band.lower === 'number' ? null : band.lower;
    const like = (value: Point[] | number, other: Point[] | null) =>
      typeof value === 'number'
        ? other
          ? other.map(([t]): Point => [t, value])
          : asPoints(value, from, to)
        : value;
    return { upper: like(band.upper, lowerList), lower: like(band.lower, upperList) };
  }

  interface BuiltPanel {
    spec: PanelSpec;
    top: number;
    height: number;
    lanes: LaneSpec[];
    lines: LineSpec[];
    bands: { band: BandSpec; upper: Point[]; lower: Point[] }[];
    left: Axis | null;
    right: Axis | null;
    syLeft: (v: number) => number;
    syRight: (v: number) => number;
    ticksLeft: number[];
    ticksRight: number[];
    stepLeft: number;
    stepRight: number;
  }

  const syFor = (axis: Axis | null, h: number) => (v: number) =>
    axis ? h - ((v - axis.min) / Math.max(axis.max - axis.min, 1e-9)) * h : h;

  const built = $derived<BuiltPanel[]>(
    specs.map((spec, index) => {
      const box = boxes[index] ?? { top: 0, height: 40 };
      const shown = (spec.lines ?? []).filter((l) => visible(l.id));
      const shownBands = (spec.bands ?? [])
        .filter((b) => visible(b.id))
        .map((band) => ({ band, ...boundPoints(band) }));
      const leftLists = [
        ...shown.filter((l) => l.axis !== 'right').map((l) => l.points),
        ...shownBands.filter((b) => b.band.axis !== 'right').flatMap((b) => [b.upper, b.lower]),
        ...(spec.rules ?? []).map((r): Point[] => [[from, r.value]]),
      ];
      const rightLists = [
        ...shown.filter((l) => l.axis === 'right').map((l) => l.points),
        ...shownBands.filter((b) => b.band.axis === 'right').flatMap((b) => [b.upper, b.lower]),
      ];
      const left = axisFor(leftLists, {
        min: spec.min,
        max: spec.max,
        zero: spec.zero,
        snap: spec.snap ?? (legacy ? 1 : undefined),
      });
      const right = rightLists.length > 0 ? axisFor(rightLists, { pad: 0.15, snap: 0.5 }) : null;
      const count = Math.max(2, Math.min(compact ? 4 : 5, Math.floor(box.height / 30)));
      const ticksFor = (axis: Axis | null) =>
        axis ? niceTicks(axis.min, axis.max, count, 1e-9) : [];
      const stepOf = (axis: Axis | null) => (axis ? niceStep((axis.max - axis.min) / count) : 1);
      return {
        spec,
        top: box.top,
        height: box.height,
        lanes: spec.lanes ?? [],
        lines: shown,
        bands: shownBands,
        left,
        right,
        syLeft: syFor(left, box.height),
        syRight: syFor(right, box.height),
        ticksLeft: ticksFor(left),
        ticksRight: ticksFor(right),
        stepLeft: stepOf(left),
        stepRight: stepOf(right),
      };
    }),
  );

  const tickText = (value: number, step: number) =>
    formatNum(value, Math.max(0, -Math.floor(Math.log10(step) + 1e-9)), lang);

  const xTicks = $derived(timeTicks(from, to, compact ? 4 : 6));

  function xTickLabel(t: number): string {
    const date = new Date(t);
    if (multiDay && date.getHours() === 0 && date.getMinutes() === 0)
      return date.toLocaleDateString(timeLocale(lang), { weekday: 'short', day: 'numeric' });
    return formatClockTime(t, lang);
  }

  function linePath(line: LineSpec, panel: BuiltPanel): string {
    const sy = line.axis === 'right' ? panel.syRight : panel.syLeft;
    const gap = line.maxGapMs ?? gapMs;
    if (line.step) return stepPath(line.points, sx, sy, gap, now ?? to);
    let path = '';
    let previous: number | null = null;
    for (const [t, v] of line.points) {
      const command = previous === null || t - previous > gap ? 'M' : 'L';
      path += `${command}${sx(t).toFixed(1)},${sy(v).toFixed(1)}`;
      previous = t;
    }
    return path;
  }

  const allLines = $derived(
    specs.flatMap((p) => (p.lines ?? []).map((line) => ({ line, panel: p }))),
  );
  const shownLines = $derived(allLines.filter(({ line }) => visible(line.id)));
  const lineUnit = (line: LineSpec, panel: PanelSpec) =>
    line.unit ?? (line.axis === 'right' ? (panel.rightUnit ?? rightUnit) : (panel.unit ?? unit));

  const times = $derived.by(() => {
    const lists = shownLines.map(({ line }) => line.points.filter(([t]) => t >= from && t <= to));
    const merged = unionTimes(lists);
    if (merged.length > 0 || allLanes.length === 0) return merged;
    return unionTimes(
      allLanes.map((lane) => lane.segments.map((s): Point => [Math.max(s.from, from), 0])),
    );
  });

  function shownValue(line: LineSpec, t: number | null): number | null {
    if (t === null) return line.points[line.points.length - 1]?.[1] ?? null;
    return (
      valueAt(line.points, t, line.step ? 'step' : 'nearest', line.maxGapMs ?? gapMs)?.[1] ?? null
    );
  }

  function laneStateLabel(lane: LaneSpec, t: number): string {
    const segment = segmentAt(lane.segments, t);
    if (!segment) return chartText(lang, 'off');
    return lane.states?.[segment.state]?.label ?? lane.label;
  }

  const legendLines = $derived(allLines.filter(({ line }) => !line.hideInLegend));
  const legendBands = $derived(
    specs.flatMap((p) => (p.bands ?? []).filter((b) => !b.hideInLegend)),
  );

  const readoutText = $derived.by(() => {
    if (cursor === null) return chartText(lang, 'cursorIdle');
    const at = cursor;
    const parts = shownLines.map(
      ({ line, panel }) =>
        `${line.label} ${formatValue(shownValue(line, at), lineUnit(line, panel), line.digits ?? panel.digits ?? digits, lang)}`,
    );
    for (const lane of allLanes) parts.push(`${lane.label} ${laneStateLabel(lane, at)}`);
    return `${formatClockTime(at, lang, multiDay)}: ${parts.join(', ')}`;
  });

  const summaryText = $derived(
    summary ??
      describeTimeChart(
        title,
        from,
        to,
        shownLines.map(({ line, panel }) => ({
          label: line.label,
          unit: lineUnit(line, panel),
          points: line.points.filter(([t]) => t >= from && t <= to),
          digits: line.digits ?? panel.digits ?? digits,
        })),
        allLanes,
        lang,
      ),
  );

  const inRange = (t: number | null): t is number => t !== null && t >= from && t <= to;

  const markerTextWidth = (label: string) => Math.ceil(label.length * 6.2);
  const markerLayout = $derived(
    layoutMarkers(
      markers.map((m) => ({
        x: sx(m.t),
        width: markerTextWidth(m.label) + (m.icon ? 14 : 4),
      })),
      innerW,
      8,
    ),
  );
  const showNowLabel = $derived.by(() => {
    if (!inRange(now) || !nowLabel) return false;
    const end = sx(now) - 4;
    const start = end - markerTextWidth(nowLabel);
    if (start < 0) return false;
    return markers.every((m, i) => {
      const placed = markerLayout[i];
      if (!placed?.label || !inRange(m.t)) return true;
      const x = sx(m.t);
      const w = markerTextWidth(m.label) + (m.icon ? 14 : 4);
      const [a, b] = placed.align === 'start' ? [x - 6, x + w] : [x - w, x + 6];
      return b + 6 <= start || a >= end + 6;
    });
  });

  const hasData = $derived(
    specs.some(
      (p) =>
        (p.lines ?? []).some((l) => l.points.length > 0) ||
        (p.lanes ?? []).length > 0 ||
        (p.bands ?? []).length > 0,
    ),
  );

  const rows = $derived(
    showTable
      ? tableRows(
          shownLines.map(({ line }) => ({
            points: line.points,
            step: line.step,
            maxDistMs: line.maxGapMs,
          })),
          from,
          to,
          compact ? 12 : 24,
          gapMs,
        )
      : [],
  );

  function downloadCsv(): void {
    const header = [
      'time',
      ...shownLines.map(({ line, panel }) => `${line.label} (${lineUnit(line, panel)})`),
    ];
    const body = csvRows(
      shownLines.map(({ line }) => ({
        points: line.points,
        step: line.step,
        maxDistMs: line.maxGapMs,
      })),
      gapMs,
    );
    const stamp = new Date(from).toISOString().slice(0, 16).replace(/:/g, '');
    const slug = title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '');
    saveBlob(
      new Blob([toCsv(header, body)], { type: 'text/csv;charset=utf-8' }),
      `${DOWNLOAD_PREFIX}${slug || 'chart'}-${stamp}.csv`,
    );
  }

  function toggle(id: string): void {
    const nowVisible = !visible(id);
    toggled = toggled.includes(id) ? toggled.filter((h) => h !== id) : [...toggled, id];
    ontoggle?.(id, nowVisible);
  }

  function pick(t: number): void {
    if (!onselect) return;
    const first = shownLines.find(({ line }) => line.points.length > 0)?.line;
    if (!first) return onselect(t);
    const index = nearestIndex(
      first.points.map(([pt]) => pt),
      t,
    );
    const point = first.points[index];
    if (point) onselect(point[0]);
  }

  $effect(() => {
    oncursor?.(cursor);
  });
</script>

<figure class="chart" bind:clientWidth={measured} data-testid="chart">
  {#if hasData}
    <div class="head">
      <span class="when" aria-hidden="true" data-testid="chart-when"
        >{cursor !== null
          ? formatClockTime(cursor, lang, multiDay)
          : chartText(lang, 'latest')}</span
      >
      {#if legend === 'chips'}
        <ul class="chips" data-testid="chart-legend">
          {#each legendLines as { line, panel } (line.id)}
            {@const on = visible(line.id)}
            <li>
              <Pill
                interactive
                tone="plain"
                class="tc-chip {on ? '' : 'off'}"
                pressed={on}
                onclick={() => toggle(line.id)}
              >
                <svg width="16" height="8" aria-hidden="true">
                  <line
                    x1="1"
                    x2="15"
                    y1="4"
                    y2="4"
                    stroke={line.color}
                    stroke-width="3"
                    stroke-linecap="round"
                    stroke-dasharray={line.dash}
                  />
                </svg>
                <span>{line.label}</span>
                {#if on}
                  <strong
                    >{formatValue(
                      shownValue(line, cursor),
                      lineUnit(line, panel),
                      line.digits ?? panel.digits ?? digits,
                      lang,
                    )}</strong
                  >
                {/if}
              </Pill>
            </li>
          {/each}
          {#each legendBands as band (band.id)}
            {@const on = visible(band.id)}
            <li>
              <Pill
                interactive
                tone="plain"
                class="tc-chip {on ? '' : 'off'}"
                pressed={on}
                onclick={() => toggle(band.id)}
              >
                <svg width="16" height="10" aria-hidden="true">
                  <rect
                    width="16"
                    height="10"
                    rx="2"
                    fill={band.color}
                    fill-opacity={Math.max(band.opacity ?? 0.3, 0.3)}
                  />
                </svg>
                <span>{band.label}</span>
              </Pill>
            </li>
          {/each}
        </ul>
      {/if}
      {#if table}
        <Button
          variant="link"
          class="tc-link"
          aria-expanded={showTable}
          data-testid="chart-table-toggle"
          onclick={() => (showTable = !showTable)}
          >{chartText(lang, showTable ? 'hideTable' : 'showTable')}</Button
        >
        {#if showTable && shownLines.length > 0}
          <Button variant="link" class="tc-link" data-testid="chart-table-csv" onclick={downloadCsv}
            >{chartText(lang, 'downloadCsv')}</Button
          >
        {/if}
      {/if}
    </div>

    <div class="plot">
      <svg
        viewBox="0 0 {width} {svgH}"
        {width}
        height={svgH}
        role="img"
        aria-label={summaryText}
        data-testid="time-chart"
      >
        <defs>
          {#each built as panel, i (panel.spec.id)}
            <clipPath id="{uid}-clip-{i}">
              <rect x="0" y={panel.top - 2} width={innerW} height={panel.height + 4} />
            </clipPath>
          {/each}
        </defs>
        <g transform="translate({pad.left},{pad.top})">
          {#each night as interval (interval.from)}
            <rect
              x={sx(interval.from)}
              y="0"
              width={Math.max(sx(interval.to) - sx(interval.from), 0)}
              height={plotH}
              fill={NIGHT_FILL}
              data-testid="chart-night"
            />
          {/each}
          {#each spans as span, i (`${span.from}-${i}`)}
            <rect
              x={sx(Math.max(span.from, from))}
              y="0"
              width={Math.max(sx(Math.min(span.to, to)) - sx(Math.max(span.from, from)), 0)}
              height={plotH}
              fill={span.color ?? 'var(--muted)'}
              fill-opacity={span.opacity ?? 0.12}
            >
              {#if span.label}<title>{span.label}</title>{/if}
            </rect>
          {/each}

          {#each built as panel, i (panel.spec.id)}
            {#if panel.lanes.length > 0}
              <LaneRows
                lanes={panel.lanes}
                {sx}
                top={panel.top}
                {innerW}
                gutter={pad.left}
                laneHeight={LANE_HEIGHT}
                laneGap={LANE_GAP}
                showLabels={!compact}
              />
            {:else}
              <g transform="translate(0,{panel.top})">
                {#each panel.ticksLeft as tick (tick)}
                  <line
                    x1="0"
                    x2={innerW}
                    y1={panel.syLeft(tick)}
                    y2={panel.syLeft(tick)}
                    class="grid"
                  />
                  <text x="-6" y={panel.syLeft(tick)} dy="0.32em" text-anchor="end" class="tick"
                    >{tickText(tick, panel.stepLeft)}</text
                  >
                {/each}
                {#each panel.ticksRight as tick (tick)}
                  <text x={innerW + 6} y={panel.syRight(tick)} dy="0.32em" class="tick"
                    >{tickText(tick, panel.stepRight)}</text
                  >
                {/each}
                <g clip-path="url(#{uid}-clip-{i})" transform="translate(0,{-panel.top})">
                  <g transform="translate(0,{panel.top})">
                    {#each panel.bands as { band, upper, lower } (band.id)}
                      <path
                        d={areaPath(
                          upper,
                          lower,
                          sx,
                          band.axis === 'right' ? panel.syRight : panel.syLeft,
                        )}
                        fill={band.color}
                        fill-opacity={band.opacity ?? 0.3}
                        stroke="none"
                      />
                    {/each}
                    {#each panel.spec.rules ?? [] as rule (rule.value)}
                      <line
                        x1="0"
                        x2={innerW}
                        y1={panel.syLeft(rule.value)}
                        y2={panel.syLeft(rule.value)}
                        stroke={rule.color ?? 'var(--muted)'}
                        stroke-dasharray={rule.dash ?? '4 3'}
                        class="rule"
                      />
                    {/each}
                    {#each panel.lines as line (line.id)}
                      {#if line.points.length > 0}
                        <path
                          d={linePath(line, panel)}
                          fill="none"
                          stroke={line.color}
                          stroke-width={line.width ?? 2}
                          stroke-dasharray={line.dash}
                          stroke-linejoin="round"
                          stroke-linecap="round"
                          data-line={line.id}
                        />
                      {/if}
                    {/each}
                    {#each panel.spec.rules ?? [] as rule (rule.value)}
                      {#if rule.label}
                        {@const y = panel.syLeft(rule.value)}
                        <text
                          x="4"
                          y={y < 14 ? y + 12 : y - 4}
                          class="rule-label"
                          data-testid="rule-label">{rule.label}</text
                        >
                      {/if}
                    {/each}
                    {#if inRange(cursor)}
                      {#each panel.lines as line (line.id)}
                        {@const v = shownValue(line, cursor)}
                        {#if v !== null}
                          <circle
                            cx={sx(cursor)}
                            cy={(line.axis === 'right' ? panel.syRight : panel.syLeft)(v)}
                            r="3.5"
                            fill={line.color}
                            class="dot"
                          />
                        {/if}
                      {/each}
                    {/if}
                  </g>
                </g>
                {#if panel.spec.label || (!legacy && panel.spec.unit)}
                  <text x="2" y="-5" class="panel-label"
                    >{panel.spec.label ?? ''}{panel.spec.label && panel.spec.unit
                      ? ` · ${panel.spec.unit}`
                      : (panel.spec.unit ?? '')}</text
                  >
                {/if}
              </g>
            {/if}
          {/each}

          {#each xTicks as tick (tick)}
            <line x1={sx(tick)} x2={sx(tick)} y1={plotH} y2={plotH + 4} class="grid" />
            <text x={sx(tick)} y={plotH + 16} text-anchor="middle" class="tick"
              >{xTickLabel(tick)}</text
            >
          {/each}

          {#each markers as marker, i (`${marker.t}-${marker.label}`)}
            {@const x = sx(marker.t)}
            {@const placed = markerLayout[i]}
            {@const color = marker.color ?? 'var(--muted)'}
            {@const end = placed?.align === 'end'}
            {#if marker.t >= from && marker.t <= to}
              <g class="marker" data-testid="chart-marker">
                <title>{marker.label} · {formatClockTime(marker.t, lang, multiDay)}</title>
                <line
                  x1={x}
                  x2={x}
                  y1={placed?.label ? -pad.top + 13 : marker.icon ? -pad.top + 27 : -4}
                  y2={plotH}
                  stroke={color}
                />
                {#if placed?.label}
                  {#if marker.icon}
                    <path
                      d={marker.icon}
                      transform="translate({x - 6},{-pad.top + 1}) scale(0.5)"
                      class="marker-icon"
                      stroke={color}
                    />
                  {/if}
                  <text
                    x={x + (end ? -1 : 1) * (marker.icon ? 8 : 3)}
                    y={-pad.top + 10}
                    text-anchor={end ? 'end' : 'start'}
                    class="marker-label"
                    data-testid="chart-marker-label">{marker.label}</text
                  >
                {:else if marker.icon}
                  <path
                    d={marker.icon}
                    transform="translate({x - 6},{-pad.top + 15}) scale(0.5)"
                    class="marker-icon"
                    stroke={color}
                  />
                {:else}
                  <circle cx={x} cy="-4" r="2.5" fill={color} />
                {/if}
              </g>
            {/if}
          {/each}

          {#if inRange(now)}
            <line x1={sx(now)} x2={sx(now)} y1="0" y2={plotH} class="now" />
            {#if showNowLabel}
              <text x={sx(now) - 4} y={-pad.top + 10} text-anchor="end" class="now-label"
                >{nowLabel}</text
              >
            {/if}
          {/if}
          {#if inRange(selected)}
            <line x1={sx(selected)} x2={sx(selected)} y1="0" y2={plotH} class="selected" />
          {/if}
          {#if inRange(cursor)}
            <line x1={sx(cursor)} x2={sx(cursor)} y1="0" y2={plotH} class="cursor" />
          {/if}
        </g>
      </svg>
      <Crosshair
        {from}
        {to}
        {times}
        bind:cursor
        label={chartText(lang, 'cursor', { title })}
        valuetext={readoutText}
        left={pad.left}
        top={pad.top}
        width={innerW}
        height={plotH}
        onpick={onselect ? pick : undefined}
      />
    </div>

    {#if showTable}
      <div class="table-wrap" data-testid="chart-table">
        {#if shownLines.length > 0}
          <table>
            <caption class="visually-hidden">{title}</caption>
            <thead>
              <tr>
                <th scope="col">{chartText(lang, 'time')}</th>
                {#each shownLines as { line, panel } (line.id)}
                  <th scope="col" class="num">{line.label} ({lineUnit(line, panel)})</th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each rows as row (row.t)}
                <tr>
                  <th scope="row">{formatClockTime(row.t, lang, multiDay)}</th>
                  {#each row.values as value, i (i)}
                    {@const entry = shownLines[i]}
                    <td class="num"
                      >{formatValue(
                        value,
                        '',
                        entry ? (entry.line.digits ?? entry.panel.digits ?? digits) : digits,
                        lang,
                      )}</td
                    >
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
        {#each allLanes as lane (lane.id)}
          <h4>{lane.label}</h4>
          <ul class="segments">
            {#each lane.segments as segment, i (`${segment.from}-${i}`)}
              <li>
                {describeSegment(
                  segment,
                  lane.states?.[segment.state]?.label ?? lane.label,
                  lang,
                  multiDay,
                )}
              </li>
            {:else}
              <li>{chartText(lang, 'none')}</li>
            {/each}
          </ul>
        {/each}
      </div>
    {/if}
  {/if}
</figure>

<style>
  .chart {
    margin: 0;
    min-width: 0;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    margin-bottom: var(--space-1);
  }
  .when {
    font-size: var(--fs-sm);
    font-weight: var(--fw-semibold);
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    min-width: 3.2rem;
  }
  .chips {
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin: 0;
    padding: 0;
    order: 3;
    flex: 1 1 100%;
    min-width: 0;
  }
  :global(.tc-chip) {
    display: inline-flex;
    align-items: center;
    gap: var(--chart-space-4);
    min-height: 32px;
    padding: var(--chart-space-2) var(--chart-space-6);
    border-radius: var(--radius-pill);
    font-size: var(--fs-sm);
    font-weight: var(--fw-medium);
    background: var(--surface);
  }
  :global(.tc-chip) strong {
    font-variant-numeric: tabular-nums;
    font-weight: var(--fw-bold);
  }
  :global(.tc-chip.off) {
    color: var(--muted);
    border-style: dashed;
  }
  :global(.tc-chip.off) span {
    text-decoration: line-through;
  }
  :global(.tc-chip.off) svg {
    opacity: 0.4;
  }
  :global(.tc-link) {
    min-height: 32px;
    padding: var(--chart-space-2) var(--chart-space-5);
    border: none;
    background: none;
    color: var(--accent);
    font-size: var(--fs-sm);
    font-weight: var(--fw-semibold);
    margin-left: auto;
  }
  .plot {
    position: relative;
  }
  @media (--narrow), (pointer: coarse) {
    :global(.tc-chip) {
      position: relative;
      isolation: isolate;
      min-height: var(--tap);
      margin-block: var(--chart-bleed-sm);
      border-color: transparent;
      background: transparent;
    }
    :global(.tc-chip)::before {
      content: '';
      position: absolute;
      inset: 6px 0;
      z-index: -1;
      border: 1px solid var(--border);
      border-radius: var(--radius-pill);
      background: var(--surface);
    }
    :global(.tc-chip.off)::before {
      border-style: dashed;
    }
    :global(.tc-chip):hover:not(:disabled) {
      border-color: transparent;
    }
    :global(.tc-chip):hover:not(:disabled)::before {
      border-color: var(--accent);
    }
    :global(.tc-link) {
      min-height: var(--tap);
      margin-block: var(--chart-bleed-sm);
    }
  }
  svg[role='img'] {
    display: block;
    width: 100%;
    overflow: visible;
  }
  .grid {
    stroke: var(--border);
    stroke-width: 1;
  }
  .tick {
    fill: var(--muted);
    font-size: var(--fs-micro);
    font-variant-numeric: tabular-nums;
  }
  .panel-label {
    fill: var(--muted);
    font-size: var(--fs-micro);
    font-weight: var(--fw-semibold);
    paint-order: stroke;
    stroke: var(--surface);
    stroke-width: 3px;
    stroke-linejoin: round;
  }
  .rule {
    stroke-width: 1;
  }
  .rule-label {
    fill: var(--muted);
    font-size: var(--fs-micro);
    font-weight: var(--fw-semibold);
    paint-order: stroke;
    stroke: var(--surface);
    stroke-width: 4px;
    stroke-linejoin: round;
  }
  .marker line {
    stroke-width: 1;
    stroke-dasharray: 2 3;
  }
  .marker-icon {
    fill: none;
    stroke-width: 3;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .marker-label {
    fill: var(--chart-axis);
    font-size: var(--fs-chart-tick);
    font-weight: var(--fw-semibold);
    paint-order: stroke;
    stroke: var(--surface);
    stroke-width: 3px;
    stroke-linejoin: round;
  }
  .now {
    stroke: var(--text);
    stroke-width: 1;
    stroke-dasharray: 4 3;
    opacity: 0.6;
  }
  .now-label {
    fill: var(--muted);
    font-size: var(--fs-chart-tick);
  }
  .selected {
    stroke: var(--accent);
    stroke-width: 2;
  }
  .cursor {
    stroke: var(--text);
    stroke-width: 1;
    opacity: 0.55;
  }
  .dot {
    stroke: var(--surface);
    stroke-width: 2;
  }
  .table-wrap {
    overflow-x: auto;
    margin-top: var(--space-2);
    max-height: 22rem;
  }
  .table-wrap th[scope='row'] {
    font-weight: var(--fw-medium);
    font-variant-numeric: tabular-nums;
  }
  .table-wrap .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .table-wrap h4 {
    margin: var(--space-3) 0 var(--space-1);
    font-size: var(--fs-md);
  }
  .segments {
    margin: 0;
    padding-left: var(--chart-indent);
    font-size: var(--fs-md);
    font-variant-numeric: tabular-nums;
  }
</style>
