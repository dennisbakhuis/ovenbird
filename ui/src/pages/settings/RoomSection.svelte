<!--
  Room section, ordered by use: the comfort target first (large stepper with the room now on a
  comfort-band meter), then the room sensor with its live status, with sensor behaviour,
  correction strength and the too-cold monitor collapsed by topic.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import BandMeter from '$components/charts/BandMeter.svelte';
  import Field from '$components/settings/Field.svelte';
  import FieldGroup from '$components/settings/FieldGroup.svelte';
  import RoomStatusCard from '$components/settings/RoomStatusCard.svelte';
  import Stepper from '$ui/Stepper.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { draft } from '$lib/core/draft.svelte';
  import { formatDelta } from '$lib/core/fieldFormat';
  import { formatNumber } from '$lib/core/format';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import { signalName } from '$lib/core/signalView';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  interface Props {
    ctl: ControlStore;
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { ctl, schema, config }: Props = $props();

  const HALF_BAND_K = 0.5;

  $effect(() => {
    void cfg.loadSignals();
  });

  const locale = $derived(settings.language);
  const profile = $derived(String(draft.value('control_room_profile', config) ?? 'periodic'));
  const sensorFields = $derived(
    profile === 'on_change'
      ? [
          'control_room_profile',
          'control_room_step_k',
          'control_room_silence_limit_s',
          'control_room_liveness_signals',
          'control_room_crosscheck_signal',
        ]
      : [
          'control_room_profile',
          'control_room_report_interval_s',
          'control_room_crosscheck_signal',
        ],
  );
  const room = $derived(ctl.control?.room ?? null);
  const nameOf = (signal: string) => {
    const lists = cfg.signals
      ? [cfg.signals.room, cfg.signals.liveness, cfg.signals.crosscheck]
      : [];
    const name = lists.flat().find((c) => c.signal === signal)?.name;
    return signalName(signal, name, tOpt);
  };
  const comfortDef = $derived(schema.fields['control_comfort_c']);
  const issues = (id: string) => ({
    errors: cfg.validation?.errors.filter((e) => e.field === id) ?? [],
    warnings: cfg.validation?.warnings.filter((e) => e.field === id) ?? [],
  });
</script>

<Card
  bare
  class="room-section-card room-section-comfort"
  data-testid="comfort-card"
  data-help="settings/room.comfort"
>
  <Field id="control_comfort_c" {schema} {config} {draft} wide {...issues('control_comfort_c')}>
    {#snippet editor(api)}
      {@const target = typeof api.value === 'number' ? api.value : null}
      <div class="comfort-row">
        <div class="stepper">
          <Stepper
            id="field-control_comfort_c"
            value={target ?? 21}
            step={comfortDef?.step ?? 0.1}
            min={comfortDef?.min ?? undefined}
            max={comfortDef?.max ?? undefined}
            label={t('cfg.control_comfort_c.label')}
            unit="°C"
            size="lg"
            disabled={api.disabled}
            invalid={api.invalid}
            onchange={(v) => api.set(v)}
            testid="comfort-stepper"
          />
        </div>
        <div class="meter">
          {#if target !== null && room?.value !== null && room?.value !== undefined}
            <p class="now">
              {t('roomNowValue', { value: formatNumber(room.value, 1, locale) })}
              <span class="delta">{formatDelta(target, room.value, locale)}&#8239;K</span>
            </p>
            <BandMeter
              label={t('roomNowLabel')}
              value={room.value}
              {target}
              low={target - HALF_BAND_K}
              high={target + HALF_BAND_K}
              showValue={false}
            />
          {:else}
            <p class="muted">{t('roomStatusNone')}</p>
          {/if}
        </div>
      </div>
    {/snippet}
  </Field>
</Card>

<Card
  bare
  class="room-section-card"
  data-testid="room-sensor-card"
  data-help="settings/room.sensor"
>
  <Field
    id="control_room_signal"
    {schema}
    {config}
    {draft}
    wide
    signals={cfg.signals}
    signalsState={cfg.signalsState}
    {...issues('control_room_signal')}
  />
  <RoomStatusCard {room} {nameOf} help="settings/room.status" />
  <FieldGroup
    {schema}
    {config}
    groups={['room']}
    only={sensorFields}
    collapsed
    title={t('roomSensorBehaviour')}
    icon="settings"
    testid="room-sensor-behaviour"
    helpTarget="settings/room.behaviour"
  />
</Card>

<Card bare class="room-section-card" data-testid="room-feedback-card">
  <FieldGroup {schema} {config} groups={['feedback']} helpTarget="settings/room.correction" />
  <FieldGroup
    {schema}
    {config}
    groups={['monitors']}
    collapsed
    title={t('group_monitors')}
    icon="bell"
    testid="room-monitor"
    helpTarget="settings/room.monitor"
  />
</Card>

<style>
  :global(.room-section-card) {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .comfort-row {
    display: grid;
    grid-template-columns: minmax(12rem, 16rem) minmax(0, 1fr);
    gap: var(--space-3) var(--space-5);
    align-items: center;
  }
  .meter {
    min-width: 0;
  }
  .now {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0;
    font-weight: var(--fw-semibold);
  }
  .delta {
    padding: 0 0.45rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  @container main (max-width: 40rem) {
    .comfort-row {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
