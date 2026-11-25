<!--
  RoomCard: room temperature as a number, the comfort band meter with trend, and the sensor
  freshness in words, following the controller's trust: "Sensor ok" only while the value is
  trusted, "value is old, ovenbird trusts it less" below full cooling authority, and an amber
  "room value not trusted" (with a link to Setpoint) at zero authority or a failed cross-check.

  Props: value, target (°C | null), halfBand (K), trend (K/h | null), fresh (sensor delivering),
  changedAgoS (seconds since the value last changed | null), configured (room sensor set up),
  trust (RoomTrust), authority (0..1 | null), ontarget (what "Target 21.0 °C" does: open the
  comfort stepper; the target is always the same button, disabled until ontarget is given, so a
  tap right after load never lands on a plain label), actions (header snippet, e.g. "Stove on…").
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import type { Snippet } from 'svelte';
  import type { RoomTrust } from '$lib/core/derive';
  import { formatAge, formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import BandMeter from '$components/charts/BandMeter.svelte';
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    value: number | null;
    target: number | null;
    halfBand: number;
    trend: number | null;
    fresh: boolean;
    changedAgoS: number | null;
    configured: boolean;
    trust?: RoomTrust;
    authority?: number | null;
    ontarget?: () => void;
    actions?: Snippet;
  }

  let {
    value,
    target,
    halfBand,
    trend,
    fresh,
    changedAgoS,
    configured,
    trust = 'ok',
    authority = null,
    ontarget,
    actions,
  }: Props = $props();

  const locale = $derived(settings.language);
  const low = $derived(target === null ? null : target - halfBand);
  const high = $derived(target === null ? null : target + halfBand);
  const trendIcon = $derived(
    trend === null || Math.abs(trend) < 0.05 ? 'trendFlat' : trend > 0 ? 'trendUp' : 'trendDown',
  );
  const warn = $derived(!fresh || trust === 'untrusted' || trust === 'implausible');
  const why = $derived(fresh && trust !== 'ok');
  const sensorText = $derived.by(() => {
    if (fresh && trust === 'implausible') return t('roomSensorImplausible');
    if (changedAgoS === null) return '';
    const age = formatAge(changedAgoS);
    if (!fresh) return t('roomSensorStale', { age });
    if (trust === 'untrusted') return t('roomSensorUntrusted', { age });
    if (trust === 'reduced')
      return t('roomSensorOld', { age, pct: Math.round((authority ?? 0) * 100) });
    return t('roomSensorOk', { age });
  });
</script>

<Card
  title={t('roomTemperature')}
  icon="home"
  span={5}
  testid="room-hero"
  help="home.room"
  {actions}
>
  {#if value !== null}
    <div class="reading" class:stale={!fresh}>
      <span class="value" data-testid="room-value"
        >{formatNumber(value, 1, locale)}<span class="unit">&#8239;°C</span></span
      >
      {#if trend !== null}<Icon name={trendIcon} size={24} />{/if}
      {#if target !== null}
        <Button
          class="room-target room-edit"
          onclick={() => ontarget?.()}
          disabled={!ontarget}
          aria-label={t('roomTargetEdit', { target: formatNumber(target, 1, locale) })}
          data-testid="room-target"
          >{t('roomNowTarget', { target: formatNumber(target, 1, locale) })}<Icon
            name="edit"
            size={14}
          /></Button
        >
      {/if}
    </div>
    {#if low !== null && high !== null}
      <BandMeter
        label={t('roomTemperature')}
        {value}
        {target}
        {low}
        {high}
        {trend}
        showValue={false}
      />
    {/if}
    {#if sensorText}
      <p class="caption" class:warn data-testid="room-trust" data-trust={fresh ? trust : 'stale'}>
        {#if warn}<Icon name="warning" size={14} />{/if}
        {sensorText}
        {#if why}<a class="why" href="#/setpoint">{t('roomSensorWhy')}</a>{/if}
      </p>
    {/if}
  {:else}
    <p class="value" data-testid="room-value">–</p>
    <p class="caption">{configured ? t('roomUnavailable') : t('roomNotConfigured')}</p>
  {/if}
</Card>

<style>
  .reading {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .reading :global(.icon) {
    align-self: center;
    color: var(--muted);
  }
  .reading.stale .value {
    color: var(--muted);
  }
  .value {
    font-size: var(--fs-hero);
    font-family: var(--font-display);
    font-weight: var(--fw-bold);
    line-height: 1.05;
    font-variant-numeric: tabular-nums;
  }
  .unit {
    font-size: 0.4em;
    color: var(--muted);
    font-weight: var(--fw-medium);
  }
  :global(.room-target) {
    margin-left: auto;
    color: var(--muted);
    font-size: var(--fs-body);
  }
  :global(.room-target.room-edit) {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    min-height: 36px;
    padding: 0.15rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    color: var(--text);
    font-weight: var(--fw-semibold);
    cursor: pointer;
  }
  :global(.room-target.room-edit):hover:enabled {
    border-color: var(--accent);
    color: var(--accent);
  }
  :global(.room-target.room-edit):disabled {
    opacity: 1;
    color: var(--muted);
    cursor: default;
  }
  @media (--narrow), (pointer: coarse) {
    :global(.room-target.room-edit) {
      min-height: var(--tap);
    }
  }
  p {
    margin: 0;
  }
  .warn {
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .caption :global(.icon) {
    vertical-align: -2px;
  }
  .why {
    margin-left: var(--space-1);
    font-weight: var(--fw-medium);
  }
</style>
