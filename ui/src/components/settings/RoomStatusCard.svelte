<!--
  RoomStatusCard: the controller's view of the room sensor as one compact row of chips —
  freshness (icon + word), value, held for, alive by, authority as a small bar and
  plausibility. No card chrome: the Room section places it under the sensor picker.
-->
<script lang="ts">
  import { formatAge, formatNumber } from '$lib/core/format';
  import { livenessKind } from '$lib/setpoint/explain';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { RoomStatus } from '$lib/core/types';
  import Icon from '$ui/Icon.svelte';

  let {
    room,
    nameOf = (signal: string) => signal,
    help,
  }: { room: RoomStatus | null; nameOf?: (signal: string) => string; help?: string } = $props();
  const locale = $derived(settings.language);
  const authority = $derived(
    room?.authority === null || room?.authority === undefined
      ? null
      : Math.round(Math.min(Math.max(room.authority, 0), 1) * 100),
  );
</script>

<div
  class="room-status"
  data-testid="room-status"
  data-help={help}
  aria-label={t('roomStatusTitle')}
  role="group"
>
  {#if room}
    <span class="chip state" class:ok={room.fresh} class:bad={!room.fresh}>
      <Icon name={room.fresh ? 'check' : 'warning'} size={16} />
      {room.fresh ? t('roomStatusFreshYes') : t('roomStatusFreshNo')}
    </span>
    <span class="chip value">
      <Icon name="thermometer" size={16} />
      <strong>{room.value === null ? '–' : `${formatNumber(room.value, 1, locale)}`}</strong>
      <span class="unit">°C</span>
    </span>
    {#if room.held_s !== null}
      <span class="chip" title={t('roomStatusHeld')}>
        <Icon name="clock" size={16} />{t('roomStatusHeldFor', { age: formatAge(room.held_s) })}
      </span>
    {/if}
    {#if room.alive_by}
      <span class="chip" title={t('roomStatusAlive')}>
        <Icon name="power" size={16} />{t('roomStatusAliveBy', {
          signal: livenessKind(nameOf(room.alive_by), (key) => tOpt(key)),
          age: room.alive_s !== null ? formatAge(room.alive_s) : '–',
        })}
      </span>
    {/if}
    {#if authority !== null}
      <span class="chip" title={t('roomStatusAuthority')}>
        {t('roomStatusAuthority')}
        <span class="meter" aria-hidden="true"><span style:width="{authority}%"></span></span>
        <strong>{authority}&#8239;%</strong>
      </span>
    {/if}
    {#if room.plausible !== null}
      <span class="chip" class:bad={!room.plausible}>
        <Icon name={room.plausible ? 'check' : 'warning'} size={16} />
        {room.plausible ? t('roomStatusPlausibleYes') : t('roomStatusPlausibleNo')}
      </span>
    {/if}
  {:else}
    <span class="muted">{t('roomStatusNone')}</span>
  {/if}
</div>

<style>
  .room-status {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-2);
    font-size: var(--fs-caption);
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.15rem 0.55rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    color: var(--muted);
    white-space: nowrap;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .chip strong {
    color: var(--text);
  }
  .chip.ok {
    background: var(--status-ok-bg);
    color: var(--status-ok);
    font-weight: var(--fw-semibold);
  }
  .chip.bad {
    background: var(--status-limited-bg);
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .value strong {
    font-size: var(--fs-body);
  }
  .meter {
    display: inline-block;
    width: 2.5rem;
    height: 6px;
    border-radius: var(--radius-xs);
    background: var(--border);
    overflow: hidden;
  }
  .meter span {
    display: block;
    height: 100%;
    background: var(--series-room);
  }
</style>
