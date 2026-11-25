<!--
  PreviewDialog: review of a draft before applying. The changes as pictures (DiffTable), the
  effect on the current decision (setpoint now → with the changes, both calculations behind a
  disclosure), the replay of the last 24 h as recorded vs candidate setpoint with the
  difference shaded, the identity-check result, the replay's limitations, warnings to
  acknowledge, a comment and Apply. Full-screen sheet on phones (Modal).
-->
<script lang="ts">
  import Checkbox from '$ui/Checkbox.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Button from '$ui/Button.svelte';
  import { untrack } from 'svelte';
  import type { DiffEntry } from '$lib/core/draft.svelte';
  import { formatDelta } from '$lib/core/fieldFormat';
  import { formatClock, formatNumber } from '$lib/core/format';
  import { issueText } from '$lib/settings/issues';
  import { settings, t, tOpt } from '$lib/core/settings.svelte';
  import type {
    ConfigSchema,
    Decision,
    DecisionRecord,
    PreviewResult,
    ValidationIssue,
  } from '$lib/core/types';
  import { limitationKind, replayLines } from '$lib/settings/replay';
  import Details from '$ui/Details.svelte';
  import DiffTable from './DiffTable.svelte';
  import Icon from '$ui/Icon.svelte';
  import Modal from '$ui/Modal.svelte';
  import TimeChart, { type PanelSpec } from '$components/charts/TimeChart.svelte';
  import Waterfall from '$components/setpoint/Waterfall.svelte';
  import Why from '$ui/Why.svelte';

  interface Props {
    diff: DiffEntry[];
    schema: ConfigSchema | null;
    result: PreviewResult | null;
    loading: boolean;
    error: 'missing' | 'forbidden' | 'failed' | null;
    admin: boolean | null;
    applying?: boolean;
    applyError?: string | null;
    stale?: boolean;
    defaultComment?: string;
    onapply: (comment: string, acknowledge: string[]) => void;
    onrebase?: () => void;
    onclose: () => void;
  }

  let {
    diff,
    schema,
    result,
    loading,
    error,
    admin,
    applying = false,
    applyError = null,
    stale = false,
    defaultComment = '',
    onapply,
    onrebase,
    onclose,
  }: Props = $props();

  const locale = $derived(settings.language);
  let comment = $state(untrack(() => defaultComment));
  let acknowledged = $state<string[]>([]);

  const errors = $derived(result?.errors ?? []);
  const warnings = $derived(result?.warnings ?? []);
  const warningCodes = $derived([...new Set(warnings.map((w) => w.code))]);
  const unacknowledged = $derived(warningCodes.filter((c) => !acknowledged.includes(c)));
  const blockedReason = $derived(
    admin === false
      ? 'previewNotAdmin'
      : loading || result === null
        ? 'previewLoading'
        : errors.length > 0
          ? 'previewHasErrors'
          : unacknowledged.length > 0
            ? 'previewNeedsAck'
            : null,
  );
  const canApply = $derived(blockedReason === null && !applying);
  const fmt = (v: number, digits = 1) => formatNumber(v, digits, locale).replace('-', '−');
  const signed = (v: number) => formatDelta(0, v, locale) ?? '0';
  const describe = (issue: ValidationIssue) =>
    issueText(issue, issue.field ? schema?.fields[issue.field] : undefined, tOpt);
  const fieldName = (field: string | null) =>
    field === null ? null : (tOpt(`cfg.${field}.label`) ?? field);

  function asDecision(record: DecisionRecord): Decision {
    return {
      at: record.at.wall,
      controller: record.controller,
      mode: record.mode,
      ladder: record.ladder,
      reason: record.reason,
      setpoint: record.setpoint,
      note: record.note,
      arbiter: [],
      commands: [],
      config_version: null,
      record,
    };
  }

  const now = $derived(result?.now ?? null);
  const nowDelta = $derived.by(() => {
    if (!now) return null;
    const a = now.current.setpoint;
    const b = now.candidate.setpoint;
    return typeof a === 'number' && typeof b === 'number' ? b - a : null;
  });
  const openLoop = $derived(result?.open_loop_run ?? null);
  const hours = $derived(
    openLoop ? Math.round((Date.parse(openLoop.to) - Date.parse(openLoop.from)) / 3_600_000) : 24,
  );
  const replay = $derived(openLoop ? replayLines(openLoop) : null);
  const panels = $derived.by<PanelSpec[]>(() => {
    if (!replay) return [];
    return [
      {
        id: 'setpoint',
        unit: '°C',
        snap: 1,
        digits: 0,
        height: 190,
        bands: [
          {
            id: 'difference',
            label: t('previewDifference'),
            color: 'var(--accent)',
            upper: replay.upper,
            lower: replay.lower,
            opacity: 0.36,
          },
        ],
        lines: [
          {
            id: 'recorded',
            label: t('previewRecorded'),
            color: 'var(--series-preround)',
            points: replay.recorded,
            step: true,
            width: 2,
            digits: 0,
          },
          {
            id: 'candidate',
            label: t('previewCandidate'),
            color: 'var(--accent)',
            points: replay.candidate,
            step: true,
            width: 2,
            digits: 0,
          },
        ],
      },
    ];
  });
  const replaySummary = $derived(
    openLoop && replay
      ? t('previewReplaySummary', {
          hours,
          share: Math.round(replay.differs * 100),
          mean: signed(openLoop.summary.mean_diff_k),
          min: signed(openLoop.summary.min_diff_k),
          max: signed(openLoop.summary.max_diff_k),
        })
      : '',
  );
  const budgetShare = $derived(
    openLoop && openLoop.summary.budget > 0
      ? Math.min(openLoop.summary.writes_per_day / openLoop.summary.budget, 1)
      : 0,
  );
  const limitationText = (text: string) => {
    const kind = limitationKind(text);
    return kind === 'other' ? text : t(`previewLimit_${kind}`);
  };

  const comfort = $derived.by(() => {
    if (diff.length !== 1) return null;
    const entry = diff[0];
    if (!entry || entry.field !== 'control_comfort_c') return null;
    if (typeof entry.from !== 'number' || typeof entry.to !== 'number') return null;
    const delta = entry.to - entry.from;
    const direction =
      delta > 0
        ? delta > 0.5
          ? 'warmer'
          : 'slightlyWarmer'
        : delta > -0.5
          ? 'slightlyCooler'
          : 'cooler';
    const temp = (v: number) =>
      new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(
        v,
      );
    const headline = t(`previewComfort_${direction}` as 'previewComfort_warmer', {
      from: temp(entry.from),
      to: temp(entry.to),
    });
    let water: string | null = null;
    if (openLoop) {
      const mean = openLoop.summary.mean_diff_k;
      water =
        Math.abs(mean) < 0.05
          ? t('previewComfortWater_same', { hours })
          : t(mean > 0 ? 'previewComfortWater_up' : 'previewComfortWater_down', {
              hours,
              mean: fmt(Math.abs(mean)),
            });
    } else if (nowDelta !== null) {
      water =
        nowDelta === 0
          ? t('previewComfortNow_same')
          : t('previewComfortNow_change', { delta: signed(nowDelta) });
    }
    return { headline, water };
  });

  function toggle(code: string, on: boolean): void {
    acknowledged = on ? [...acknowledged, code] : acknowledged.filter((c) => c !== code);
  }
</script>

{#snippet changesSection()}
  <section aria-labelledby="pv-changes">
    <h3 id="pv-changes">{t('previewChanges', { n: diff.length })}</h3>
    <DiffTable entries={diff} {schema} />
  </section>
{/snippet}
{#snippet effectSections()}
  {#if now}
    <section aria-labelledby="pv-now" data-testid="preview-now">
      <h3 id="pv-now">{t('previewNow')}</h3>
      <div class="now-row">
        <div class="setpoint">
          <span class="cap">{t('previewCurrent')}</span>
          <span class="big old"
            >{now.current.setpoint ?? '–'}<span class="unit">&#8239;°C</span></span
          >
        </div>
        <Icon name="arrowRight" size={22} />
        <div class="setpoint">
          <span class="cap">{t('previewCandidate')}</span>
          <span class="big new"
            >{now.candidate.setpoint ?? '–'}<span class="unit">&#8239;°C</span></span
          >
        </div>
        <span
          class="delta-pill"
          class:zero={nowDelta === 0 || nowDelta === null}
          data-testid="preview-delta"
        >
          {nowDelta === null
            ? t('previewDeltaUnknown')
            : nowDelta === 0
              ? t('previewDeltaNone')
              : t('previewDeltaK', { delta: signed(nowDelta) })}
        </span>
      </div>
      <p class="caption">{t('previewNowCaption')}</p>
      <Details
        summary={t('previewCompare')}
        icon="chart"
        id="preview.compare"
        testid="preview-compare"
      >
        <div class="pair">
          <div>
            <h4>{t('previewCurrent')}</h4>
            <Waterfall decision={asDecision(now.current)} compact />
          </div>
          <div>
            <h4>{t('previewCandidate')}</h4>
            <Waterfall decision={asDecision(now.candidate)} compact />
          </div>
        </div>
      </Details>
    </section>
  {/if}

  {#if openLoop && replay}
    <section aria-labelledby="pv-openloop" data-testid="preview-openloop">
      <div class="openloop-head">
        <h3 id="pv-openloop">{t('previewLookBack', { hours })}</h3>
        <span class="open-loop">
          {t('previewOpenLoopShort')}
          <Why title={t('previewOpenLoopShort')} testid="open-loop-why">
            <p>{t('previewOpenLoop')}</p>
          </Why>
        </span>
      </div>
      <p
        class="identity"
        class:ok={openLoop.identity_ok}
        data-testid="preview-identity"
        data-ok={openLoop.identity_ok}
      >
        <Icon name={openLoop.identity_ok ? 'check' : 'warning'} size={18} />
        {#if openLoop.identity_ok}
          {openLoop.identity_ticks > 0
            ? t('previewIdentityOk', { n: openLoop.identity_ticks })
            : t('previewIdentityNone')}
        {:else}
          <span>
            <strong>{t('previewIdentityBad')}</strong>
            {t('previewIdentityDetail', {
              n: openLoop.identity_mismatches,
              of: openLoop.identity_ticks,
              at: openLoop.identity_first_mismatch
                ? formatClock(openLoop.identity_first_mismatch, locale)
                : '–',
            })}
          </span>
        {/if}
      </p>
      <TimeChart
        from={Date.parse(openLoop.from)}
        to={Date.parse(openLoop.to)}
        {panels}
        height={190}
        digits={0}
        title={t('previewLookBack', { hours })}
        summary={replaySummary}
      />
      <div class="stats">
        <div class="stat">
          <span class="cap">{t('previewMeanDiff')}</span>
          <strong>{signed(openLoop.summary.mean_diff_k)}&#8239;K</strong>
        </div>
        <div class="stat">
          <span class="cap">{t('previewMinMax')}</span>
          <strong
            >{signed(openLoop.summary.min_diff_k)} … {signed(
              openLoop.summary.max_diff_k,
            )}&#8239;K</strong
          >
        </div>
        <div class="stat">
          <span class="cap">{t('previewDiffers')}</span>
          <strong>{Math.round(replay.differs * 100)}&#8239;%</strong>
        </div>
        <div class="stat wide">
          <span class="cap">{t('previewWrites')}</span>
          <strong
            >{t('previewWritesValue', {
              n: fmt(openLoop.summary.writes_per_day),
              budget: openLoop.summary.budget,
            })}</strong
          >
          <span
            class="budget"
            role="img"
            aria-label={t('previewBudgetLabel', {
              share: Math.round(budgetShare * 100),
            })}
            ><span style:width="{Math.max(budgetShare * 100, 1)}%" class:high={budgetShare > 0.8}
            ></span></span
          >
          <span class="cap"
            >{t('previewWritesBefore', {
              n: openLoop.summary.changes_recorded,
              m: openLoop.summary.changes_candidate,
            })}</span
          >
        </div>
        {#if openLoop.summary.share_safety_clamped > 0}
          <div class="stat">
            <span class="cap">{t('previewClamped')}</span>
            <strong>{Math.round(openLoop.summary.share_safety_clamped * 100)}&#8239;%</strong>
          </div>
        {/if}
      </div>
      {#if openLoop.limitations.length > 0 || openLoop.skipped > 0}
        <ul class="limits" data-testid="preview-limitations">
          {#each openLoop.limitations as text (text)}
            <li><Icon name="info" size={16} />{limitationText(text)}</li>
          {/each}
          {#if openLoop.skipped > 0}
            <li>
              <Icon name="info" size={16} />{t('previewSkipped', {
                n: openLoop.skipped,
                of: openLoop.ticks,
              })}
            </li>
          {/if}
        </ul>
      {/if}
    </section>
  {/if}
{/snippet}

<Modal title={t('previewTitle')} {onclose} testid="preview-dialog">
  {#if comfort}
    <section class="comfort" data-testid="preview-comfort" aria-labelledby="pv-comfort">
      <h3 id="pv-comfort" class="visually-hidden">{t('previewChanges', { n: 1 })}</h3>
      <p class="comfort-line">{comfort.headline}</p>
      {#if comfort.water}<p class="comfort-water" data-testid="preview-comfort-water">
          {comfort.water}
          {#if openLoop && !openLoop.identity_ok}<span
              class="muted"
              data-testid="preview-comfort-caveat">{t('previewIdentityBad')}</span
            >{/if}
        </p>{/if}
    </section>
  {:else}
    {@render changesSection()}
  {/if}

  {#if loading}
    <p class="notice info" role="status"><Icon name="clock" size={18} />{t('previewLoading')}</p>
  {:else if error === 'missing'}
    <p class="notice" data-testid="preview-missing">
      <Icon name="info" size={18} />{t('previewMissing')}
    </p>
  {:else if error === 'forbidden'}
    <p class="notice" data-testid="preview-forbidden">
      <Icon name="lock" size={18} />{t('previewForbidden')}
    </p>
  {:else if error === 'failed'}
    <p class="notice error" role="alert"><Icon name="critical" size={18} />{t('previewFailed')}</p>
  {/if}

  {#if errors.length > 0}
    <section class="problems" data-testid="preview-errors" aria-labelledby="pv-errors">
      <h3 id="pv-errors"><Icon name="critical" size={18} />{t('previewErrors')}</h3>
      <ul>
        {#each errors as issue, i (i)}
          <li class="error">
            {#if fieldName(issue.field)}<strong>{fieldName(issue.field)}</strong>:
            {/if}{describe(issue)}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if comfort}
    <Details
      summary={t('previewDetails')}
      icon="chart"
      id="preview.comfort"
      testid="preview-details"
    >
      {@render changesSection()}
      {@render effectSections()}
    </Details>
  {:else}
    {@render effectSections()}
  {/if}

  {#if warnings.length > 0}
    <section class="problems warnings" data-testid="preview-warnings" aria-labelledby="pv-warnings">
      <h3 id="pv-warnings"><Icon name="warning" size={18} />{t('previewWarnings')}</h3>
      {#each warningCodes as code (code)}
        <Checkbox
          class="preview-ack"
          checked={acknowledged.includes(code)}
          onchange={(e) => toggle(code, e.currentTarget.checked)}
          data-testid="ack-{code}"
        >
          {#each warnings.filter((w) => w.code === code) as issue, i (i)}
            {#if fieldName(issue.field)}<strong>{fieldName(issue.field)}</strong>:
            {/if}{describe(issue)}
          {/each}
          <span class="muted">{t('previewAcknowledgeShort')}</span>
        </Checkbox>
      {/each}
    </section>
  {/if}

  <label class="comment">
    <span class="cap">{t('previewComment')}</span>
    <TextInput type="text" maxlength={200} bind:value={comment} data-testid="preview-comment" />
  </label>

  {#if stale}
    <p class="notice" data-testid="preview-stale">
      <Icon name="warning" size={18} />
      <span>{t('previewStale')}</span>
      {#if onrebase}<Button onclick={onrebase}>{t('previewRebase')}</Button>{/if}
    </p>
  {/if}
  {#if applyError}<p class="notice error" role="alert">
      <Icon name="critical" size={18} />{applyError}
    </p>{/if}

  {#snippet footer()}
    {#if blockedReason}
      <span class="muted why" data-testid="preview-blocked"
        >{t(blockedReason as 'previewNeedsAck')}</span
      >
    {/if}
    <Button onclick={onclose}>{t('cancel')}</Button>
    <Button
      type="button"
      variant="primary"
      disabled={!canApply}
      onclick={() => onapply(comment.trim(), acknowledged)}
      data-testid="preview-apply"
    >
      {applying ? t('previewApplying') : t('previewApply')}
    </Button>
  {/snippet}
</Modal>

<style>
  .comfort-line {
    margin: 0;
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
  }
  .comfort-water {
    margin: var(--space-1) 0 var(--space-3);
  }
  section + section,
  section + .comment,
  .notice + section {
    margin-top: var(--space-5);
  }
  h3 {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0 0 var(--space-2);
    font-size: var(--fs-emph);
  }
  h4 {
    margin: 0 0 var(--space-1);
    font-size: var(--fs-body);
    color: var(--muted);
  }
  .cap {
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .now-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-2) var(--space-4);
  }
  .now-row > :global(.icon) {
    color: var(--muted);
    margin-bottom: 0.6rem;
  }
  .setpoint {
    display: flex;
    flex-direction: column;
  }
  .big {
    font-size: var(--fs-display-4);
    font-weight: var(--fw-bold);
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  .big .unit {
    font-size: var(--fs-emph);
  }
  .big.old {
    color: var(--muted);
  }
  .big.new {
    color: var(--accent);
  }
  .delta-pill {
    align-self: center;
    padding: 0.2rem 0.7rem;
    border-radius: var(--radius-pill);
    background: var(--status-manual-bg);
    color: var(--status-manual);
    font-weight: var(--fw-bold);
  }
  .delta-pill.zero {
    background: var(--surface-2);
    color: var(--muted);
  }
  .caption {
    margin: var(--space-1) 0 0;
  }
  .pair {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }
  .openloop-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }
  .openloop-head h3 {
    margin: 0;
  }
  .open-loop {
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    padding-left: 0.6rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    color: var(--muted);
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
  }
  .identity {
    display: flex;
    align-items: flex-start;
    gap: 0.4rem;
    margin: 0 0 var(--space-2);
    padding: 0.4rem 0.6rem;
    border-radius: var(--radius-sm);
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .identity.ok {
    background: var(--status-ok-bg);
    color: var(--status-ok);
  }
  .identity :global(.icon) {
    flex: none;
    margin-top: 1px;
  }
  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
    gap: var(--space-3) var(--space-4);
    margin-top: var(--space-3);
  }
  .stat {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    min-width: 0;
  }
  .stat strong {
    font-size: var(--fs-emph);
    font-variant-numeric: tabular-nums;
  }
  .stat.wide {
    grid-column: span 2;
  }
  .budget {
    display: block;
    height: 6px;
    border-radius: var(--radius-xs);
    background: var(--surface-2);
    border: 1px solid var(--border);
    overflow: hidden;
    margin: 0.2rem 0;
  }
  .budget span {
    display: block;
    height: 100%;
    background: var(--cat-normal);
  }
  .budget span.high {
    background: var(--cat-limited);
  }
  .limits {
    list-style: none;
    margin: var(--space-3) 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .limits li {
    display: flex;
    align-items: flex-start;
    gap: 0.35rem;
  }
  .limits :global(.icon) {
    flex: none;
    margin-top: 1px;
  }
  .problems ul {
    margin: 0;
    padding-left: 1.2rem;
  }
  .problems h3 :global(.icon) {
    color: var(--status-stopped);
  }
  .warnings h3 :global(.icon) {
    color: var(--status-limited);
  }
  .error {
    color: var(--err-text);
  }
  .notice {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.6rem;
    margin: var(--space-3) 0 0;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm);
    background: var(--warn-bg);
    color: var(--warn-text);
  }
  .notice.info {
    background: var(--surface-2);
    color: var(--muted);
  }
  .notice.error {
    background: var(--err-bg);
    color: var(--err-text);
  }
  :global(.preview-ack) {
    display: flex;
    gap: 0.6rem;
    align-items: flex-start;
    min-height: var(--tap);
    padding: var(--space-2) 0.6rem;
    border-radius: var(--radius-sm);
    background: var(--warn-bg);
    color: var(--warn-text);
  }
  :global(.preview-ack + .preview-ack) {
    margin-top: var(--space-1);
  }
  .comment {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .why {
    flex: 1;
    align-self: center;
    font-size: var(--fs-caption);
  }
  @media (--narrow) {
    .pair {
      grid-template-columns: minmax(0, 1fr);
    }
    .big {
      font-size: var(--fs-display-2);
    }
  }
</style>
