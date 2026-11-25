<!--
  DecisionTable: what the controller did in the window, as episodes (ticks with the same reason
  merged: "13:18–13:39 · Compressor start · 30 → 32 °C · 22 min"), newest first, with command
  holds and gaps as rows of their own. "Show every decision" switches to one row per tick (the
  newest decisions). Every row links to the moment (`#/setpoint?at=…`).

  Props: episodes (oldest first, from buildEpisodes); decisions (newest ticks, oldest first);
  selected (ms of the inspected tick, highlights its row); range (hours, kept in the links);
  now (ms); limit (episode rows before "Show all"; default 8, 3 when narrow).
  A11y: a real table with column headers; the category icon has a text label.
-->
<script lang="ts">
  import Segmented from '$ui/Segmented.svelte';
  import Button from '$ui/Button.svelte';
  import { dayOffset, formatClock, formatDateTime, formatDuration } from '$lib/core/format';
  import type { Episode } from '$lib/setpoint/episodes';
  import { BUSY_ICON, hotWater } from '$lib/core/hotWater.svelte';
  import type { IconName } from '$lib/core/icons';
  import { buildHash } from '$lib/core/router.svelte';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import type { Decision } from '$lib/core/types';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    episodes: Episode[];
    decisions?: Decision[];
    selected?: number | null;
    range?: number;
    now?: number;
    limit?: number;
  }

  let {
    episodes,
    decisions = [],
    selected = null,
    range = 24,
    now = Date.now(),
    limit,
  }: Props = $props();

  let view = $state<'episodes' | 'all'>('episodes');
  const viewOptions = $derived([
    { value: 'episodes' as const, label: t('viewEpisodes'), testid: 'view-episodes' },
    { value: 'all' as const, label: t('viewEvery'), testid: 'view-all' },
  ]);
  let width = $state(800);

  function measure(node: HTMLElement): () => void {
    width = node.clientWidth || width;
    if (typeof ResizeObserver === 'undefined') return () => undefined;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => (width = node.clientWidth || width));
    });
    observer.observe(node);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }
  const rowsShown = $derived(limit ?? (width < 560 ? 3 : 8));
  let expanded = $state(false);

  const newest = $derived([...episodes].reverse());
  const shown = $derived(expanded ? newest : newest.slice(0, rowsShown));
  const ticks = $derived([...decisions].reverse().slice(0, 30));

  const CATEGORY_ICON: Record<string, IconName> = {
    normal: 'check',
    limited: 'ramp',
    frozen: 'snowflake',
    stopped: 'pause',
    manual: 'hand',
  };

  function icon(episode: Episode): IconName {
    if (episode.kind === 'gap') return 'clock';
    if (episode.kind === 'hold') return 'lock';
    if (episode.reason === 'defrost_freeze') return 'snowflake';
    if (episode.reason === 'dhw_freeze') return hotWater.shown ? 'tap' : BUSY_ICON;
    if (episode.group === 'start') return 'ramp';
    if (episode.group === 'keep') return 'pause';
    if (episode.reason === 'safety_clamp') return 'warning';
    return CATEGORY_ICON[episode.category] ?? 'check';
  }

  function title(episode: Episode): string {
    if (episode.kind === 'gap') return t('epGap');
    if (episode.kind === 'hold')
      return t('epHold', {
        reason: episode.holdReason ? tc('holdWhy_', episode.holdReason) : '–',
      });
    if (episode.group === 'start') return t('epStart');
    if (episode.group === 'keep') return t('epKeep');
    return tc('reason_', episode.reason);
  }

  const OBVIOUS = ['start_ramp', 'cycling_floor', 'deadband', 'rounding', 'dwell', 'override'];

  function note(episode: Episode): string | null {
    if (episode.kind !== 'decisions') return null;
    const hidden = episode.group === 'keep' ? [] : OBVIOUS;
    const extra = episode.bindings
      .filter((binding) => !hidden.includes(binding))
      .map((binding) => tc('binding_', binding));
    return extra.length ? extra.join(' · ') : null;
  }

  function clock(ms: number): string {
    return dayOffset(ms, now) === 0
      ? formatClock(ms, settings.language)
      : formatDateTime(ms, settings.language, now);
  }

  function span(episode: Episode): string {
    if (episode.ongoing) return t('epSince', { time: clock(episode.from) });
    if (episode.to - episode.from <= 60_000) return clock(episode.from);
    return `${clock(episode.from)}–${formatClock(episode.to, settings.language)}`;
  }

  function setpoint(episode: Episode): string {
    if (episode.kind !== 'decisions') return '';
    if (episode.setpointFirst === null) return t('epNothingSent');
    if (episode.setpointFirst === episode.setpointLast && episode.changes === 0)
      return `${episode.setpointFirst} °C`;
    return `${episode.setpointFirst} → ${episode.setpointLast} °C`;
  }

  const contains = (episode: Episode, ms: number | null) =>
    ms !== null && episode.kind === 'decisions' && ms >= episode.from && ms < episode.to;

  const link = (ms: number) =>
    buildHash('setpoint', [], { at: new Date(ms).toISOString(), range: String(range) });
</script>

<div class="decision-view" {@attach measure}>
  <Segmented
    options={viewOptions}
    value={view}
    onchange={(next) => (view = next)}
    label={t('tableTitle')}
    appearance="pill"
    class="dt-views"
  />

  {#if view === 'episodes'}
    <table class="episodes" data-testid="decision-table">
      <thead>
        <tr>
          <th scope="col">{t('colTime')}</th>
          <th scope="col">{t('colReason')}</th>
          <th scope="col" class="num">{t('colSetpoint')}</th>
          <th scope="col" class="num">{t('colDuration')}</th>
        </tr>
      </thead>
      <tbody>
        {#each shown as episode (`${episode.kind}-${episode.from}`)}
          {@const extra = note(episode)}
          <tr
            class="{episode.kind} {episode.category}"
            class:selected={contains(episode, selected)}
            data-episode={episode.group}
          >
            <th scope="row" class="time">
              {#if episode.kind === 'decisions'}
                <a href={link(episode.from)}>{span(episode)}</a>
              {:else}
                {span(episode)}
              {/if}
            </th>
            <td class="what">
              <div class="what-inner">
                <span class="badge" aria-hidden="true"><Icon name={icon(episode)} size={16} /></span
                >
                <span class="text">
                  <span class="name">{title(episode)}</span>
                  {#if extra || episode.versionFrom !== null || episode.changes > 1}
                    <span class="sub">
                      {#if episode.versionFrom !== null}
                        <span class="tag"
                          ><Icon name="settings" size={12} />{t('epVersion', {
                            from: episode.versionFrom,
                            to: episode.configVersion ?? '–',
                          })}</span
                        >
                      {/if}
                      {#if episode.changes > 1}
                        <span>{t('epChanges', { n: episode.changes })}</span>
                      {/if}
                      {#if extra}<span>{extra}</span>{/if}
                    </span>
                  {/if}
                </span>
              </div>
            </td>
            <td class="num setpoint">{setpoint(episode)}</td>
            <td class="num duration">{formatDuration((episode.to - episode.from) / 1000)}</td>
          </tr>
        {:else}
          <tr><td colspan="4" class="muted">{t('decisionsEmpty')}</td></tr>
        {/each}
      </tbody>
    </table>
    {#if newest.length > rowsShown}
      <Button
        class="dt-more"
        aria-expanded={expanded}
        onclick={() => (expanded = !expanded)}
        data-testid="episodes-more"
      >
        {expanded ? t('showFewer') : t('showAllEpisodes', { n: newest.length })}
      </Button>
    {/if}
  {:else}
    <table class="ticks" data-testid="decision-table">
      <thead>
        <tr>
          <th scope="col">{t('colTime')}</th>
          <th scope="col">{t('colReason')}</th>
          <th scope="col" class="opt">{t('colBinding')}</th>
          <th scope="col" class="num">{t('colSetpoint')}</th>
          <th scope="col" class="num opt">{t('colConfig')}</th>
        </tr>
      </thead>
      <tbody>
        {#each ticks as decision (decision.at)}
          {@const at = Date.parse(decision.at)}
          <tr class:selected={selected !== null && Math.abs(at - selected) < 30_000}>
            <th scope="row" class="time"><a href={link(at)}>{clock(at)}</a></th>
            <td>{tc('reason_', decision.reason)}</td>
            <td class="opt"
              >{decision.record.binding ? tc('binding_', decision.record.binding) : '–'}</td
            >
            <td class="num">{decision.setpoint ?? '–'}</td>
            <td class="num opt">{decision.config_version ?? '–'}</td>
          </tr>
        {:else}
          <tr><td colspan="5" class="muted">{t('decisionsEmpty')}</td></tr>
        {/each}
      </tbody>
    </table>
    <p class="caption">{t('everyHint', { n: ticks.length })}</p>
  {/if}
</div>

<style>
  .decision-view {
    display: grid;
    gap: var(--space-2);
    min-width: 0;
  }
  :global(.dt-views) {
    justify-self: start;
  }
  :global(.dt-more) {
    font: inherit;
    font-size: var(--fs-caption);
    padding: 0.3rem 0.7rem;
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }
  :global(.dt-more) {
    justify-self: start;
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  th,
  td {
    text-align: left;
    padding: 0.45rem var(--space-2) 0.45rem 0;
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }
  thead th {
    font-size: var(--fs-caption);
    color: var(--muted);
    font-weight: var(--fw-semibold);
  }
  .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  tbody tr {
    position: relative;
  }
  .time a::after {
    content: '';
    position: absolute;
    inset: 0;
  }
  .time {
    font-weight: var(--fw-regular);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .what-inner {
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }
  .badge {
    flex: none;
    display: inline-grid;
    place-items: center;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 50%;
    color: var(--status-ok);
    background: var(--status-ok-bg);
  }
  .limited .badge {
    color: var(--status-limited);
    background: var(--status-limited-bg);
  }
  .frozen .badge {
    color: var(--status-frozen);
    background: var(--status-frozen-bg);
  }
  .stopped .badge {
    color: var(--status-stopped);
    background: var(--status-stopped-bg);
  }
  .manual .badge {
    color: var(--status-manual);
    background: var(--status-manual-bg);
  }
  .gap .badge {
    color: var(--status-unknown);
    background: var(--status-unknown-bg);
  }
  .text {
    display: grid;
    min-width: 0;
  }
  .name {
    font-weight: var(--fw-semibold);
  }
  .sub {
    display: flex;
    flex-wrap: wrap;
    gap: 0 0.6rem;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .tag {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
  }
  .gap .name,
  .gap .time {
    color: var(--muted);
  }
  .duration {
    color: var(--muted);
  }
  tr.selected th,
  tr.selected td {
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .caption {
    margin: 0;
    font-size: var(--fs-caption);
    color: var(--muted);
  }

  @container main (max-width: 40rem) {
    .episodes thead {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
    }
    .episodes tr {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas: 'what setpoint' 'time duration';
      gap: 0.1rem var(--space-3);
      padding: 0.45rem 0;
      border-bottom: 1px solid var(--border);
    }
    .episodes th,
    .episodes td {
      padding: 0;
      border: none;
    }
    .episodes .what {
      grid-area: what;
    }
    .episodes .setpoint {
      grid-area: setpoint;
    }
    .episodes .time {
      grid-area: time;
      padding-left: 2.35rem;
      font-size: var(--fs-caption);
    }
    .episodes .duration {
      grid-area: duration;
      font-size: var(--fs-caption);
    }
    .episodes td[colspan] {
      grid-column: 1 / -1;
    }
    .opt {
      display: none;
    }
    .ticks th,
    .ticks td {
      height: var(--tap);
    }
  }
</style>
