<!--
  TimelineCard: how the model is learned. The room prediction error per day of the held-out block
  (one bar per day, a table behind "Show as table"), the error of each model run, the periods the
  learner left out of the fit (wood-stove episodes) and what the model in use was fitted on.

  Each day can be left out of the next fit: a bar of the chart (a button for keyboard and screen
  reader) or a button in the table toggles it in the settings draft (`house_learn_excluded_days`).

  Props: house (HouseInsight), schema and config (without them the days are not selectable).
  A11y: the chart is a group with a sentence, each day a toggle button; the table lists the same
  days with the same toggle.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import { linearScale, niceTicks } from '$lib/core/chart';
  import { chartText, formatNum } from '$lib/core/chartSummary';
  import { draft } from '$lib/core/draft.svelte';
  import { formatDateTime, formatDay, timeLocale } from '$lib/core/format';
  import type { ConfigDoc, ConfigSchema } from '$lib/core/types';
  import type { HouseInsight } from '$lib/house/house';
  import { EXCLUDED_DAYS, cleanDays, toggleDay } from '$lib/house/settings';
  import { errorStats, fittedOn, leftOutPeriods, runErrors } from '$lib/house/timeline';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import { SERIES } from '$components/charts/palette';

  interface Props {
    house: HouseInsight;
    schema?: ConfigSchema | null;
    config?: ConfigDoc | null;
  }

  let { house, schema = null, config = null }: Props = $props();

  const selectable = $derived(Boolean(schema?.fields[EXCLUDED_DAYS] && config));
  const chosen = $derived(new Set(cleanDays(draft.value(EXCLUDED_DAYS, config))));
  const maxDays = $derived(schema?.fields[EXCLUDED_DAYS]?.max_items ?? undefined);
  const toggle = (day: string) =>
    draft.set(
      EXCLUDED_DAYS,
      toggleDay(cleanDays(draft.value(EXCLUDED_DAYS, config)), day, maxDays),
      config,
    );
  const dayName = (day: string) => formatDay(day, lang);
  const toggleLabel = (day: string) =>
    t(chosen.has(day) ? 'houseDayKeepIn' : 'houseDayLeaveOut', { day: dayName(day) });

  const lang = $derived(settings.language);
  const num = (value: number, digits = 2) => formatNum(value, digits, lang);
  const shortDay = (iso: string) =>
    new Date(iso).toLocaleDateString(timeLocale(lang), { day: 'numeric', month: 'short' });

  const daily = $derived(house.daily_error ?? []);
  const stats = $derived(errorStats(daily));
  const runs = $derived(runErrors(house.error_trend));
  const leftOut = $derived(leftOutPeriods(house.events));
  const fitted = $derived(fittedOn(house.provenance));
  const excludedDays = $derived(house.data?.excluded_days?.length ?? 0);

  let measured = $state(0);
  let showTable = $state(false);
  const width = $derived(measured > 0 ? measured : 320);
  const height = 150;
  const pad = { left: 40, right: 8, top: 12, bottom: 24 };
  const yMax = $derived(Math.max(0.05, ...daily.map((day) => day.room_rmse_24h_k ?? 0)) * 1.15);
  const sy = $derived(linearScale(0, yMax, height - pad.bottom, pad.top));
  const slot = $derived((width - pad.left - pad.right) / Math.max(daily.length, 1));
  const barWidth = $derived(Math.max(2, slot * 0.7));
  const yTicks = $derived(niceTicks(0, yMax, 3, 0.01).filter((tick) => tick <= yMax));
  const labelAt = $derived(
    new Set([0, Math.floor((daily.length - 1) / 2), daily.length - 1].filter((i) => i >= 0)),
  );
  const summary = $derived(
    stats === null
      ? t('houseDailyNone')
      : t('houseDailySummary', {
          n: stats.days,
          min: num(stats.min, 3),
          max: num(stats.max, 3),
          mean: num(stats.mean, 3),
          worst: formatDay(stats.worstDate, lang),
        }),
  );
  const runsText = $derived(
    runs.length === 0
      ? null
      : t('houseRunErrors', { list: runs.map((v) => num(v, 3)).join(' → ') }),
  );
  const span = (from: string | null, to: string | null) =>
    from && to ? `${formatDateTime(from, lang)} – ${formatDateTime(to, lang)}` : null;
</script>

<Card
  title={t('houseTimelineTitle')}
  subtitle={t('houseTimelineSubtitle')}
  icon="clock"
  testid="house-timeline"
  help="house.timeline"
  span={7}
>
  <div class="body">
    <section class="part">
      <h3>{t('houseDailyTitle')}</h3>
      {#if stats !== null}
        <div class="plot" bind:clientWidth={measured}>
          <svg
            {width}
            {height}
            viewBox="0 0 {width} {height}"
            role="group"
            aria-label={summary}
            data-testid="daily-error-plot"
            data-bars={stats.days}
          >
            {#each yTicks as tick (tick)}
              <line class="grid" x1={pad.left} x2={width - pad.right} y1={sy(tick)} y2={sy(tick)} />
              <text class="tick" x={pad.left - 6} y={sy(tick) + 4} text-anchor="end"
                >{num(tick, 2)}</text
              >
            {/each}
            {#each daily as day, i (day.date)}
              {@const left = chosen.has(day.date)}
              <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
              <g
                class="day"
                class:left-out={left}
                class:pick={selectable}
                role={selectable ? 'button' : undefined}
                tabindex={selectable ? 0 : undefined}
                aria-pressed={selectable ? left : undefined}
                aria-label={selectable
                  ? `${toggleLabel(day.date)}${day.room_rmse_24h_k === null ? '' : ` · ${num(day.room_rmse_24h_k, 3)} K`}`
                  : undefined}
                data-testid="day-bar-{day.date}"
                onclick={selectable ? () => toggle(day.date) : undefined}
                onkeydown={selectable
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        toggle(day.date);
                      }
                    }
                  : undefined}
              >
                <rect
                  class="hit"
                  x={pad.left + i * slot}
                  y={pad.top}
                  width={slot}
                  height={height - pad.top - pad.bottom}
                />
                {#if day.room_rmse_24h_k !== null}
                  <rect
                    class="bar"
                    x={pad.left + i * slot + (slot - barWidth) / 2}
                    y={sy(day.room_rmse_24h_k)}
                    width={barWidth}
                    height={Math.max(0, height - pad.bottom - sy(day.room_rmse_24h_k))}
                    style:fill={SERIES.room}
                  >
                    <title>{formatDay(day.date, lang)} · {num(day.room_rmse_24h_k, 3)} K</title>
                  </rect>
                {/if}
                {#if left}
                  <line
                    class="strike"
                    x1={pad.left + i * slot + slot * 0.15}
                    x2={pad.left + i * slot + slot * 0.85}
                    y1={height - pad.bottom - 6}
                    y2={pad.top + 6}
                  />
                {/if}
              </g>
              {#if labelAt.has(i)}
                <text
                  class="tick"
                  x={pad.left + i * slot + slot / 2}
                  y={height - 6}
                  text-anchor={i === 0 ? 'start' : i === daily.length - 1 ? 'end' : 'middle'}
                  >{shortDay(day.date)}</text
                >
              {/if}
            {/each}
            <text class="axis" x="4" y="9">{t('houseAxisError')}</text>
          </svg>
        </div>
        <p class="caption" data-testid="daily-error-summary">{summary}</p>
        {#if selectable}
          <p class="caption" data-testid="leave-out-why">
            {t('houseDaysWhy')}
            {t('houseDayPickHint')}
          </p>
        {/if}
        <Button
          variant="link"
          class="timeline-link"
          aria-expanded={showTable}
          onclick={() => (showTable = !showTable)}
          data-testid="daily-error-toggle"
          >{chartText(lang, showTable ? 'hideTable' : 'showTable')}</Button
        >
        {#if showTable}
          <div class="table-wrap">
            <table data-testid="daily-error-table">
              <thead>
                <tr>
                  <th scope="col">{t('houseColDay')}</th>
                  <th scope="col">{t('houseColError')}</th>
                  <th scope="col">{t('houseColOrigins')}</th>
                  {#if selectable}<th scope="col">{t('houseColLeaveOut')}</th>{/if}
                </tr>
              </thead>
              <tbody>
                {#each daily as day (day.date)}
                  <tr>
                    <td>{formatDay(day.date, lang)}</td>
                    <td class="num"
                      >{day.room_rmse_24h_k === null ? '–' : num(day.room_rmse_24h_k, 3)}</td
                    >
                    <td class="num">{day.origins}</td>
                    {#if selectable}
                      <td>
                        <Button
                          size="sm"
                          variant={chosen.has(day.date) ? 'primary' : 'default'}
                          aria-pressed={chosen.has(day.date)}
                          aria-label={toggleLabel(day.date)}
                          onclick={() => toggle(day.date)}
                          data-testid="day-toggle-{day.date}"
                        >
                          {chosen.has(day.date) ? t('houseDayLeftOut') : t('houseColLeaveOut')}
                        </Button>
                      </td>
                    {/if}
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      {:else}
        <p class="muted" data-testid="daily-error-none">{t('houseDailyNone')}</p>
      {/if}
      {#if runsText}<p class="caption" data-testid="run-errors">{runsText}</p>{/if}
    </section>

    <section class="part">
      <h3>{t('houseLeftOutTitle')}</h3>
      {#if leftOut.length > 0}
        <ul class="periods" data-testid="left-out">
          {#each leftOut as period, i (i)}
            <li>
              <strong
                >{period.kind === 'stove' || period.kind === 'stove_mode'
                  ? t('houseLeftOutStove')
                  : t('houseLeftOutOther')}</strong
              >
              {#if period.start}
                <span
                  >{formatDateTime(period.start, lang)}{#if period.hours !== null}
                    · {t('houseLeftOutHours', { n: num(period.hours, 1) })}{/if}</span
                >
              {/if}
              {#if period.excludedHours !== null}
                <span class="caption"
                  >{t('houseLeftOutExcluded', { n: num(period.excludedHours, 0) })}</span
                >
              {/if}
            </li>
          {/each}
        </ul>
        <p class="caption">{t('houseLeftOutWhy')}</p>
      {:else}
        <p class="muted" data-testid="left-out-none">{t('houseLeftOutNone')}</p>
      {/if}
      {#if excludedDays > 0}
        <p class="caption" data-testid="excluded-days">
          {t('houseExcluded', { n: excludedDays })}
        </p>
      {/if}
    </section>

    <section class="part">
      <h3>{t('houseFittedTitle')}</h3>
      <dl class="facts" data-testid="house-fitted">
        {#if span(fitted.from, fitted.to)}
          <div>
            <dt>{t('houseFittedData')}</dt>
            <dd>
              {span(fitted.from, fitted.to)}{#if fitted.fitDays !== null}
                <span class="caption">
                  {t('houseFittedDays', { n: num(fitted.fitDays, 0) })}{#if fitted.stepS !== null}
                    · {t('houseFittedStep', { n: num(fitted.stepS / 60, 0) })}{/if}</span
                >{/if}
            </dd>
          </div>
        {/if}
        {#if fitted.method}
          <div>
            <dt>{t('houseFittedMethod')}</dt>
            <dd>
              {tOpt(`houseFittedMethod_${fitted.method}`) ?? fitted.method}
              {#if fitted.fallbackReason}
                <span class="caption"
                  >{t('houseFittedFallback', { reason: fitted.fallbackReason })}</span
                >
              {/if}
            </dd>
          </div>
        {/if}
        {#if fitted.bootstrap !== null || fitted.folds !== null}
          <div>
            <dt>{t('houseFittedChecks')}</dt>
            <dd>
              {t('houseFittedChecksText', {
                bootstrap: fitted.bootstrap ?? 0,
                folds: fitted.folds ?? 0,
              })}
            </dd>
          </div>
        {/if}
        {#if fitted.generated}
          <div>
            <dt>{t('houseFittedMade')}</dt>
            <dd>
              {formatDateTime(fitted.generated, lang)}{#if fitted.codeVersion}
                <span class="caption">{t('houseFittedVersion', { v: fitted.codeVersion })}</span
                >{/if}
            </dd>
          </div>
        {/if}
      </dl>
    </section>
  </div>
</Card>

<style>
  .body {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: var(--space-4);
  }
  .part {
    display: grid;
    gap: var(--space-2);
    align-content: start;
    min-width: 0;
  }
  h3 {
    margin: 0;
    font-size: var(--fs-body);
  }
  p {
    margin: 0;
  }
  .plot {
    min-width: 0;
  }
  svg {
    display: block;
    max-width: 100%;
  }
  .grid {
    stroke: var(--chart-grid, var(--border));
    stroke-width: 1;
  }
  .tick,
  .axis {
    fill: var(--chart-axis, var(--muted));
    font-size: var(--fs-caption);
    font-variant-numeric: tabular-nums;
  }
  .bar {
    fill-opacity: 0.85;
  }
  .hit {
    fill: transparent;
  }
  .pick {
    cursor: pointer;
  }
  .pick:hover .hit {
    fill: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .pick:focus-visible {
    outline: none;
  }
  .pick:focus-visible .hit {
    stroke: var(--accent);
    stroke-width: 2;
  }
  .left-out .bar {
    fill-opacity: 0.3;
  }
  .strike {
    stroke: var(--muted);
    stroke-width: 1.5;
  }
  :global(.timeline-link) {
    justify-self: start;
    min-height: var(--control-h);
  }
  .table-wrap {
    max-height: 20rem;
    overflow: auto;
  }
  .periods {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: var(--space-2);
  }
  .periods li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0 var(--space-2);
  }
  .facts {
    display: grid;
    gap: var(--space-2);
    margin: 0;
  }
  .facts dt {
    color: var(--muted);
    font-size: var(--fs-caption);
  }
  .facts dd {
    margin: 0;
  }
  .facts .caption {
    display: block;
  }
</style>
