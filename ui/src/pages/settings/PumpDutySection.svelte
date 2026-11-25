<!--
  Pump section: whether the app shows hot water, with what the pump reports about its tank, then
  what the pump reports now about its duty (maximum and current duty, the fixed allowed range) as
  stat chips, then the duty settings.
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import FieldGroup from '$components/settings/FieldGroup.svelte';
  import StatChip from '$ui/StatChip.svelte';
  import { formatNumber } from '$lib/core/format';
  import { getSignal } from '$lib/core/derive';
  import { INSTALLED_SIGNAL, reportedInstalled } from '$lib/core/hotWater.svelte';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  interface Props {
    live: LiveStore;
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { live, schema, config }: Props = $props();

  const min = $derived(config.fields['command_pump_duty_min']?.value);
  const max = $derived(config.fields['command_pump_duty_max']?.value);
  const reported = (id: string) => {
    const value = getSignal(live.snapshot, id)?.value;
    return typeof value === 'number' ? formatNumber(value, 0, settings.language) : '–';
  };
  const tank = $derived(
    reportedInstalled(getSignal(live.snapshot, INSTALLED_SIGNAL)?.value) ??
      config.hot_water?.installed ??
      null,
  );
  const tankKey = $derived(
    tank === null ? 'hotWaterTank_unknown' : tank ? 'hotWaterTank_yes' : 'hotWaterTank_no',
  );
</script>

<Card bare as="div" data-help="settings/pump-duty.hot-water">
  <FieldGroup {schema} {config} groups={['pump']} />
  <p class="tank muted" data-testid="hot-water-tank" data-installed={tank ?? 'unknown'}>
    {t(tankKey)}
  </p>
</Card>
<section class="chips" data-testid="pump-duty-reported" data-help="settings/pump-duty.reported">
  <StatChip label={t('dutyReportedMax')} value={reported('main/Max_Pump_Duty')} icon="pump" />
  <StatChip label={t('dutyReportedNow')} value={reported('main/Pump_Duty')} icon="pump" />
  {#if typeof min === 'number' && typeof max === 'number'}
    <StatChip label={t('dutyFixedRange')} value="{min}–{max}" icon="lock" />
  {/if}
</section>
<Card bare as="div" data-help="settings/pump-duty.settings">
  <FieldGroup {schema} {config} groups={['pump_duty']} />
</Card>

<style>
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(9rem, 30%), 1fr));
    gap: var(--space-3);
  }
  .tank {
    margin: var(--space-2) 0 0;
    font-size: var(--fs-caption);
  }
</style>
