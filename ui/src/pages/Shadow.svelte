<!--
  Shadow: "Compare with the other controller" (System → Compare, `#/system/shadow`). What
  ovenbird would send against the pump's own water target over a chosen period: summary figures,
  the two lines with the difference shaded and the writer marked, a per-day table and the
  divergent episodes with ovenbird's reason. The 24 h view follows new decisions (at most once a
  minute); the other periods load once.
-->
<script lang="ts">
  import TextInput from '$ui/TextInput.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import StatChip from '$ui/StatChip.svelte';
  import DayTable from '$components/shadow/DayTable.svelte';
  import EpisodeList from '$components/shadow/EpisodeList.svelte';
  import ShadowChart from '$components/shadow/ShadowChart.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import { formatDuration, formatNumber } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    customWindow,
    direction,
    fetchDivergence,
    RANGE_HOURS,
    SHADOW_RANGES,
    type Divergence,
    type ShadowRange,
  } from '$lib/shadow/shadow';
  import { untrack } from 'svelte';

  let { live }: { live: LiveStore; ctl: ControlStore } = $props();

  const MINUTE = 60_000;
  const HOUR = 3_600_000;
  const SIGNAL = 'main/Z1_Water_Target_Temp';

  let range = $state<ShadowRange>('24h');
  const rangeOptions = $derived(
    SHADOW_RANGES.map((kind) => ({
      value: kind,
      label: t(`shadowRange_${kind}`),
      testid: `shadow-range-${kind}`,
    })),
  );
  let customFrom = $state('');
  let customTo = $state('');
  let anchor = $state(Math.round(untrack(() => live.clock) / MINUTE) * MINUTE);
  let reload = $state(0);
  let phase = $state<'loading' | 'ok' | 'missing' | 'failed'>('loading');
  let data = $state<Divergence | null>(null);

  const lang = $derived(settings.language);
  const custom = $derived(range === 'custom' ? customWindow(customFrom, customTo) : null);
  const problem = $derived(custom && 'problem' in custom ? custom.problem : null);
  const span = $derived.by(() => {
    if (custom && 'from' in custom) return custom;
    const hours = range === 'custom' ? 24 : RANGE_HOURS[range];
    return { from: anchor - hours * HOUR, to: anchor };
  });

  function localInput(ms: number): string {
    const d = new Date(ms);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function pick(next: ShadowRange): void {
    if (next === 'custom' && range !== 'custom') {
      customFrom = localInput(span.from);
      customTo = localInput(span.to);
    }
    if (next !== 'custom') anchor = Math.round(live.clock / MINUTE) * MINUTE;
    range = next;
  }

  $effect(() => {
    void live.decisionSeq;
    untrack(() => {
      if (range !== '24h') return;
      const now = Math.round(live.clock / MINUTE) * MINUTE;
      if (now - anchor >= MINUTE) anchor = now;
    });
  });

  $effect(() => {
    if (problem !== null) return;
    void reload;
    const from = new Date(span.from);
    const to = new Date(span.to);
    const controller = new AbortController();
    if (data === null) phase = 'loading';
    fetchDivergence({ from, to }, controller.signal)
      .then((result) => {
        if (result === null) {
          phase = 'missing';
          data = null;
          return;
        }
        data = result;
        phase = 'ok';
      })
      .catch(() => {
        if (!controller.signal.aborted) phase = 'failed';
      });
    return () => controller.abort();
  });

  const num = (value: number | null | undefined, digits = 1) =>
    value === null || value === undefined ? '–' : formatNumber(value, digits, lang);
  const summary = $derived(data?.summary ?? null);
  const lean = $derived(direction(summary?.bias_k));
</script>

<section class="shadow" data-testid="shadow-page" aria-labelledby="shadow-title">
  <div class="intro">
    <h2 id="shadow-title">{t('shadowTitle')}</h2>
    <p class="muted lead">{t('shadowLead', { signal: SIGNAL })}</p>
  </div>

  <div class="range-bar" data-testid="shadow-range" data-help="system/shadow.range">
    <Segmented
      options={rangeOptions}
      value={range}
      onchange={pick}
      label={t('shadowRangeLabel')}
      wrap
    />
    {#if range === 'custom'}
      <div class="custom">
        <label>
          <span>{t('shadowFrom')}</span>
          <TextInput
            block={false}
            type="datetime-local"
            bind:value={customFrom}
            aria-invalid={problem !== null}
            data-testid="shadow-range-from"
          />
        </label>
        <label>
          <span>{t('shadowTo')}</span>
          <TextInput
            block={false}
            type="datetime-local"
            bind:value={customTo}
            aria-invalid={problem !== null}
            data-testid="shadow-range-to"
          />
        </label>
      </div>
      {#if problem !== null}
        <p class="err" role="alert" data-testid="shadow-range-error">
          {t(`shadowWindow_${problem}`)}
        </p>
      {/if}
    {/if}
  </div>

  {#if phase === 'missing'}
    <Card bare as="div" data-testid="shadow-missing">
      <EmptyState art="noData" title={t('shadowMissingTitle')} text={t('shadowMissingText')} />
    </Card>
  {:else if phase === 'failed' && data === null}
    <Card bare as="div" data-testid="shadow-failed">
      <p class="muted">{t('shadowFailed')}</p>
      <Button onclick={() => (reload += 1)}>{t('shadowRetry')}</Button>
    </Card>
  {:else if data === null}
    <p class="muted" data-testid="shadow-loading">{t('shadowLoading')}</p>
  {:else if data.summary.compared_minutes === 0}
    <Card bare as="div" data-testid="shadow-empty" data-help="system/shadow.summary">
      <EmptyState art="noData" title={t('shadowEmptyTitle')} text={t('shadowEmptyText')} />
    </Card>
  {:else if summary}
    <Card
      title={t('shadowSummaryTitle')}
      icon="chart"
      testid="shadow-summary"
      help="system/shadow.summary"
    >
      <div class="chips">
        <StatChip
          label={t('shadowChipCoverage')}
          value={num((summary.coverage ?? 0) * 100, 0)}
          unit="%"
          tone={(summary.coverage ?? 0) < 0.8 ? 'limited' : 'default'}
          caption={summary.gap_minutes
            ? t('shadowChipCoverageCaption', {
                gap: formatDuration(summary.gap_minutes * 60, lang),
              })
            : t('shadowChipCoverageFull')}
          testid="shadow-chip-coverage"
        />
        <StatChip
          label={t('shadowChipMean')}
          value={num(summary.mean_abs_k)}
          unit="K"
          testid="shadow-chip-mean"
        />
        <StatChip
          label={t('shadowChipMax')}
          value={num(summary.max_abs_k)}
          unit="K"
          tone={(summary.max_abs_k ?? 0) > data.threshold_k ? 'limited' : 'default'}
          testid="shadow-chip-max"
        />
        <StatChip
          label={t('shadowChipHoursOver', { k: num(data.threshold_k) })}
          value={summary.hours_over > 0
            ? formatDuration(summary.hours_over * 3600, lang)
            : t('shadowNone')}
          testid="shadow-chip-over"
        />
        <StatChip
          label={t('shadowChipEpisodes')}
          value={String(summary.episodes)}
          caption={summary.longest_episode_min
            ? t('shadowChipEpisodesCaption', {
                duration: formatDuration(summary.longest_episode_min * 60, lang),
              })
            : undefined}
          testid="shadow-chip-episodes"
        />
      </div>
      <p class="lean" data-testid="shadow-lean" data-direction={lean}>
        {t(`shadowLean_${lean}`, { k: num(Math.abs(summary.bias_k ?? 0)) })}
      </p>
    </Card>

    <Card title={t('shadowChartTitle')} testid="shadow-chart-card" help="system/shadow.chart">
      <ShadowChart {data} now={live.clock} />
    </Card>

    <Card title={t('shadowEpisodesTitle')} testid="shadow-episodes" help="system/shadow.episodes">
      <EpisodeList
        episodes={data.episodes}
        total={data.episodes_total}
        thresholdK={data.threshold_k}
        now={live.clock}
      />
    </Card>

    <Card title={t('shadowDaysTitle')} testid="shadow-days-card" help="system/shadow.days">
      <DayTable
        days={data.days}
        thresholdK={data.threshold_k}
        timezone={data.timezone}
        now={live.clock}
      />
    </Card>
  {/if}
</section>

<style>
  .shadow {
    display: grid;
    gap: var(--space-4);
    min-width: 0;
  }
  .intro h2 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-emph);
  }
  .lead {
    margin: 0;
    max-width: 60rem;
    overflow-wrap: anywhere;
  }
  .range-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: var(--space-2) var(--space-3);
  }
  .custom {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-3);
  }
  .custom label {
    display: grid;
    gap: 0.15rem;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .err {
    flex-basis: 100%;
    margin: 0;
    color: var(--err-text);
  }
  .chips {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(9rem, 45%), 1fr));
    gap: var(--space-3);
  }
  .lean {
    margin: var(--space-3) 0 0;
    font-weight: var(--fw-semibold);
  }
</style>
