<!--
  LoopDiagram: the hydraulic loop as one schematic — outdoor unit, outlet pipe to the emitters,
  inlet pipe back — with the live values on it: outlet and inlet temperature, ΔT against its
  setting, flow, pump duty against its maximum, compressor Hz, electric and heat power, COP and
  the defrost / hot-water state (with hot water hidden a run reads "Busy elsewhere" under a gear). Drawn horizontally from 560 px of width, stacked below that;
  the SVG is sized in pixels from the measured width so text never scales down.

  Props: kind (PumpStateKind), outletC, inletC, flowLpm, duty, maxDuty, hz, electricW, heatW,
  setDeltaK (all number | null), deice (the defrost's deice mode, null when unknown).
  A defrost of a known model reads "Defrosting · mode 2" in the narrow layout (the wide unit box
  has no room: it keeps "Defrosting") and the long form in a line under the diagram.
  Honesty: while the pump defrosts it drives its own duty (often above the maximum setting);
  the duty is shown as "220 of 159" in the warning colour with a sentence saying why.
  A11y: role="img" with a generated sentence; the values are also in the text of the page cards.
-->
<script lang="ts">
  import { copOf, formatNum, formatValue } from '$lib/core/chartSummary';
  import { hotWater } from '$lib/core/hotWater.svelte';
  import { minus } from '$lib/core/minus';
  import type { DeiceMode, PumpStateKind } from '$lib/pump/pumpState';
  import { dutyReading } from '$lib/pump/pumpStats';
  import { settings, t } from '$lib/core/settings.svelte';
  import { GLYPHS } from '$components/charts/glyphs';
  import { SERIES } from '$components/charts/palette';

  interface Props {
    kind: PumpStateKind;
    outletC: number | null;
    inletC: number | null;
    flowLpm: number | null;
    duty: number | null;
    maxDuty: number | null;
    hz: number | null;
    electricW: number | null;
    heatW: number | null;
    setDeltaK: number | null;
    deice?: DeiceMode | null;
  }

  let {
    kind,
    outletC,
    inletC,
    flowLpm,
    duty,
    maxDuty,
    hz,
    electricW,
    heatW,
    setDeltaK,
    deice = null,
  }: Props = $props();

  const lang = $derived(settings.language);
  let width = $state(640);
  const wide = $derived(width >= 560);
  const height = $derived(wide ? 214 : 392);

  const deltaK = $derived(outletC !== null && inletC !== null ? outletC - inletC : null);
  const cop = $derived(copOf(electricW, heatW));
  const reading = $derived(dutyReading(duty, maxDuty));
  const own = $derived(reading.above && kind === 'defrost');
  const stateKey = $derived(`loopState_${kind}` as 'loopState_idle');
  const mode = $derived(kind === 'defrost' ? deice : null);
  const stateLong = $derived(mode === null ? t(stateKey) : t(`deiceMode_${mode}`));
  const stateShort = $derived(
    mode === null ? t(stateKey) : t('pumpStateDefrostMode', { mode: mode }),
  );
  const glyph = $derived(
    kind === 'defrost'
      ? GLYPHS.snowflake
      : kind === 'dhw'
        ? hotWater.shown
          ? GLYPHS.tap
          : GLYPHS.gear
        : GLYPHS.fan,
  );
  const accent = $derived(
    kind === 'defrost'
      ? SERIES.defrost
      : kind === 'dhw'
        ? SERIES.dhw
        : kind === 'running'
          ? SERIES.heat
          : 'var(--border)',
  );

  const temp = (value: number | null) => minus(formatValue(value, '°C', 1, lang));
  const kw = (watts: number | null) =>
    watts === null ? '–' : formatValue(watts / 1000, 'kW', 1, lang);
  const dutyText = $derived(
    duty === null
      ? '–'
      : maxDuty === null
        ? formatNum(duty, 0, lang)
        : t('loopDutyOf', { duty: formatNum(duty, 0, lang), max: formatNum(maxDuty, 0, lang) }),
  );
  const deltaText = $derived(minus(formatValue(deltaK, 'K', 1, lang)));
  const setText = $derived(
    setDeltaK === null ? '' : t('loopDeltaTSet', { value: formatValue(setDeltaK, 'K', 0, lang) }),
  );
  const summary = $derived(
    t('loopSummary', {
      state: stateLong,
      outlet: temp(outletC),
      inlet: temp(inletC),
      delta: deltaText,
      flow: formatValue(flowLpm, 'l/min', 1, lang),
      duty: dutyText,
      hz: formatValue(hz, 'Hz', 0, lang),
    }),
  );

  const UNIT_W = 176;
  const EMIT_W = 124;
  const pipeLeft = UNIT_W;
  const pipeRight = $derived(width - EMIT_W);
  const mid = $derived((pipeLeft + pipeRight) / 2);
  const col1 = $derived(width * 0.22);
  const col2 = $derived(width * 0.78);
</script>

<div class="loop" bind:clientWidth={width}>
  <svg
    {width}
    {height}
    viewBox="0 0 {width} {height}"
    role="img"
    aria-label={summary}
    data-testid="loop-diagram"
    data-layout={wide ? 'wide' : 'narrow'}
    data-state={kind}
  >
    <defs>
      <marker
        id="loop-arrow-out"
        viewBox="0 0 10 10"
        refX="7"
        refY="5"
        markerWidth="5"
        markerHeight="5"
        orient="auto-start-reverse"
      >
        <path d="M0 0 10 5 0 10z" fill={SERIES.outlet} />
      </marker>
      <marker
        id="loop-arrow-in"
        viewBox="0 0 10 10"
        refX="7"
        refY="5"
        markerWidth="5"
        markerHeight="5"
        orient="auto-start-reverse"
      >
        <path d="M0 0 10 5 0 10z" fill={SERIES.inlet} />
      </marker>
    </defs>

    {#if wide}
      <rect
        class="box"
        x="1"
        y="6"
        width={UNIT_W - 2}
        height="200"
        rx="10"
        style:stroke={accent}
        stroke-width={kind === 'idle' || kind === 'off' ? 1 : 2}
      />
      <g class="ink" transform="translate(14 16)">
        <g
          transform="scale(1.1)"
          style:color={accent === 'var(--border)' ? 'var(--muted)' : accent}
        >
          <path class="glyph" d={glyph} />
        </g>
      </g>
      <text class="strong" x="46" y="36" data-testid="loop-state">{t(stateKey)}</text>
      <text class="cap" x="14" y="62">{t('loopCompressor')}</text>
      <text class="big" x="14" y="88">{formatValue(hz, 'Hz', 0, lang)}</text>
      <text class="val" x="14" y="118">
        <tspan style:fill={SERIES.electric}>{kw(electricW)}</tspan>
        <tspan class="cap" dx="4">{t('loopElectric')}</tspan>
      </text>
      <text class="val" x="14" y="140">
        <tspan style:fill={SERIES.heat}>{kw(heatW)}</tspan>
        <tspan class="cap" dx="4">{t('loopHeat')}</tspan>
      </text>
      <text class="val" x="14" y="170">
        <tspan class="cap">{t('loopCop')}</tspan>
        <tspan class="strong" dx="6">{cop === null ? '–' : formatNum(cop, 1, lang)}</tspan>
      </text>
      <text class="cap" x="14" y="196">{t('loopOutdoor')}</text>

      <rect class="box" x={pipeRight + 8} y="6" width={EMIT_W - 9} height="200" rx="10" />
      {#each [0, 1, 2, 3, 4] as fin (fin)}
        <rect class="fin" x={pipeRight + 26 + fin * 18} y="28" width="9" height="128" rx="4.5" />
      {/each}
      <text class="cap" x={pipeRight + 8 + (EMIT_W - 9) / 2} y="186" text-anchor="middle"
        >{t('loopEmitters')}</text
      >

      <line
        class="pipe"
        x1={pipeLeft}
        y1="66"
        x2={pipeRight + 6}
        y2="66"
        style:stroke={SERIES.outlet}
        marker-end="url(#loop-arrow-out)"
      />
      <text class="cap" x={mid} y="34" text-anchor="middle">{t('loopOutlet')}</text>
      <text class="val temp" x={mid} y="56" text-anchor="middle">{temp(outletC)}</text>
      <text class="cap" x={mid} y="90" text-anchor="middle"
        >{t('loopFlow')} {formatValue(flowLpm, 'l/min', 1, lang)}</text
      >

      <text class="cap" x={mid} y="112" text-anchor="middle">{t('loopDeltaT')}</text>
      <text class="val" x={mid} y="132" text-anchor="middle">
        <tspan class="strong">{deltaText}</tspan>
        {#if setText}<tspan class="cap" dx="6">{setText}</tspan>{/if}
      </text>
      <text class="cap" class:warn={reading.above} x={mid} y="154" text-anchor="middle"
        >{t('loopDuty')} {dutyText}</text
      >

      <line
        class="pipe"
        x1={pipeRight}
        y1="170"
        x2={pipeLeft - 6}
        y2="170"
        style:stroke={SERIES.inlet}
        marker-end="url(#loop-arrow-in)"
      />
      <text class="val temp" x={mid} y="194" text-anchor="middle">{temp(inletC)}</text>
      <text class="cap" x={mid} y="208" text-anchor="middle">{t('loopInlet')}</text>
    {:else}
      <rect
        class="box"
        x="1"
        y="1"
        width={width - 2}
        height="138"
        rx="10"
        style:stroke={accent}
        stroke-width={kind === 'idle' || kind === 'off' ? 1 : 2}
      />
      <g class="ink" transform="translate(14 12)">
        <g
          transform="scale(1.1)"
          style:color={accent === 'var(--border)' ? 'var(--muted)' : accent}
        >
          <path class="glyph" d={glyph} />
        </g>
      </g>
      <text class="strong" x="46" y="32" data-testid="loop-state">{stateShort}</text>
      <text class="cap" x="14" y="62">{t('loopCompressor')}</text>
      <text class="big" x="14" y="88">{formatValue(hz, 'Hz', 0, lang)}</text>
      <text class="cap" x="14" y="126">{t('loopOutdoor')}</text>
      <text class="val" x={width / 2 + 8} y="62">
        <tspan style:fill={SERIES.electric}>{kw(electricW)}</tspan>
        <tspan class="cap" dx="4">{t('loopElectric')}</tspan>
      </text>
      <text class="val" x={width / 2 + 8} y="86">
        <tspan style:fill={SERIES.heat}>{kw(heatW)}</tspan>
        <tspan class="cap" dx="4">{t('loopHeat')}</tspan>
      </text>
      <text class="val" x={width / 2 + 8} y="112">
        <tspan class="cap">{t('loopCop')}</tspan>
        <tspan class="strong" dx="6">{cop === null ? '–' : formatNum(cop, 1, lang)}</tspan>
      </text>

      <line
        class="pipe"
        x1={col1}
        y1="139"
        x2={col1}
        y2="262"
        style:stroke={SERIES.outlet}
        marker-end="url(#loop-arrow-out)"
      />
      <text class="cap" x={col1 + 16} y="176">{t('loopOutlet')}</text>
      <text class="val temp" x={col1 + 16} y="198">{temp(outletC)}</text>
      <text class="cap" x={col1 + 16} y="220">{t('loopFlow')}</text>
      <text class="cap" x={col1 + 16} y="236">{formatValue(flowLpm, 'l/min', 1, lang)}</text>

      <line
        class="pipe"
        x1={col2}
        y1="266"
        x2={col2}
        y2="145"
        style:stroke={SERIES.inlet}
        marker-end="url(#loop-arrow-in)"
      />
      <text class="cap" x={col2 - 16} y="176" text-anchor="end">{t('loopInlet')}</text>
      <text class="val temp" x={col2 - 16} y="198" text-anchor="end">{temp(inletC)}</text>

      <rect class="box" x="1" y="268" width={width - 2} height="122" rx="10" />
      {#each [0, 1, 2, 3, 4, 5, 6] as fin (fin)}
        <rect class="fin" x={20 + fin * 16} y="282" width="8" height="52" rx="4" />
      {/each}
      <text class="cap" x="14" y="376">{t('loopEmitters')}</text>
      <text class="val" x={width - 14} y="296" text-anchor="end">
        <tspan class="cap">{t('loopDeltaT')}</tspan>
        <tspan class="strong" dx="6">{deltaText}</tspan>
      </text>
      <text class="cap" x={width - 14} y="316" text-anchor="end">{setText}</text>
      <text class="cap" class:warn={reading.above} x={width - 14} y="342" text-anchor="end"
        >{t('loopDuty')}</text
      >
      <text class="val" class:warn={reading.above} x={width - 14} y="364" text-anchor="end"
        >{dutyText}</text
      >
    {/if}
  </svg>
  {#if mode !== null}
    <p class="deice" data-testid="loop-deice" data-deice={mode}>{stateLong}</p>
  {/if}
  {#if reading.above && maxDuty !== null}
    <p class="honest" data-testid="loop-duty-note">
      {own
        ? t('loopDutyOwn', { max: formatNum(maxDuty, 0, lang) })
        : t('loopDutyAbove', { max: formatNum(maxDuty, 0, lang) })}
    </p>
  {/if}
</div>

<style>
  .loop {
    width: 100%;
    min-width: 0;
  }
  svg {
    display: block;
    max-width: 100%;
    font-family: inherit;
    overflow: visible;
  }
  .box {
    fill: var(--surface);
    stroke: var(--border);
  }
  .fin {
    fill: color-mix(in srgb, var(--series-outlet) 24%, var(--surface));
    stroke: var(--border);
  }
  .pipe {
    stroke-width: 6;
    stroke-linecap: butt;
  }
  .glyph {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  text {
    fill: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .cap {
    fill: var(--muted);
    font-size: var(--fs-caption);
  }
  .val {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
  }
  .temp {
    font-size: var(--fs-value);
  }
  .strong {
    font-size: var(--fs-emph);
    font-weight: var(--fw-strong);
  }
  .big {
    font-size: var(--fs-display-3);
    font-weight: var(--fw-strong);
  }
  .warn {
    fill: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .deice {
    margin: var(--space-2) 0 0;
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .honest {
    margin: var(--space-2) 0 0;
    padding: 0.4rem 0.6rem;
    border-radius: var(--radius-sm);
    background: var(--status-frozen-bg);
    color: var(--text);
    font-size: var(--fs-body);
  }
</style>
