<!--
  DayTable: the divergence per local day (compared share, mean and largest difference, time above
  the threshold, episodes started that day); a day at the edge of the window says how much of it
  is in. Scrolls sideways inside its own box on a narrow screen, never the page.

  Props: days (DivergenceDay[], oldest first), thresholdK, timezone, now (service clock, ms).
-->
<script lang="ts">
  import { formatDay, formatDuration, formatNumber } from '$lib/core/format';
  import { settings, t } from '$lib/core/settings.svelte';
  import { dayHours, type DivergenceDay } from '$lib/shadow/shadow';

  interface Props {
    days: DivergenceDay[];
    thresholdK: number;
    timezone: string;
    now: number;
  }

  let { days, thresholdK, timezone, now }: Props = $props();

  const lang = $derived(settings.language);
  const num = (value: number | null, digits = 1) =>
    value === null ? '–' : formatNumber(value, digits, lang);
  const rows = $derived([...days].reverse());
  const label = (day: DivergenceDay) => formatDay(`${day.date}T12:00:00`, lang, now);
</script>

<p class="caption muted lead">{t('shadowDaysCaption', { tz: timezone })}</p>
<p class="caption muted hint">{t('shadowDaysScroll')}</p>
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
  class="scroll"
  role="region"
  aria-label={t('shadowDaysTitle')}
  tabindex="0"
  data-testid="shadow-days-scroll"
>
  <table data-testid="shadow-days">
    <caption class="visually-hidden">{t('shadowDaysCaption', { tz: timezone })}</caption>
    <thead>
      <tr>
        <th scope="col">{t('shadowColDay')}</th>
        <th scope="col" class="num">{t('shadowColCoverage')}</th>
        <th scope="col" class="num">{t('shadowColMean')}</th>
        <th scope="col" class="num">{t('shadowColMax')}</th>
        <th scope="col" class="num">{t('shadowColOver', { k: num(thresholdK) })}</th>
        <th scope="col" class="num">{t('shadowColEpisodes')}</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as day (day.date)}
        {@const hours = dayHours(day)}
        <tr data-date={day.date}>
          <th scope="row">
            <span class="day">{label(day)}</span>
            {#if hours < 23}
              <span class="part caption muted"
                >{t('shadowPartialDay', { hours: formatDuration(hours * 3600, lang) })}</span
              >
            {/if}
          </th>
          <td class="num">{day.coverage === null ? '–' : `${num(day.coverage * 100, 0)} %`}</td>
          <td class="num">{num(day.mean_abs_k)} K</td>
          <td class="num">{num(day.max_abs_k)} K</td>
          <td class="num"
            >{day.hours_over > 0 ? formatDuration(day.hours_over * 3600, lang) : '–'}</td
          >
          <td class="num">{day.episodes}</td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .scroll {
    overflow: auto;
    max-width: 100%;
    max-height: 18rem;
    border-radius: var(--radius-sm);
  }
  thead th {
    position: sticky;
    top: 0;
    background: var(--surface);
    z-index: 1;
  }
  .scroll:focus-visible {
    outline: 3px solid var(--accent);
    outline-offset: 2px;
  }
  table {
    min-width: 30rem;
  }
  .lead,
  .hint {
    margin: 0 0 var(--space-2);
  }
  .hint {
    display: none;
  }
  th,
  td {
    white-space: nowrap;
  }
  .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  tbody th {
    font-weight: var(--fw-semibold);
  }
  .part {
    display: block;
    font-weight: var(--fw-regular);
  }
  @media (--narrow) {
    .hint {
      display: block;
    }
    th,
    td {
      padding: 0.4rem 0.4rem;
    }
  }
</style>
