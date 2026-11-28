<!--
  DayShiftCard: what the sun day shift is doing on the Setpoint page. The mode and phase (idle,
  warmer by day, cooler at night, warming back up, blocked), the offset and whether it is applied,
  why in words (reasons, and the guards that hold it back), the next planned change and what
  today's forecast looked like. In shadow a line says what it would have done; switched on, an
  "Experimental" pill says the day shift did not pass its simulator evaluation.

  Props: shift (the `GET control/dayshift` answer).
-->
<script lang="ts">
  import Card from '$ui/Card.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import { minus } from '$lib/core/minus';
  import { settings, t } from '$lib/core/settings.svelte';
  import { phaseTone, plainReasons, shadowKind } from '$lib/setpoint/dayshift';
  import type { DayShift } from '$lib/core/types';

  let { shift }: { shift: DayShift } = $props();

  const locale = $derived(settings.language);
  const num = (value: number | null | undefined, digits = 1) =>
    typeof value === 'number' ? minus(formatNumber(value, digits, locale)) : '–';
  const signed = (value: number) => (value > 0 ? `+${num(value, 2)}` : num(value, 2));
  const phaseName = (phase: DayShift['phase']) =>
    t(`dayshiftPhase_${phase}` as 'dayshiftPhase_idle');
  const reasons = $derived(plainReasons(shift));
  const shadow = $derived(shift.mode === 'shadow');
  const forecast = $derived(shift.forecast);
</script>

<Card
  span={12}
  title={t('dayshiftTitle')}
  icon="sun"
  testid="dayshift-card"
  data-phase={shift.phase}
  data-mode={shift.mode}
>
  {#snippet actions()}
    {#if shift.mode === 'on' && shift.experimental}
      <Pill tone="warn" testid="dayshift-experimental">{t('featureExperimental')}</Pill>
    {/if}
    <Pill tone={shift.mode === 'on' ? 'ok' : 'info'} testid="dayshift-mode-pill">
      {t(`dayshiftMode_${shift.mode}` as 'dayshiftMode_off')}
    </Pill>
    <Pill tone={phaseTone(shift.phase)} size="md" testid="dayshift-phase">
      {phaseName(shift.phase)}
    </Pill>
  {/snippet}

  <p class="offset" data-testid="dayshift-offset">
    <span class="label">{t('dayshiftOffset')}</span>
    <strong>
      {shadow || shift.applied_k === 0
        ? t('dayshiftOffsetShadow', { offset: signed(shift.offset_k) })
        : t('dayshiftOffsetApplied', { offset: signed(shift.applied_k) })}
    </strong>
  </p>
  {#if shadow}
    <p class="shadow" data-testid="dayshift-shadow">
      <Icon name="eye" size={16} />
      {t(`dayshiftShadow_${shadowKind(shift)}` as 'dayshiftShadow_none', {
        k: num(Math.abs(shift.offset_k), 2),
      })}
    </p>
  {/if}

  {#if reasons.length > 0 || shift.guards.length > 0}
    {#if reasons.length > 0}
      <ul class="reasons" data-testid="dayshift-reasons">
        {#each reasons as reason (reason)}
          <li>{t(`dayshiftReason_${reason}` as 'dayshiftReason_off')}</li>
        {/each}
      </ul>
    {/if}
    {#if shift.guards.length > 0}
      <p class="guards" data-testid="dayshift-guards">
        <Icon name="warning" size={16} />
        <span class="label">{t('dayshiftGuards')}</span>
        {shift.guards.map((g) => t(`dayshiftReason_${g}` as 'dayshiftReason_off')).join(' ')}
      </p>
    {/if}
  {/if}

  <p class="next" data-testid="dayshift-next">
    {shift.next_change
      ? t('dayshiftNext', {
          phase: phaseName(shift.next_change.phase),
          time: formatDateTime(shift.next_change.at, locale),
        })
      : t('dayshiftNextNone')}
  </p>

  <p class="forecast" data-testid="dayshift-forecast">
    <span class="label">{t('dayshiftForecast')}</span>
    {#if forecast}
      {t('dayshiftForecastLine', {
        sun: num(forecast.sun_wm2, 0),
        sunLimit: num(forecast.sun_limit_wm2, 0),
        outside: num(forecast.outside_c),
        min: num(forecast.outside_min_c),
        limit: num(forecast.outside_limit_c),
        night: num(forecast.night_min_c),
      })}
      {#if forecast.issued_at}
        <span class="muted"
          >· {t('dayshiftForecastIssued', {
            time: formatDateTime(forecast.issued_at, locale),
          })}</span
        >
      {/if}
    {:else}
      {t('dayshiftForecastNone')}
    {/if}
  </p>
  <p class="muted windows" data-testid="dayshift-windows">
    {t('dayshiftWindows', {
      dayStart: shift.windows.day_start,
      dayEnd: shift.windows.day_end,
      nightStart: shift.windows.night_start,
      nightEnd: shift.windows.night_end,
      comfortAt: shift.windows.comfort_at,
    })}
  </p>
</Card>

<style>
  p {
    margin: 0;
  }
  .label {
    color: var(--muted);
    margin-right: var(--space-1);
  }
  .shadow,
  .guards {
    display: flex;
    align-items: flex-start;
    gap: var(--space-1);
  }
  .shadow :global(.icon),
  .guards :global(.icon) {
    flex: none;
    margin-top: var(--space-1);
  }
  .guards {
    color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .reasons {
    margin: 0;
    padding-left: var(--space-4);
  }
  .windows {
    font-size: var(--fs-caption);
  }
</style>
