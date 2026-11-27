<!--
  WhatIfCard: ask the house model what other weather would take. Four inputs (outside
  temperature, comfort temperature, sunshine, wood stove) go to `insight/house/whatif` 300 ms
  after the last change; the last answer stays visible while the next one loads. The inputs live
  in the URL query of the page (`outside`, `comfort`, `sun`, `stove`), so a view can be shared or
  reloaded, and nowhere in the settings: nothing here changes any setting.

  Props: comfortC (the comfort target of the installation: the default of the comfort input),
  onoverview (opens the Overview tab, where the house facts are entered).
  Honesty: a pill says whether the answer comes from the measured model or from the owner's
  facts, and a line says when the model is still learning.
  A11y: the drift chart is role="img" with a generated sentence.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import { formatNum, formatValue } from '$lib/core/chartSummary';
  import { linearScale, niceTicks } from '$lib/core/chart';
  import { buildHash } from '$lib/core/router.svelte';
  import { router } from '$lib/core/router.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import { formatPower } from '$lib/house/balance';
  import type { WhatIfInputs } from '$lib/house/shapes';
  import {
    DEBOUNCE_MS,
    STOVE_PRESETS,
    SUN_PRESETS,
    WHATIF_DEFAULTS,
    WHATIF_RANGES,
    driftSummary,
    fetchWhatIf,
    isLimitedBy,
    parseWhatIfQuery,
    whatIfQuery,
    type WhatIfResult,
  } from '$lib/house/whatif';
  import { minus } from '$lib/core/minus';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import FormRow from '$ui/FormRow.svelte';
  import Pill from '$ui/Pill.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import Stepper from '$ui/Stepper.svelte';

  interface Props {
    comfortC?: number;
    onoverview?: () => void;
  }

  let { comfortC = WHATIF_DEFAULTS.comfort_c, onoverview }: Props = $props();

  const lang = $derived(settings.language);
  const defaults = $derived<WhatIfInputs>({ ...WHATIF_DEFAULTS, comfort_c: comfortC });

  let inputs = $state<WhatIfInputs>(
    untrack(() =>
      parseWhatIfQuery(router.location.query, { ...WHATIF_DEFAULTS, comfort_c: comfortC }),
    ),
  );
  let result = $state<WhatIfResult | null>(null);
  let busy = $state(false);
  let failed = $state(false);
  let started = false;

  function change(patch: Partial<WhatIfInputs>): void {
    inputs = { ...inputs, ...patch };
    history.replaceState(null, '', buildHash('house', ['what-if'], whatIfQuery(inputs, defaults)));
  }

  $effect(() => {
    const fromUrl = parseWhatIfQuery(router.location.query, defaults);
    untrack(() => {
      if (JSON.stringify(fromUrl) !== JSON.stringify(inputs)) inputs = fromUrl;
    });
  });

  $effect(() => {
    const snapshot = inputs;
    const controller = new AbortController();
    busy = true;
    const timer = window.setTimeout(
      async () => {
        try {
          result = await fetchWhatIf(snapshot, controller.signal);
          failed = false;
        } catch {
          if (controller.signal.aborted) return;
          failed = true;
        }
        busy = false;
      },
      started ? DEBOUNCE_MS : 0,
    );
    started = true;
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  });

  const data = $derived(result?.kind === 'ready' ? result.data : null);
  const num = (value: number, digits = 1) => formatNum(value, digits, lang);
  const temp = (value: number, digits = 1) => minus(formatValue(value, '°C', digits, lang));
  const noHeat = $derived(data !== null && isLimitedBy(data, 'no_heat_needed'));
  const capped = $derived(data !== null && isLimitedBy(data, 'max_supply'));
  const drift = $derived(data ? driftSummary(data) : null);

  const sunOptions = $derived(
    SUN_PRESETS.map((value) => ({
      value,
      label: t(`houseWiSun_${value}` as 'houseWiSun_0'),
      testid: `whatif-sun-${value}`,
    })),
  );
  const stoveOptions = $derived(
    STOVE_PRESETS.map((value) => ({
      value,
      label: t(`houseWiStove_${value}` as 'houseWiStove_0'),
      testid: `whatif-stove-${value}`,
    })),
  );

  const DRIFT_H = 150;
  const pad = { left: 38, right: 54, top: 12, bottom: 28 };
  let measured = $state(0);
  const chartW = $derived(measured > 0 ? measured : 320);
  const driftPoints = $derived.by(() => {
    if (!data) return [] as [number, number][];
    const step = data.drift.step_s / 3600;
    return data.drift.room_c.map((value, i): [number, number] => [i * step, value]);
  });
  const yDomain = $derived.by((): [number, number] => {
    const values = driftPoints.map((p) => p[1]);
    if (values.length === 0) return [0, 1];
    const lo = Math.floor(Math.min(...values) - 0.5);
    const hi = Math.ceil(Math.max(...values) + 0.5);
    return [lo, Math.max(hi, lo + 2)];
  });
  const sx = $derived(linearScale(0, data?.drift.hours ?? 8, pad.left, chartW - pad.right));
  const sy = $derived(linearScale(yDomain[0], yDomain[1], DRIFT_H - pad.bottom, pad.top));
  const yTicks = $derived(niceTicks(yDomain[0], yDomain[1], 3, 1));
  const xTicks = $derived(
    Array.from({ length: Math.floor((data?.drift.hours ?? 8) / 2) + 1 }, (_, i) => i * 2),
  );
  const path = $derived(
    driftPoints
      .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${sx(x).toFixed(1)} ${sy(y).toFixed(1)}`)
      .join(''),
  );
  const driftSentence = $derived(
    drift
      ? t(drift.endC < drift.startC - 0.1 ? 'houseWiDriftCools' : 'houseWiDriftHolds', {
          end: num(drift.endC, 1),
          hours: num(drift.hours, 0),
        })
      : '',
  );
  const driftAria = $derived(
    drift
      ? t('houseWiDriftAria', {
          hours: num(drift.hours, 0),
          start: num(drift.startC, 1),
          end: num(drift.endC, 1),
        })
      : '',
  );
</script>

<Card
  title={t('houseWiTitle')}
  subtitle={t('houseWiLead')}
  icon="target"
  testid="house-whatif"
  help="house.whatif"
  span={12}
>
  {#if result?.kind === 'absent'}
    <p class="muted" data-testid="whatif-absent">{t('houseWiAbsent')}</p>
  {:else if result?.kind === 'no_model'}
    <p data-testid="whatif-no-model">
      {t('houseWiNoModel')}
      {#if onoverview}
        <Button variant="link" onclick={onoverview} data-testid="whatif-facts"
          >{t('houseWiFactsLink')}</Button
        >
      {/if}
    </p>
  {:else}
    <div class="layout">
      <div class="inputs" data-testid="whatif-inputs">
        <h3>{t('houseWiInputs')}</h3>
        <FormRow label={t('houseWiOutside')}>
          {#snippet control({ id })}
            <div class="step">
              <Stepper
                {id}
                label={t('houseWiOutside')}
                value={inputs.outside_c}
                step={1}
                fineStep={0.5}
                min={WHATIF_RANGES.outside_c.min}
                max={WHATIF_RANGES.outside_c.max}
                unit="°C"
                onchange={(value) => change({ outside_c: value })}
                testid="whatif-outside"
              />
            </div>
          {/snippet}
        </FormRow>
        <FormRow label={t('houseWiComfort')}>
          {#snippet control({ id })}
            <div class="step">
              <Stepper
                {id}
                label={t('houseWiComfort')}
                value={inputs.comfort_c}
                step={0.5}
                min={WHATIF_RANGES.comfort_c.min}
                max={WHATIF_RANGES.comfort_c.max}
                unit="°C"
                onchange={(value) => change({ comfort_c: value })}
                testid="whatif-comfort"
              />
            </div>
          {/snippet}
        </FormRow>
        <FormRow label={t('houseWiSun')}>
          {#snippet control({ id })}
            <div class="stack">
              <Segmented
                options={sunOptions}
                value={inputs.sun_wm2}
                onchange={(value) => change({ sun_wm2: value })}
                label={t('houseWiSun')}
                appearance="joined"
                size="sm"
                testid="whatif-sun"
              />
              <div class="step">
                <Stepper
                  {id}
                  label={t('houseWiSunExact')}
                  value={inputs.sun_wm2}
                  step={50}
                  fineStep={10}
                  min={WHATIF_RANGES.sun_wm2.min}
                  max={WHATIF_RANGES.sun_wm2.max}
                  unit="W/m²"
                  onchange={(value) => change({ sun_wm2: value })}
                  testid="whatif-sun-exact"
                />
              </div>
            </div>
          {/snippet}
        </FormRow>
        <FormRow label={t('houseWiStove')}>
          {#snippet control()}
            <Segmented
              options={stoveOptions}
              value={inputs.stove_w}
              onchange={(value) => change({ stove_w: value })}
              label={t('houseWiStove')}
              appearance="joined"
              size="sm"
              testid="whatif-stove"
            />
          {/snippet}
        </FormRow>
      </div>

      <div class="results" aria-live="polite" data-testid="whatif-results" data-busy={busy}>
        <h3>
          {t('houseWiResults')}
          {#if busy}<span class="caption" data-testid="whatif-busy">{t('houseWiUpdating')}</span
            >{/if}
        </h3>
        {#if failed}
          <p class="warn" data-testid="whatif-failed">{t('houseWiFailed')}</p>
        {/if}
        {#if data}
          <p class="pills">
            <Pill tone={data.source === 'model' ? 'good' : 'warn'} testid="whatif-source">
              {data.source === 'model' ? t('houseWiSourceModel') : t('houseWiSourceEstimate')}
            </Pill>
            {#if data.source === 'model' && !data.credible}
              <Pill tone="warn" testid="whatif-learning">{t('houseWiNotCredible')}</Pill>
            {/if}
          </p>
          {#if noHeat}
            <p class="lead" data-testid="whatif-none">
              {t('houseWiLimitNone', { outside: num(data.inputs.outside_c, 1) })}
            </p>
          {:else}
            <p class="lead" data-testid="whatif-demand">
              {t('houseWiDemand', { value: formatPower(data.heat_demand_w, lang) })}
            </p>
            <p data-testid="whatif-free">
              {t('houseWiFree', {
                loss: formatPower(data.loss_w, lang),
                free: formatPower(data.free_heat_w, lang),
              })}
            </p>
            <p data-testid="whatif-water">
              {t('houseWiWater', {
                supply: num(data.supply_c, 1),
                mean: num(data.loop_mean_c, 1),
                curve: num(data.curve_c, 1),
              })}
            </p>
          {/if}
          {#if capped}
            <p class="warn" data-testid="whatif-capped">
              {t('houseWiLimitMax', {
                max: num(data.max_supply_c, 1),
                comfort: num(data.inputs.comfort_c, 1),
              })}
            </p>
          {/if}
          {#if data.balance_outside_c !== null}
            <p data-testid="whatif-balance">
              {t('houseWiBalance', { value: num(data.balance_outside_c, 1) })}
            </p>
          {/if}

          {#if drift}
            <h3 class="drift-title">{t('houseWiDriftTitle')}</h3>
            <div class="plot" bind:clientWidth={measured}>
              <svg
                width={chartW}
                height={DRIFT_H}
                viewBox="0 0 {chartW} {DRIFT_H}"
                role="img"
                aria-label={driftAria}
                data-testid="whatif-drift"
              >
                {#each yTicks as tick (tick)}
                  <line
                    class="grid"
                    x1={pad.left}
                    x2={chartW - pad.right}
                    y1={sy(tick)}
                    y2={sy(tick)}
                  />
                  <text class="tick" x={pad.left - 6} y={sy(tick) + 4} text-anchor="end"
                    >{num(tick, 0)}</text
                  >
                {/each}
                {#each xTicks as tick (tick)}
                  <text class="tick" x={sx(tick)} y={DRIFT_H - 10} text-anchor="middle"
                    >{tick}&#8239;{t('houseTrendUnitH')}</text
                  >
                {/each}
                <path class="line" d={path} />
                <circle class="dot" cx={sx(0)} cy={sy(drift.startC)} r="3.5" />
                <circle class="dot" cx={sx(drift.hours)} cy={sy(drift.endC)} r="3.5" />
                <text class="end" x={sx(drift.hours) + 8} y={sy(drift.endC) + 4}
                  >{temp(drift.endC)}</text
                >
              </svg>
            </div>
            <p data-testid="whatif-drift-text">{driftSentence}</p>
            {#if data.time_constant_h !== null}
              <p class="caption">{t('houseWiDriftTau', { tau: num(data.time_constant_h, 0) })}</p>
            {/if}
          {/if}
        {:else if result === null && !failed}
          <p class="muted">{t('loading')}</p>
        {/if}
      </div>
    </div>
  {/if}
</Card>

<style>
  .layout {
    display: grid;
    grid-template-columns: minmax(16rem, 22rem) minmax(0, 1fr);
    gap: var(--space-5);
    align-items: start;
  }
  @container main (max-width: 48rem) {
    .layout {
      grid-template-columns: minmax(0, 1fr);
      gap: var(--space-4);
    }
  }
  .inputs {
    display: grid;
    gap: var(--space-3);
  }
  .step {
    width: 12rem;
    max-width: 100%;
  }
  .inputs :global(.row) {
    align-items: flex-start;
  }
  .stack {
    display: grid;
    gap: var(--space-2);
    justify-items: start;
  }
  h3 {
    margin: 0;
    font-size: var(--fs-body);
  }
  .results p {
    margin: 0 0 var(--space-2);
  }
  .results .lead {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
  }
  .pills {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .warn {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-control);
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .results {
    min-width: 0;
  }
  .results[data-busy='true'] {
    opacity: 0.85;
  }
  .drift-title {
    margin-top: var(--space-4);
  }
  .plot {
    min-width: 0;
    margin-bottom: var(--space-2);
  }
  svg {
    display: block;
    max-width: 100%;
  }
  .grid {
    stroke: var(--chart-grid, var(--border));
  }
  .tick {
    fill: var(--chart-axis, var(--muted));
    font-size: var(--fs-caption);
    font-variant-numeric: tabular-nums;
  }
  .line {
    fill: none;
    stroke: var(--series-room);
    stroke-width: 2;
    stroke-linejoin: round;
  }
  .dot {
    fill: var(--surface);
    stroke: var(--series-room);
    stroke-width: 2;
  }
  .end {
    fill: var(--text);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
  }
</style>
