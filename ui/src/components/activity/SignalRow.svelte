<!--
  SignalRow: one signal as a compact line (freshness mark, friendly name, value). Expanding it
  shows the technical fields and, on demand, the last hour as a sparkline. A held on-change
  sensor shows when it last proved it was alive instead of looking like a fault.

  Props: id, signal, all (every signal, to resolve alive_by), receivedAt, now (ms).
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { fetchHistory } from '$lib/core/api';
  import { clockNow, formatAge, formatNumber, effectiveAge } from '$lib/core/format';
  import { freshness, humanizeId, proofAge, shortId, valueLabelKey } from '$lib/core/signalView';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type { Signal } from '$lib/core/types';
  import Sparkline from '$components/charts/Sparkline.svelte';
  import Icon from '$ui/Icon.svelte';

  interface Props {
    id: string;
    signal: Signal;
    all: Record<string, Signal>;
    receivedAt: number;
    now: number;
    open?: boolean;
  }

  let { id, signal, all, receivedAt, now, open = false }: Props = $props();

  let expanded = $derived(open);
  let points = $state<[number, number][] | null>(null);
  let historyState = $state<'idle' | 'loading' | 'none' | 'failed'>('idle');

  const fresh = $derived(freshness(signal));
  const name = $derived(tOpt(`sig_${shortId(id)}`) ?? humanizeId(id));
  const age = $derived(effectiveAge(signal.age, receivedAt, now));
  const proof = $derived(proofAge(signal, all, receivedAt, now));
  const numeric = $derived(typeof signal.value === 'number');
  const display = $derived.by(() => {
    const { value, label, unit } = signal;
    if (value === null || value === undefined) return '–';
    if (label) return tOpt(valueLabelKey(label)) ?? label;
    if (typeof value === 'number') {
      const text = formatNumber(value, Number.isInteger(value) ? 0 : 1, settings.language);
      return unit ? `${text} ${unit}` : text;
    }
    if (typeof value === 'boolean') return value ? t('yes') : t('no');
    return tOpt(valueLabelKey(String(value))) ?? String(value);
  });
  const caption = $derived(
    fresh === 'stale'
      ? t('signalStale', { age: formatAge(age) })
      : fresh === 'held'
        ? t('signalHeld', { age: formatAge(proof) })
        : '',
  );

  $effect(() => {
    if (!expanded || !numeric || historyState !== 'idle') return;
    historyState = 'loading';
    const controller = new AbortController();
    const to = new Date(clockNow());
    fetchHistory([id], controller.signal, {
      from: new Date(to.getTime() - 3_600_000),
      to,
      step: 60,
    })
      .then((history) => {
        const series = history.series[id];
        const found = (series?.points ?? [])
          .filter((p): p is [string, number] => typeof p[1] === 'number')
          .map((p): [number, number] => [Date.parse(p[0]), p[1]]);
        points = found.length > 1 ? found : null;
        historyState = found.length > 1 ? 'idle' : 'none';
      })
      .catch(() => {
        if (!controller.signal.aborted) historyState = 'failed';
      });
    return () => controller.abort();
  });
</script>

<li class="signal state-{fresh}" data-state={fresh} data-testid="signal-row">
  <Button
    variant="bare"
    class="sr-head"
    aria-expanded={expanded}
    onclick={() => (expanded = !expanded)}
  >
    <span class="mark">
      {#if fresh === 'stale'}
        <Icon name="warning" size={14} label={t('signalStateStale')} />
      {:else if fresh === 'held'}
        <Icon name="pause" size={14} label={t('signalStateHeld')} />
      {:else}
        <Icon name="check" size={14} label={t('signalStateFresh')} />
      {/if}
    </span>
    <span class="name">{name}<span class="raw mono" data-testid="signal-raw-id">{id}</span></span>
    <span class="value num">{display}</span>
    {#if caption}<span class="caption note">{caption}</span>{/if}
  </Button>
  {#if expanded}
    <div class="more">
      <dl>
        <div>
          <dt>{t('colId')}</dt>
          <dd class="mono">{id}</dd>
        </div>
        <div>
          <dt>{t('colAge')}</dt>
          <dd>{formatAge(age)}</dd>
        </div>
        <div>
          <dt>{t('colHeld')}</dt>
          <dd>{formatAge(signal.held)}</dd>
        </div>
        <div>
          <dt>{t('colMaxAge')}</dt>
          <dd>{formatAge(signal.max_age)}</dd>
        </div>
        <div>
          <dt>{t('colAliveBy')}</dt>
          <dd title={signal.alive_by ?? undefined}>
            {signal.alive_by
              ? (tOpt(`sig_${shortId(signal.alive_by)}`) ?? humanizeId(signal.alive_by))
              : '–'}
          </dd>
        </div>
        <div>
          <dt>{t('colFresh')}</dt>
          <dd>{signal.fresh ? t('yes') : t('no')}</dd>
        </div>
        <div>
          <dt>{t('colSource')}</dt>
          <dd>{signal.source}{signal.retained ? ` · ${t('colRetained')}` : ''}</dd>
        </div>
        {#if signal.source_unit}
          <div>
            <dt>{t('colSourceUnit')}</dt>
            <dd data-testid="signal-source-unit">
              {t('signalConverted', { unit: signal.source_unit })}
            </dd>
          </div>
        {/if}
        {#if signal.reason}
          <div class="wide">
            <dt>{t('colReason')}</dt>
            <dd data-testid="signal-reason">{signal.reason}</dd>
          </div>
        {/if}
      </dl>
      {#if numeric}
        {#if points}
          <Sparkline
            {points}
            label={name}
            unit={signal.unit ?? ''}
            step={signal.max_age !== null && signal.max_age !== undefined && signal.max_age >= 3600}
            minMax
          />
        {:else if historyState === 'loading'}
          <p class="caption">{t('loading')}</p>
        {:else if historyState === 'none'}
          <p class="caption">{t('signalNoHistory')}</p>
        {:else if historyState === 'failed'}
          <p class="caption">{t('signalHistoryFailed')}</p>
        {/if}
      {/if}
    </div>
  {/if}
</li>

<style>
  .signal {
    border-bottom: 1px solid var(--border);
  }
  .signal:last-child {
    border-bottom: none;
  }
  :global(.sr-head) {
    all: unset;
    box-sizing: border-box;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    column-gap: var(--space-2);
    align-items: center;
    width: 100%;
    min-height: 2rem;
    padding: 2px 0;
    cursor: pointer;
  }
  @media (--narrow), (pointer: coarse) {
    :global(.sr-head) {
      min-height: var(--tap);
    }
  }
  :global(.sr-head):focus-visible {
    outline: 2px solid var(--accent, currentColor);
    outline-offset: 2px;
    border-radius: var(--radius-s);
  }
  .mark {
    display: inline-flex;
    color: var(--status-ok);
  }
  .state-held .mark {
    color: var(--status-manual);
  }
  .state-stale .mark {
    color: var(--status-limited);
  }
  .name {
    overflow-wrap: anywhere;
  }
  .raw {
    display: none;
    color: var(--muted);
    line-height: 1.2;
  }
  @media (--wide) and (pointer: fine) {
    .raw {
      display: block;
    }
  }
  .value {
    font-weight: var(--fw-semibold);
    text-align: right;
  }
  .note {
    grid-column: 2 / -1;
    color: var(--muted);
  }
  .state-stale .note {
    color: var(--status-limited);
  }
  .more {
    padding: 0 0 var(--space-3) calc(14px + var(--space-2));
    display: grid;
    gap: var(--space-2);
  }
  dl {
    margin: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
    gap: var(--space-1) var(--space-4);
  }
  dt {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .wide {
    grid-column: 1 / -1;
  }
  dd {
    margin: 0;
    font-size: var(--fs-body);
    overflow-wrap: anywhere;
  }
  .mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: var(--fs-caption);
  }
  @container sigcard (min-width: 40rem) {
    :global(.sr-head) {
      grid-template-columns: auto 18rem 10rem minmax(0, 1fr);
    }
    .note {
      grid-column: auto;
    }
    .value {
      text-align: left;
    }
  }
</style>
