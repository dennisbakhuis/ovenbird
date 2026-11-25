<!--
  Heating-curve section: weather-dependent control on or off, the curve editor (or the fixed water
  temperature), the outside sensor the curve uses (the pump's own unless another thermometer is
  chosen; a chip says when the latest decision fell back to the pump's sensor) and the advanced
  outside filter.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import { decisionSends } from '$lib/setpoint/waterfall';
  import CurveEditor from '$components/settings/CurveEditor.svelte';
  import Field from '$components/settings/Field.svelte';
  import FieldGroup from '$components/settings/FieldGroup.svelte';
  import { fetchHistory, fetchSeries, fetchWeather } from '$lib/core/api';
  import { clockNow } from '$lib/core/format';
  import { nearestIndex } from '$lib/core/chart';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { asCurve, curveWater, type Curve } from '$lib/core/curve';
  import { draft } from '$lib/core/draft.svelte';
  import { forecastOf, forecastRange } from '$lib/weather/weather';
  import { t, tOpt } from '$lib/core/settings.svelte';
  import { signalName } from '$lib/core/signalView';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import { curveOutside } from '$lib/setpoint/explain';

  interface Props {
    live?: LiveStore;
    ctl: ControlStore;
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { live, ctl, schema, config }: Props = $props();

  const ready = $derived(live?.snapshot !== null);
  const war = $derived(draft.value('control_weather_compensation', config) !== false);

  const points = $derived(asCurve(draft.value('control_curve', config)) ?? []);
  const active = $derived(asCurve(config.fields['control_curve']?.value) ?? []);
  const emitter = $derived(String(draft.value('control_emitter', config) ?? 'mixed'));
  const preset = $derived(asCurve(schema.presets[emitter]?.['control_curve']));
  const limits = $derived({
    min: Number(draft.value('control_min_setpoint_c', config) ?? 20),
    max: Number(draft.value('control_max_supply_c', config) ?? 40),
  });
  const operating = $derived.by(() => {
    const record = ctl.decision?.record;
    const outside = record?.controller_state['outside_filtered_c'];
    if (typeof outside !== 'number' || active.length === 0) return null;
    return {
      outside,
      curve: curveWater(active as Curve, outside),
      issued: ctl.decision?.setpoint ?? null,
      sent: ctl.decision ? decisionSends(ctl.decision) : true,
    };
  });

  const OUTSIDE_FIELDS = [
    'control_outside_signal',
    'control_outside_max_age_s',
    'control_outside_plausible_min_c',
    'control_outside_plausible_max_c',
    'control_outside_max_deviation_k',
  ];
  const outsideSignal = $derived.by(() => {
    const value = draft.value('control_outside_signal', config);
    return typeof value === 'string' && value ? value : null;
  });
  const lastOutside = $derived(ctl.decision?.record ? curveOutside(ctl.decision.record) : null);
  const outsideName = $derived.by(() => {
    if (!lastOutside) return '';
    const listed = cfg.signals?.room.find((c) => c.signal === lastOutside.signal)?.name;
    return signalName(lastOutside.signal, listed, tOpt);
  });

  $effect(() => {
    void cfg.loadSignals();
  });

  let dots = $state<[number, number][]>([]);
  let range = $state<[number, number] | null>(null);

  $effect(() => {
    void ready;
    const controller = new AbortController();
    const to = new Date(clockNow());
    const from = new Date(to.getTime() - 7 * 86_400_000);
    void (async () => {
      try {
        const [history, series] = await Promise.all([
          fetchHistory(['main/Outside_Temp'], controller.signal, { from, to, step: 3600 }),
          fetchSeries({ from, to, step: 3600 }, controller.signal),
        ]);
        const outside = (history.series['main/Outside_Temp']?.points ?? []).flatMap(
          ([at, v]): [number, number][] => (typeof v === 'number' ? [[Date.parse(at), v]] : []),
        );
        const times = outside.map(([ms]) => ms);
        dots = series.at.flatMap((at, i): [number, number][] => {
          const setpoint = series.setpoint[i];
          const k = nearestIndex(times, Date.parse(at));
          const match = outside[k];
          if (
            typeof setpoint !== 'number' ||
            !match ||
            Math.abs(match[0] - Date.parse(at)) > 1_800_000
          )
            return [];
          return [[match[1], setpoint]];
        });
      } catch {
        dots = [];
      }
      try {
        range = forecastRange(forecastOf(await fetchWeather(1, 48, controller.signal)));
      } catch {
        range = null;
      }
    })();
    return () => controller.abort();
  });
</script>

<Card
  bare
  as="div"
  class="curve-section-curve"
  data-testid="curve-card"
  data-war={war ? 'on' : 'off'}
>
  <FieldGroup
    {schema}
    {config}
    groups={['curve']}
    only={['control_weather_compensation']}
    headings={false}
    testid="curve-war"
  />
  {#if !war}
    <FieldGroup
      {schema}
      {config}
      groups={['curve']}
      only={['control_fixed_water_c']}
      headings={false}
      testid="curve-fixed"
    />
    <p class="fixed-note" data-testid="curve-fixed-note">{t('curveFixedNote')}</p>
  {/if}
  {#if war}
    <Field
      id="control_curve"
      {schema}
      {config}
      {draft}
      wide
      hideLabel
      hideHelp
      errors={cfg.validation?.errors.filter((e) => e.field === 'control_curve') ?? []}
      warnings={cfg.validation?.warnings.filter((e) => e.field === 'control_curve') ?? []}
    >
      {#snippet editor(api)}
        <CurveEditor
          {points}
          {active}
          {preset}
          envelope={schema.envelope}
          {limits}
          {operating}
          {dots}
          forecastRange={range}
          disabled={api.disabled}
          onchange={(next) => api.set(next)}
        />
      {/snippet}
    </Field>
  {/if}
  {#if war && schema.fields['control_outside_signal']}
    <section class="outside" data-testid="curve-outside" data-help="settings/curve.outside">
      <h2 class="outside-title">{t('curveOutsideTitle')}</h2>
      {#each OUTSIDE_FIELDS.filter((id) => schema.fields[id]) as id (id)}
        <Field
          {id}
          {schema}
          {config}
          {draft}
          signals={cfg.signals}
          signalsState={cfg.signalsState}
          errors={cfg.validation?.errors.filter((e) => e.field === id) ?? []}
          warnings={cfg.validation?.warnings.filter((e) => e.field === id) ?? []}
        />
      {/each}
      <p class="outside-note" data-testid="curve-outside-note">
        {outsideSignal ? t('curveOutsideOnly') : t('curveOutsidePump')}
      </p>
      {#if lastOutside?.fallback}
        <p class="outside-fallback" role="status" data-testid="curve-outside-fallback">
          <Icon name="warning" size={16} />{t('curveOutsideFallback')}
        </p>
      {:else if lastOutside}
        <p class="outside-note" data-testid="curve-outside-using">
          {t('curveOutsideUsing', { name: outsideName })}
        </p>
      {/if}
    </section>
  {/if}
  <FieldGroup
    {schema}
    {config}
    groups={['curve']}
    exclude={[
      'control_curve',
      'control_weather_compensation',
      'control_fixed_water_c',
      ...OUTSIDE_FIELDS,
    ]}
    collapsed
    title={t('curveAdvanced')}
    icon="settings"
    testid="curve-advanced"
    helpTarget="settings/curve.filter"
  />
</Card>

<style>
  :global(.curve-section-curve) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .outside {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding-top: var(--space-3);
    border-top: 1px solid var(--border);
  }
  .outside-title {
    margin: 0;
    font-size: var(--fs-body);
    font-weight: var(--fw-semibold);
  }
  .outside-note {
    margin: 0;
    color: var(--muted);
    font-size: var(--fs-sm);
  }
  .outside-fallback {
    margin: var(--space-1) 0 0;
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--status-limited-bg);
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
    font-size: var(--fs-sm);
  }
  .outside-fallback :global(.icon) {
    flex: none;
  }
  .fixed-note {
    margin: 0;
    color: var(--muted);
    font-size: var(--fs-sm);
  }
</style>
