<!--
  Wood-stove section: what wood-stove mode does right now (on or off, the applied back-off, the
  start and end thresholds, why the detection waits) as stat chips and one sentence, then the
  wood-stove settings. Pump-duty section as template. The reference room is picked from the same
  list as the room sensor; an amber line says when it is set but ovenbird has no fresh reading of
  it (the guard cannot work), and a quiet line when none is set (no other room is watched).
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import FieldGroup from '$components/settings/FieldGroup.svelte';
  import Icon from '$ui/Icon.svelte';
  import StatChip from '$ui/StatChip.svelte';
  import { cfg } from '$lib/core/cfg.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { formatClock, formatNumber } from '$lib/core/format';
  import { stoveReference, stoveWaiting } from '$lib/stove/stove';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import { signalName } from '$lib/core/signalView';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

  interface Props {
    ctl: ControlStore;
    schema: ConfigSchema;
    config: ConfigDoc;
  }

  let { ctl, schema, config }: Props = $props();

  $effect(() => {
    void cfg.loadSignals();
  });

  const locale = $derived(settings.language);
  const stove = $derived(ctl.control?.stove ?? null);
  const enabled = $derived(config.fields['control_stove_enabled']?.value === true);
  const num = (value: number | null | undefined, digits = 1) =>
    typeof value === 'number' ? formatNumber(value, digits, locale) : '–';
  const backoff = $derived(
    stove?.active ? stove.backoff_k : config.fields['control_stove_backoff_k']?.value,
  );
  const waiting = $derived(stoveWaiting(stove));
  const refSignal = $derived.by(() => {
    const value = config.fields['control_stove_reference_signal']?.value;
    return typeof value === 'string' && value ? value : null;
  });
  const reference = $derived(stove ? stoveReference(stove, refSignal) : null);
  const refName = $derived.by(() => {
    if (!refSignal) return '';
    const listed = cfg.signals?.room.find((c) => c.signal === refSignal)?.name;
    return signalName(refSignal, listed, tOpt);
  });
  const field = (id: string) => {
    const value = config.fields[id]?.value;
    return typeof value === 'number' ? value : null;
  };
  const enterC = $derived.by(() => {
    if (stove?.enter_c != null) return stove.enter_c;
    const comfort = field('control_comfort_c');
    const above = field('control_stove_enter_above_k');
    return comfort !== null && above !== null ? comfort + above : null;
  });
  const exitC = $derived.by(() => {
    if (stove?.exit_c != null) return stove.exit_c;
    const hysteresis = field('control_stove_exit_hysteresis_k');
    return enterC !== null && hysteresis !== null ? enterC - hysteresis : null;
  });
</script>

<section class="chips" data-testid="stove-status" data-help="settings/stove.status">
  <StatChip
    label={t('stoveChipNow')}
    value={!enabled ? t('off') : stove?.active ? t('stoveChipActive') : t('stoveChipIdle')}
    icon="flame"
    tone={stove?.active ? 'limited' : 'default'}
    caption={stove?.active && stove.since
      ? t('stoveChipSince', { time: formatClock(stove.since, locale) })
      : undefined}
    testid="stove-chip-state"
  />
  <StatChip
    label={t('stoveChipBackoff')}
    value={config.fields['control_stove_to_minimum']?.value === true && !stove?.active
      ? t('stoveChipToMinimum')
      : num(typeof backoff === 'number' ? backoff : null)}
    unit={config.fields['control_stove_to_minimum']?.value === true && !stove?.active
      ? undefined
      : 'K'}
    icon="trendDown"
  />
  <StatChip
    label={t('stoveChipEnter')}
    value={num(enterC)}
    unit="°C"
    icon="thermometer"
    caption={exitC !== null ? t('stoveChipExit', { value: num(exitC) }) : undefined}
  />
</section>
{#if enabled && waiting}
  <p class="waiting muted" data-testid="stove-waiting">
    {t(`stoveWait_${waiting}` as 'stoveWait_blocked', { exit: num(exitC) })}
  </p>
{/if}
{#if enabled && reference === 'stale'}
  <p class="ref warn" role="status" data-testid="stove-reference" data-reference="stale">
    <Icon name="warning" size={16} />{t('stoveRefSettingsStale', { room: refName })}
  </p>
{:else if enabled && reference === 'none'}
  <p class="ref muted" data-testid="stove-reference" data-reference="none">
    {t('stoveRefSettingsNone')}
  </p>
{/if}
<Card bare as="div" data-help="settings/stove.settings">
  <FieldGroup {schema} {config} groups={['stove']} />
</Card>

<style>
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(9rem, 30%), 1fr));
    gap: var(--space-3);
  }
  .waiting,
  .ref {
    margin: 0;
  }
  .ref.warn {
    display: flex;
    align-items: flex-start;
    gap: 0.4rem;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--status-limited-bg);
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .ref.warn :global(.icon) {
    flex: none;
    margin-top: 0.1rem;
  }
</style>
