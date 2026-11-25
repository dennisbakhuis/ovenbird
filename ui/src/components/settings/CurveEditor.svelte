<!--
  CurveEditor: the heating curve as draggable points on outside °C × water °C.

  Draws the safety envelope band (anchored to the emitter preset), the min setpoint and max
  supply lines, the last 7 days of issued setpoints as a density band per outside degree,
  the active curve (grey), the draft (accent) with the area between them shaded, today's
  operating point (diamond on top, arrow to the issued setpoint) and the 48 h forecast range on
  the x axis. A fixed read-out row above the plot shows the focused/dragged point, or today's
  value and what the draft changes there.

  Water moves in whole degrees (drag, arrow keys, ± buttons); hold Shift for 0.5 K. Outside
  moves in 1 °C. The number table sits under the chart (collapsed on phones).
  A11y: each point is a slider (arrows, Delete); the plot has a generated summary.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import {
    addPoint,
    cornerSamples,
    curveWater,
    densityBins,
    MAX_POINTS,
    MIN_POINTS,
    OUTSIDE_GAP,
    OUTSIDE_MAX,
    OUTSIDE_MIN,
    removePoint,
    sameCurve,
    setOutside,
    setWater,
    WATER_FINE_STEP,
    WATER_STEP,
    type Curve,
  } from '$lib/core/curve';
  import { niceTicks } from '$lib/core/chart';
  import { curveText, formatDelta } from '$lib/core/fieldFormat';
  import { formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import Details from '$ui/Details.svelte';
  import Icon from '$ui/Icon.svelte';
  import Stepper from '$ui/Stepper.svelte';
  import Why from '$ui/Why.svelte';
  import { NARROW_QUERY } from '$lib/core/breakpoints';

  interface Props {
    points: Curve;
    active: Curve;
    preset?: Curve | null;
    envelope: { curve: Curve; below_k: number; above_k: number };
    limits: { min: number; max: number };
    operating?: {
      outside: number;
      curve: number;
      issued: number | null;
      sent?: boolean;
    } | null;
    dots?: [number, number][];
    forecastRange?: [number, number] | null;
    disabled?: boolean;
    onchange: (points: Curve) => void;
  }

  let {
    points,
    active,
    preset = null,
    envelope,
    limits,
    operating = null,
    dots = [],
    forecastRange = null,
    disabled = false,
    onchange,
  }: Props = $props();

  const narrow =
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(NARROW_QUERY).matches
      : false;
  const HEIGHT = narrow ? 260 : 300;
  const uid = Math.random().toString(36).slice(2, 8);
  const clipId = `curve-clip-${uid}`;
  const waterLimits = $derived({ waterMin: limits.min, waterMax: limits.max });
  const locale = $derived(settings.language);

  let measured = $state(0);
  const width = $derived(measured > 0 ? measured : 560);
  const pad = { left: 34, right: 10, top: 14, bottom: 26 };
  const innerW = $derived(Math.max(width - pad.left - pad.right, 100));
  const innerH = HEIGHT - pad.top - pad.bottom;

  const xMin = $derived(Math.min(-15, (points[0]?.[0] ?? -15) - 2));
  const xMax = $derived(Math.max(20, (points[points.length - 1]?.[0] ?? 20) + 2));

  const bandSamples = $derived.by(() => {
    const out: number[] = [];
    for (let x = xMin; x <= xMax; x += 1) out.push(x);
    return out;
  });
  const bandHigh = $derived(
    bandSamples.map((x) => curveWater(envelope.curve, x) + envelope.above_k),
  );
  const bandLow = $derived(
    bandSamples.map((x) => curveWater(envelope.curve, x) - envelope.below_k),
  );
  const bins = $derived(densityBins(dots, 1).filter((b) => b.outside >= xMin && b.outside <= xMax));
  const maxCount = $derived(Math.max(1, ...bins.map((b) => b.count)));

  const yMin = $derived(
    Math.floor(Math.min(limits.min, ...bandLow, ...points.map((p) => p[1])) - 1),
  );
  const yMax = $derived(
    Math.ceil(Math.max(limits.max, ...points.map((p) => p[1]), ...active.map((p) => p[1])) + 2),
  );

  const sx = (x: number) => ((x - xMin) / (xMax - xMin)) * innerW;
  const sy = (y: number) => innerH - ((y - yMin) / (yMax - yMin)) * innerH;
  const ix = (px: number) => xMin + (px / innerW) * (xMax - xMin);
  const iy = (py: number) => yMin + ((innerH - py) / innerH) * (yMax - yMin);
  const xy = (x: number, y: number) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`;

  const path = (curve: Curve) => {
    if (curve.length === 0) return '';
    const xs = cornerSamples(curve, curve, xMin, xMax);
    return 'M' + xs.map((x) => xy(x, curveWater(curve, x))).join('L');
  };
  const bandPath = $derived(
    'M' +
      bandSamples.map((x, i) => xy(x, bandHigh[i] as number)).join('L') +
      'L' +
      [...bandSamples]
        .reverse()
        .map((x, i) => xy(x, bandLow[bandSamples.length - 1 - i] as number))
        .join('L') +
      'Z',
  );
  const changed = $derived(!sameCurve(points, active));
  const diffPath = $derived.by(() => {
    if (!changed || active.length === 0) return '';
    const xs = cornerSamples(active, points, xMin, xMax);
    return (
      'M' +
      xs.map((x) => xy(x, curveWater(points, x))).join('L') +
      'L' +
      [...xs]
        .reverse()
        .map((x) => xy(x, curveWater(active, x)))
        .join('L') +
      'Z'
    );
  });

  const yTicks = $derived(niceTicks(yMin, yMax, narrow ? 5 : 6));
  const xTicks = $derived(niceTicks(xMin, xMax, narrow ? 5 : 7));
  const fmt = (v: number) => formatNumber(v, 1, locale).replace('-', '−');
  const binW = $derived(Math.max(3, (sx(1) - sx(0)) * 0.7));

  let svg: SVGSVGElement | undefined = $state();
  let dragging = $state<number | null>(null);
  let focused = $state<number | null>(null);
  const pointer = $derived(dragging ?? focused);

  const draftNow = $derived(operating && changed ? curveWater(points, operating.outside) : null);
  const readout = $derived.by(() => {
    const p = pointer === null ? undefined : points[pointer];
    if (p && pointer !== null)
      return {
        kind: 'point' as const,
        text: t('curveReadPoint', { n: pointer + 1, outside: fmt(p[0]), water: fmt(p[1]) }),
      };
    if (!operating) return null;
    return { kind: 'now' as const };
  });

  const summary = $derived.by(() => {
    const now = curveText(active, locale);
    const parts = [t('curveSummaryActive', { water: now.water, outside: now.outside })];
    if (changed) {
      const next = curveText(points, locale);
      parts.push(t('curveSummaryDraft', { water: next.water, outside: next.outside }));
    }
    if (operating)
      parts.push(
        t('curveSummaryNow', { outside: fmt(operating.outside), water: fmt(operating.curve) }),
      );
    return parts.join(' ');
  });

  function emit(next: Curve): void {
    if (!sameCurve(next, points)) onchange(next);
  }

  function dragTo(index: number, event: PointerEvent): void {
    if (!svg) return;
    const box = svg.getBoundingClientRect();
    const outside = ix(event.clientX - box.left - pad.left);
    const water = iy(event.clientY - box.top - pad.top);
    const snap = event.shiftKey ? WATER_FINE_STEP : WATER_STEP;
    emit(setOutside(setWater(points, index, water, waterLimits, snap), index, outside));
  }

  function onKey(index: number, event: KeyboardEvent): void {
    if (disabled) return;
    const p = points[index];
    if (!p) return;
    const step = event.shiftKey ? WATER_FINE_STEP : WATER_STEP;
    const up = (dir: 1 | -1) => {
      const base = dir > 0 ? Math.floor(p[1] / step) * step : Math.ceil(p[1] / step) * step;
      return setWater(points, index, base + dir * step, waterLimits, step);
    };
    let next: Curve | null = null;
    if (event.key === 'ArrowUp') next = up(1);
    else if (event.key === 'ArrowDown') next = up(-1);
    else if (event.key === 'ArrowRight') next = setOutside(points, index, p[0] + 1);
    else if (event.key === 'ArrowLeft') next = setOutside(points, index, p[0] - 1);
    else if ((event.key === 'Delete' || event.key === 'Backspace') && points.length > MIN_POINTS)
      next = removePoint(points, index);
    if (next) {
      event.preventDefault();
      emit(next);
    }
  }

  const waterRange = (index: number) => {
    const upper = index > 0 ? (points[index - 1] as [number, number])[1] : limits.max;
    const lower =
      index < points.length - 1 ? (points[index + 1] as [number, number])[1] : limits.min;
    return { min: Math.max(lower, limits.min), max: upper };
  };
  const outsideRange = (index: number) => ({
    min: index > 0 ? (points[index - 1] as [number, number])[0] + OUTSIDE_GAP : OUTSIDE_MIN,
    max:
      index < points.length - 1
        ? (points[index + 1] as [number, number])[0] - OUTSIDE_GAP
        : OUTSIDE_MAX,
  });
</script>

<div class="editor" data-testid="curve-editor">
  <div
    class="readout"
    aria-live="polite"
    data-testid="curve-readout"
    data-help="settings/curve.readout"
  >
    {#if readout?.kind === 'point'}
      <span class="read-point"><Icon name="edit" size={16} />{readout.text}</span>
    {:else if readout?.kind === 'now' && operating}
      <span class="read-now">
        <span class="diamond" aria-hidden="true"></span>
        {t('curveReadNow', { outside: fmt(operating.outside) })}
        <strong>{fmt(operating.curve)}&#8239;°C</strong>
        {#if draftNow !== null}
          <Icon name="arrowRight" size={14} />
          <strong class="draft-value" data-testid="curve-draft-now">{fmt(draftNow)}&#8239;°C</strong
          >
          <span class="delta">{formatDelta(operating.curve, draftNow, locale)}&#8239;K</span>
        {/if}
        {#if operating.issued !== null}
          <span class="issued-note"
            >· {t(operating.sent === false ? 'curveReadWouldSend' : 'curveReadIssued', {
              water: fmt(operating.issued),
            })}</span
          >
        {/if}
      </span>
    {:else}
      <span class="muted">{t('curveReadIdle')}</span>
    {/if}
    <Why title={t('curveHelpTitle')} testid="curve-why">
      <p>{t('curveHint')}</p>
      <p>{t('curveHelpEnvelope')}</p>
      <p>{t('curveHelpDots')}</p>
    </Why>
  </div>

  <figure bind:clientWidth={measured} data-help="settings/curve.chart">
    <svg
      bind:this={svg}
      viewBox="0 0 {width} {HEIGHT}"
      {width}
      height={HEIGHT}
      role="group"
      aria-label={t('curveChartLabel')}
      aria-describedby="curve-summary-{uid}"
      data-testid="curve-svg"
    >
      <defs>
        <clipPath id={clipId}><rect x="0" y="0" width={innerW} height={innerH} /></clipPath>
      </defs>
      <g transform="translate({pad.left},{pad.top})">
        {#each yTicks as tick (tick)}
          <line x1="0" x2={innerW} y1={sy(tick)} y2={sy(tick)} class="grid" />
          <text x="-6" y={sy(tick)} dy="0.32em" text-anchor="end" class="tick">{tick}</text>
        {/each}
        {#each xTicks as tick (tick)}
          <line x1={sx(tick)} x2={sx(tick)} y1={innerH} y2={innerH + 4} class="grid" />
          <text x={sx(tick)} y={innerH + 17} text-anchor="middle" class="tick"
            >{String(tick).replace('-', '−')}</text
          >
        {/each}
        <text x={innerW} y={innerH - 5} text-anchor="end" class="axis-label">{t('curveAxisX')}</text
        >
        <text x="2" y="-4" class="axis-label">{t('curveAxisY')}</text>

        <path d={bandPath} class="band" clip-path="url(#{clipId})" data-testid="curve-envelope" />
        <line x1="0" x2={innerW} y1={sy(limits.max)} y2={sy(limits.max)} class="limit" />
        <line x1="0" x2={innerW} y1={sy(limits.min)} y2={sy(limits.min)} class="limit" />
        <text x={innerW - 2} y={sy(limits.max) - 4} text-anchor="end" class="limit-label"
          >{t('curveMaxSupply', { value: fmt(limits.max) })}</text
        >
        <text x="4" y={sy(limits.min) + 12} class="limit-label"
          >{t('curveMinSetpoint', { value: fmt(limits.min) })}</text
        >

        <g class="density" data-testid="curve-dots">
          {#each bins as bin (bin.outside)}
            <rect
              x={sx(bin.outside) - binW / 2}
              y={sy(bin.high + 0.25)}
              width={binW}
              height={Math.max(sy(bin.low - 0.25) - sy(bin.high + 0.25), 3)}
              rx={Math.min(binW / 2, 4)}
              style:opacity={0.06 + 0.22 * (bin.count / maxCount)}
            />
          {/each}
        </g>

        {#if preset && !sameCurve(preset, active)}
          <path d={path(preset)} class="preset-line" />
        {/if}
        {#if diffPath}
          <path d={diffPath} class="diff" clip-path="url(#{clipId})" data-testid="curve-diff" />
        {/if}
        <path d={path(active)} class="active-line" data-testid="curve-active" />
        {#if changed}
          <path d={path(points)} class="draft-line" data-testid="curve-draft" />
        {/if}

        {#if forecastRange}
          <rect
            x={sx(forecastRange[0])}
            y={innerH - 6}
            width={Math.max(sx(forecastRange[1]) - sx(forecastRange[0]), 3)}
            height="5"
            rx="2.5"
            class="forecast"
            data-testid="curve-forecast"
          />
        {/if}

        {#if operating}
          <g data-testid="curve-operating" class="operating-group">
            <line
              x1={sx(operating.outside)}
              x2={sx(operating.outside)}
              y1={innerH}
              y2={sy(operating.curve)}
              class="now-rule"
            />
            {#if operating.issued !== null && Math.abs(operating.issued - operating.curve) > 0.05}
              <line
                x1={sx(operating.outside)}
                x2={sx(operating.outside)}
                y1={sy(operating.curve)}
                y2={sy(operating.issued)}
                class="arrow"
              />
              <circle cx={sx(operating.outside)} cy={sy(operating.issued)} r="4" class="issued" />
            {/if}
            {#if draftNow !== null}
              <path
                d="M{sx(operating.outside)},{sy(draftNow) - 7}l7,7l-7,7l-7,-7z"
                class="operating draft"
              />
            {/if}
            <path
              d="M{sx(operating.outside)},{sy(operating.curve) - 8}l8,8l-8,8l-8,-8z"
              class="operating"
            />
          </g>
        {/if}

        {#each points as [x, y], i (i)}
          <g
            class="handle"
            class:drag={dragging === i}
            role="slider"
            tabindex={disabled ? -1 : 0}
            aria-label={t('curvePointLabel', { n: i + 1, outside: fmt(x), water: fmt(y) })}
            aria-orientation="vertical"
            aria-valuemin={waterRange(i).min}
            aria-valuemax={waterRange(i).max}
            aria-valuenow={y}
            aria-valuetext={t('curvePointValue', { outside: fmt(x), water: fmt(y) })}
            aria-disabled={disabled}
            onkeydown={(e) => onKey(i, e)}
            onfocus={() => (focused = i)}
            onblur={() => (focused = null)}
            onpointerdown={(e) => {
              if (disabled) return;
              (e.currentTarget as Element).setPointerCapture(e.pointerId);
              dragging = i;
            }}
            onpointermove={(e) => dragging === i && dragTo(i, e)}
            onpointerup={() => (dragging = null)}
            onpointercancel={() => (dragging = null)}
            data-testid="curve-handle-{i}"
          >
            <circle cx={sx(x)} cy={sy(y)} r="24" class="hit" />
            <circle cx={sx(x)} cy={sy(y)} r={narrow ? 11 : 9} class="knob" />
            {#if pointer === i}
              <text x={sx(x)} y={sy(y) - 16} text-anchor="middle" class="knob-value"
                >{fmt(y)}&#8239;°C</text
              >
            {:else}
              <text x={sx(x)} y={sy(y) + 3.5} text-anchor="middle" class="knob-label">{i + 1}</text>
            {/if}
          </g>
        {/each}
      </g>
    </svg>
    <p id="curve-summary-{uid}" class="visually-hidden">{summary}</p>
    <figcaption>
      <ul class="legend">
        <li><span class="key active"></span>{t('curveLegendActive')}</li>
        {#if changed}<li><span class="key draft"></span>{t('curveLegendDraft')}</li>{/if}
        <li><span class="key band"></span>{t('curveLegendEnvelope')}</li>
        {#if operating}<li><span class="key diamond"></span>{t('curveLegendNow')}</li>{/if}
        {#if bins.length > 0}<li><span class="key dots"></span>{t('curveLegendDots')}</li>{/if}
        {#if forecastRange}<li>
            <span class="key forecast"></span>{t('curveLegendForecast')}
          </li>{/if}
      </ul>
    </figcaption>
  </figure>

  <div data-help="settings/curve.points">
    <Details
      summary={t('curveTableLabel')}
      meta={t('curveCount', { n: points.length, max: MAX_POINTS })}
      open={!narrow}
      icon="edit"
      testid="curve-table"
    >
      <div class="table" role="group" aria-label={t('curveTableLabel')}>
        {#each points as [x, y], i (i)}
          <div class="row" data-testid="curve-row-{i}">
            <span class="num" aria-hidden="true">{i + 1}</span>
            <div class="pair out">
              <span class="cap">{t('curveOutside')}</span>
              <Stepper
                value={x}
                step={1}
                min={outsideRange(i).min}
                max={outsideRange(i).max}
                label={t('curveOutsideOf', { n: i + 1 })}
                unit="°C"
                {disabled}
                onchange={(v) => emit(setOutside(points, i, v))}
                testid="point-outside-{i}"
              />
            </div>
            <div class="pair water">
              <span class="cap">{t('curveWater')}</span>
              <Stepper
                value={y}
                step={WATER_STEP}
                fineStep={WATER_FINE_STEP}
                min={waterRange(i).min}
                max={waterRange(i).max}
                label={t('curveWaterOf', { n: i + 1 })}
                unit="°C"
                {disabled}
                onchange={(v) =>
                  emit(
                    setWater(
                      points,
                      i,
                      v,
                      waterLimits,
                      Number.isInteger(v) ? WATER_STEP : WATER_FINE_STEP,
                    ),
                  )}
                testid="point-water-{i}"
              />
            </div>
            <Button
              class="curve-remove"
              disabled={disabled || points.length <= MIN_POINTS}
              onclick={() => emit(removePoint(points, i))}
              aria-label={t('curveRemove', { n: i + 1 })}
              title={t('curveRemove', { n: i + 1 })}
              data-testid="remove-point-{i}"><Icon name="close" size={18} /></Button
            >
          </div>
        {/each}
        <Button
          class="curve-add"
          onclick={() => emit(addPoint(points))}
          disabled={disabled || points.length >= MAX_POINTS}
          data-testid="add-point"
        >
          <Icon name="plus" size={18} />{t('curveAdd')}
        </Button>
      </div>
    </Details>
  </div>
</div>

<style>
  .editor {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  .readout {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    min-height: 2.25rem;
    padding: var(--space-1) var(--space-1) var(--space-1) 0.6rem;
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    font-size: var(--fs-body);
  }
  .read-now,
  .read-point {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem;
    min-width: 0;
  }
  .read-point {
    color: var(--accent);
    font-weight: var(--fw-semibold);
  }
  .read-now :global(.icon) {
    color: var(--muted);
  }
  .diamond {
    width: 9px;
    height: 9px;
    background: var(--series-outlet);
    transform: rotate(45deg);
    flex: none;
  }
  .draft-value {
    color: var(--accent);
  }
  .delta {
    padding: 0 0.4rem;
    border-radius: var(--radius-pill);
    background: var(--status-manual-bg);
    color: var(--status-manual);
    font-size: var(--fs-caption);
    font-weight: var(--fw-bold);
  }
  .issued-note {
    color: var(--muted);
  }
  figure {
    margin: 0;
    min-width: 0;
  }
  svg {
    display: block;
    max-width: 100%;
    touch-action: pan-y;
    user-select: none;
  }
  .grid {
    stroke: var(--chart-grid);
  }
  .tick,
  .axis-label,
  .limit-label {
    fill: var(--chart-axis);
    font-size: var(--fs-micro);
  }
  .band {
    fill: var(--band-safety);
    fill-opacity: calc(var(--chart-band-opacity) * 0.8);
  }
  .limit {
    stroke: var(--status-stopped);
    stroke-dasharray: 5 4;
    opacity: 0.55;
  }
  .limit-label {
    fill: var(--status-stopped);
  }
  .density rect {
    fill: var(--muted);
  }
  .active-line {
    fill: none;
    stroke: var(--muted);
    stroke-width: 2.5;
  }
  .preset-line {
    fill: none;
    stroke: var(--muted);
    stroke-dasharray: 3 4;
    stroke-width: 1.5;
    opacity: 0.7;
  }
  .draft-line {
    fill: none;
    stroke: var(--accent);
    stroke-width: 3;
  }
  .diff {
    fill: var(--accent);
    fill-opacity: 0.18;
  }
  .now-rule {
    stroke: var(--series-outlet);
    stroke-dasharray: 2 3;
    opacity: 0.7;
  }
  .operating {
    fill: var(--series-outlet);
    stroke: var(--surface);
    stroke-width: 2;
  }
  .operating.draft {
    fill: var(--surface);
    stroke: var(--accent);
    stroke-width: 2;
  }
  .arrow {
    stroke: var(--series-issued);
    stroke-width: 1.5;
    stroke-dasharray: 3 2;
  }
  .issued {
    fill: var(--series-issued);
    stroke: var(--surface);
    stroke-width: 1.5;
  }
  .forecast {
    fill: var(--series-outside);
    opacity: 0.6;
  }
  .handle {
    cursor: grab;
    touch-action: none;
    outline: none;
  }
  .handle.drag {
    cursor: grabbing;
  }
  .hit {
    fill: transparent;
  }
  .knob {
    fill: var(--surface);
    stroke: var(--accent);
    stroke-width: 3;
  }
  .handle:focus-visible .knob,
  .handle.drag .knob {
    stroke-width: 4;
    fill: var(--accent);
  }
  .knob-label {
    fill: var(--accent);
    font-size: var(--fs-chart-tick);
    font-weight: var(--fw-bold);
    pointer-events: none;
  }
  .knob-value {
    fill: var(--text);
    font-size: var(--fs-chart-axis);
    font-weight: var(--fw-bold);
    paint-order: stroke;
    stroke: var(--surface);
    stroke-width: 4px;
    pointer-events: none;
  }
  .legend {
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: 0.15rem 0.9rem;
    margin: var(--space-1) 0 0;
    padding: 0;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .legend li {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .key {
    display: inline-block;
    width: 18px;
    height: 3px;
    border-radius: var(--radius-2xs);
  }
  .key.active {
    background: var(--muted);
  }
  .key.draft {
    background: var(--accent);
  }
  .key.band {
    height: 10px;
    background: color-mix(in srgb, var(--band-safety) 28%, transparent);
  }
  .key.diamond {
    width: 9px;
    height: 9px;
    background: var(--series-outlet);
    transform: rotate(45deg);
  }
  .key.dots {
    width: 6px;
    height: 12px;
    border-radius: var(--radius-xs);
    background: var(--series-issued);
    opacity: 0.35;
  }
  .key.forecast {
    height: 5px;
    background: var(--series-outside);
    opacity: 0.6;
  }
  .table {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(22rem, 1fr));
    gap: var(--space-2) var(--space-4);
    align-items: end;
  }
  .row {
    display: grid;
    grid-template-columns: 1.5rem minmax(0, 1fr) minmax(0, 1fr) var(--tap);
    gap: var(--space-2);
    align-items: end;
  }
  .num {
    align-self: center;
    margin-top: var(--space-4);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 50%;
    border: 2px solid var(--accent);
    color: var(--accent);
    font-size: var(--fs-caption);
    font-weight: var(--fw-bold);
  }
  .pair {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
  }
  .cap {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  :global(.curve-remove) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: var(--tap);
    min-height: var(--tap);
    padding: 0;
    color: var(--muted);
  }
  :global(.curve-add) {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    justify-self: start;
    min-height: var(--tap);
  }
  .editor :global(.details .body) {
    padding-left: 0;
  }
  @media (--narrow) {
    .table {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-3);
    }
    .row {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      grid-template-areas:
        'num remove'
        'out water';
      gap: var(--space-1) var(--space-2);
      padding-bottom: var(--space-3);
      border-bottom: 1px solid var(--border);
    }
    .num {
      grid-area: num;
      margin-top: 0;
    }
    .out {
      grid-area: out;
    }
    .water {
      grid-area: water;
    }
    :global(.curve-remove) {
      grid-area: remove;
      justify-self: end;
      min-height: var(--tap);
    }
  }
</style>
