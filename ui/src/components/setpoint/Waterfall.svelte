<!--
  Waterfall: how the issued water setpoint is built, as rows on one shared °C axis: heating curve,
  each contributing term (coloured like its band in the history chart), the sum, the safety clamp
  against the allowed range, rounding/dead band/wait time, the issued setpoint and what the pump
  has. When the decision was not sent (Shadow, pause, hold) the setpoint row reads "Would send"
  and "Pump has" follows at equal weight, also in the compact form. Hold and refuse decisions show the reason instead of bars.

  Props: decision; compact (Home and the review dialog: no zero rows, no sum, no axis).
  A11y: an ordered list with every row's label and value as text; the list carries a one-line
  summary as its accessible name.
-->
<script lang="ts">
  import { fixedBase, numberFormats } from '$lib/setpoint/explain';
  import { settings, t, tc } from '$lib/core/settings.svelte';
  import type { Decision } from '$lib/core/types';
  import {
    buildWaterfall,
    decisionSends,
    reportedTarget,
    type WaterfallRow,
  } from '$lib/setpoint/waterfall';

  let { decision, compact = false }: { decision: Decision; compact?: boolean } = $props();

  const fmt = $derived(numberFormats(settings.language));
  const sends = $derived(decisionSends(decision));
  const model = $derived(
    buildWaterfall(decision.record, compact && sends ? null : reportedTarget(decision)),
  );
  const rows = $derived(
    compact
      ? model.rows.filter(
          (row) =>
            row.kind !== 'sum' &&
            !(row.kind === 'clamp' && Math.abs(row.delta) < 1e-6) &&
            !(row.kind === 'stage' && Math.abs(row.delta) < 1e-6),
        )
      : model.rows,
  );

  const span = $derived(Math.max(model.axis.max - model.axis.min, 1));
  const pct = (value: number) => ((value - model.axis.min) / span) * 100;
  const ticks = $derived.by(() => {
    const out: number[] = [];
    const step = span > 20 ? 5 : span > 8 ? 2 : 1;
    for (let v = Math.ceil(model.axis.min / step) * step; v <= model.axis.max; v += step)
      out.push(v);
    return out;
  });

  const TERM_COLOURS: Record<string, string> = {
    room_feedback: 'var(--band-feedback)',
    plan: 'var(--band-plan)',
    start_ramp: 'var(--band-ramp)',
    cycling_floor: 'var(--band-cycling)',
    stove: 'var(--band-stove)',
  };
  const termColour = (id: string) => TERM_COLOURS[id] ?? 'var(--band-other)';

  const summary = $derived(rows.map((row) => `${label(row)} ${valueText(row)}`).join(', '));

  function left(row: WaterfallRow): number {
    return pct(Math.min(row.start, row.end));
  }
  function barWidth(row: WaterfallRow): number {
    return Math.max(Math.abs(pct(row.end) - pct(row.start)), row.kind === 'sum' ? 0 : 0.6);
  }

  function label(row: WaterfallRow): string {
    if (row.kind === 'term') return tc('term_', row.id);
    if (row.kind === 'issued' && !sends) return t('wfWouldSend');
    if (row.kind === 'curve' && fixedBase(decision.record)) return t('wf_fixed');
    return t(`wf_${row.kind}` as 'wf_curve');
  }

  function valueText(row: WaterfallRow): string {
    if (row.kind === 'term') return fmt.signed(row.delta);
    if (row.kind === 'clamp') {
      return Math.abs(row.delta) < 1e-6 ? t('wfWithinLimits') : fmt.signed(row.delta);
    }
    if (row.kind === 'stage') {
      return Math.abs(row.delta) < 1e-6 ? t('wfNoChange') : fmt.signed(row.delta);
    }
    return `${fmt.plain(row.end, row.kind === 'issued' || row.kind === 'reported' ? 0 : 1)} °C`;
  }

  function detailText(row: WaterfallRow): string | null {
    if (row.kind === 'term' && row.limited && row.raw !== null) {
      return t('wfRawApplied', { raw: fmt.signed(row.raw), applied: fmt.signed(row.delta) });
    }
    if (row.kind === 'clamp' && model.allowed) {
      const range = t('wfAllowed', {
        low: fmt.plain(model.allowed.low, 1),
        high: fmt.plain(model.allowed.high, 1),
      });
      if (Math.abs(row.delta) < 1e-6) return range;
      return `${t('wfRawApplied', { raw: `${fmt.plain(row.start, 1)} °C`, applied: `${fmt.plain(row.end, 1)} °C` })} · ${range}`;
    }
    if (row.kind === 'stage') {
      if (row.binding) return tc('binding_', row.binding);
      return Math.abs(row.delta) < 1e-6 ? null : t('wfRounded');
    }
    return null;
  }

  function tone(row: WaterfallRow): string {
    if (row.kind === 'term') return `term ${row.delta >= 0 ? 'up' : 'down'}`;
    if (row.kind === 'clamp') return Math.abs(row.delta) < 1e-6 ? 'quiet' : 'clamp';
    return row.kind;
  }
</script>

<div
  class="waterfall"
  class:compact
  class:unsent={!sends}
  data-testid="waterfall"
  data-sends={sends}
>
  {#if model.kind === 'reason'}
    <p class="reason-only" data-testid="waterfall-reason">
      {t(decision.record.ladder === 'refuse' ? 'wfRefuse' : 'wfHold')}
      <strong>{tc('reason_', decision.record.reason)}</strong>
    </p>
    {#if model.setpoint !== null}
      <p class="kept">{t('wfKept', { setpoint: model.setpoint })}</p>
    {/if}
  {:else}
    <ol class="rows" aria-label={summary}>
      {#each rows as row (row.id)}
        {@const detail = detailText(row)}
        <li
          class="row {tone(row)}"
          data-row={row.id}
          style:--term={row.kind === 'term' ? termColour(row.id) : undefined}
        >
          <span class="label">{label(row)}</span>
          <span class="track" aria-hidden="true">
            {#each ticks as tick (tick)}
              <i class="tick" style="left: {pct(tick)}%"></i>
            {/each}
            {#if (row.kind === 'clamp' || row.kind === 'sum') && model.allowed && !compact}
              <i
                class="allowed"
                style="left: {pct(model.allowed.low)}%; width: {pct(model.allowed.high) -
                  pct(model.allowed.low)}%"
              ></i>
            {/if}
            {#if row.kind === 'sum'}
              <i class="sum-mark" style="left: {pct(row.end)}%"></i>
            {:else}
              <i class="bar" style="left: {left(row)}%; width: {barWidth(row)}%"></i>
            {/if}
          </span>
          <span class="value">{valueText(row)}</span>
          {#if detail}
            <span class="detail" class:minor={!row.limited} data-detail={row.id}>{detail}</span>
          {/if}
        </li>
      {/each}
    </ol>
    {#if !compact}
      <div class="axis" aria-hidden="true">
        {#each ticks as tick (tick)}
          <span style="left: {pct(tick)}%">{tick}</span>
        {/each}
      </div>
      {#if model.collapsed.length > 0}
        <p class="muted collapsed" data-testid="waterfall-collapsed">
          {t('wfNoContribution', {
            terms: model.collapsed.map((name) => tc('term_', name)).join(', '),
          })}
        </p>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.15rem;
  }
  .row {
    display: grid;
    grid-template-columns: 11rem 1fr 6.5rem;
    grid-template-areas: 'label track value' '. detail detail';
    align-items: center;
    gap: 0 var(--space-3);
    padding: 0.3rem 0;
    border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent);
  }
  .compact .row {
    padding: 0.15rem 0;
  }
  .label {
    grid-area: label;
    font-size: var(--fs-body);
  }
  .track {
    grid-area: track;
    position: relative;
    height: 1.15rem;
    background: color-mix(in srgb, var(--border) 25%, transparent);
    border-radius: var(--radius-s);
  }
  .compact .track {
    height: 0.9rem;
  }
  .value {
    grid-area: value;
    text-align: right;
    font-weight: var(--fw-semibold);
    font-variant-numeric: tabular-nums;
    line-height: 1.25;
  }
  .detail {
    grid-area: detail;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .tick {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 1px;
    background: var(--border);
  }
  .allowed {
    position: absolute;
    top: 0;
    bottom: 0;
    background: color-mix(in srgb, var(--ok) 18%, transparent);
  }
  .bar {
    position: absolute;
    top: 15%;
    bottom: 15%;
    border-radius: var(--radius-xs);
    background: var(--accent);
  }
  .sum-mark {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 3px;
    background: var(--text);
  }
  .term .bar {
    background: var(--term);
  }
  .term .bar::after {
    content: '';
    position: absolute;
    top: 50%;
    width: 0;
    height: 0;
    border-block: 0.3rem solid transparent;
    transform: translateY(-50%);
  }
  .up .bar::after {
    right: -0.3rem;
    border-left: 0.3rem solid var(--term);
  }
  .down .bar::after {
    left: -0.3rem;
    border-right: 0.3rem solid var(--term);
  }
  .clamp .bar {
    background: var(--err-text);
  }
  .clamp .value {
    color: var(--err-text);
  }
  .stage .bar {
    background: var(--muted);
  }
  .issued .bar {
    background: var(--accent);
  }
  .issued .label,
  .issued .value {
    font-weight: var(--fw-bold);
  }
  .reported .bar {
    background: transparent;
    border: 2px solid var(--accent);
  }
  .unsent .reported .label,
  .unsent .reported .value {
    font-weight: var(--fw-bold);
  }
  .quiet .bar {
    display: none;
  }
  .axis {
    position: relative;
    height: 1.2rem;
    margin-left: 11.75rem;
    margin-right: 7.25rem;
    font-size: var(--fs-2xs);
    color: var(--muted);
  }
  .axis span {
    position: absolute;
    transform: translateX(-50%);
  }
  .collapsed,
  .reason-only,
  .kept {
    margin: var(--space-2) 0 0;
  }

  @container main (max-width: 40rem) {
    .rows {
      gap: 0;
    }
    .row {
      grid-template-columns: 1fr auto;
      grid-template-areas: 'label value' 'track track' 'detail detail';
      gap: 0 var(--space-2);
      padding: 0.1rem 0 0.2rem;
      line-height: 1.3;
    }
    .track {
      height: 0.6rem;
    }
    .label {
      font-size: var(--fs-caption);
    }
    .detail.minor,
    .collapsed {
      display: none;
    }
    .axis {
      margin: 0;
    }
  }
</style>
