<!--
  Checklist: the go-live checklist. A verdict line with the counts, then the items in two groups
  ("Before go-live", which is what ready means, and "In the first trial week", only possible once
  ovenbird controls; one group for an older service), one row per item with an
  ok/warn/fail pill (icon and word), a translated line built from the evidence, a quieter evidence
  line, a link to the page with the facts and the service's own message behind "Why?". The
  Notifications item follows the live notification verdict (as the System tile and the strip do).
  The verdict and its counts are about the items before go-live. On a phone a Done row shows its
  title only (the service text stays behind "Why?").

  Props: status (TrialStatus), fmt (TrialFormat).
  A11y: a list; the pill carries a word, never colour alone.
-->
<script lang="ts">
  import { notifyHealth } from '$lib/notify/notifyHealth.svelte';
  import { t, tc, tOpt } from '$lib/core/settings.svelte';
  import {
    checkEvidence,
    checkLine,
    checkGroups,
    checkLink,
    goLiveCounts,
    openBeforeGoLive,
    withNotifyVerdict,
    type TrialCheck,
    type CheckStatus,
    type TrialFormat,
    type TrialStatus,
  } from '$lib/trial/trial';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';
  import Why from '$ui/Why.svelte';

  let { status: served, fmt }: { status: TrialStatus; fmt: TrialFormat } = $props();

  const status = $derived(
    withNotifyVerdict(served, notifyHealth.failing, notifyHealth.verdict?.key ?? ''),
  );

  const TONE = { ok: 'good', warn: 'warn', fail: 'bad' } as const;
  const ICON = { ok: 'check', warn: 'warning', fail: 'critical' } as const;

  const open = $derived(openBeforeGoLive(status.checklist));
  const counts = $derived(goLiveCounts(status.checklist));
  const row = (check: TrialCheck) => {
    const line = checkLine(check, fmt);
    const evidence = checkEvidence(check, fmt);
    return {
      check,
      title: tc('trialCheck_', check.id),
      line: tOpt(line.key, line.params) ?? check.message,
      evidence: evidence ? (tOpt(evidence.key, evidence.params) ?? null) : null,
      href: checkLink(check.id),
    };
  };
  const groups = $derived(
    checkGroups(status.checklist).map((group) => ({ ...group, rows: group.checks.map(row) })),
  );
  const pillText = (value: CheckStatus) => t(`trialStatus_${value}`);
</script>

<p class="verdict" class:ready={status.ready} data-testid="trial-verdict">
  <Icon name={status.ready ? 'check' : 'info'} size={20} />
  <span class="main">
    {status.ready ? t('trialReady') : open === 1 ? t('trialToDoOne') : t('trialToDo', { n: open })}
  </span>
  <span class="counts muted">
    {t('trialCounts', {
      ok: counts.ok,
      warn: counts.warn,
      fail: counts.fail,
    })}
  </span>
</p>

<div data-testid="trial-checklist">
  {#each groups as group (group.phase ?? 'all')}
    {#if group.phase}
      <h3 class="group" data-testid="trial-group-{group.phase}">
        {t(`trialGroup_${group.phase}`)}
      </h3>
      {#if group.phase === 'trial'}<p class="note caption muted">{t('trialGroupTrialNote')}</p>{/if}
    {/if}
    <ul class="checks">
      {#each group.rows as row (row.check.id)}
        <li data-check={row.check.id} data-status={row.check.status}>
          <div class="text">
            <span class="head">
              <Pill tone={TONE[row.check.status]} icon={ICON[row.check.status]}
                >{pillText(row.check.status)}</Pill
              >
              <span class="title">{row.title}</span>
            </span>
            <span class="line">{row.line}</span>
            {#if row.evidence}<span class="evidence caption muted">{row.evidence}</span>{/if}
          </div>
          <div class="tools">
            {#if row.href}
              <a
                class="go"
                href={row.href}
                title={t('trialOpen')}
                aria-label="{t('trialOpen')}: {row.title}"><Icon name="chevronRight" size={18} /></a
              >
            {/if}
            {#if row.check.message}
              <Why
                title={t('trialServiceMessageLang')}
                ariaLabel="{t('trialServiceMessage')}: {row.title}"
                width="22rem"
                align="end"
              >
                <p class="raw">{row.check.message}</p>
              </Why>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/each}
</div>

<style>
  .verdict {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-2);
    margin: 0 0 var(--space-3);
    padding: 0.6rem 0.8rem;
    border-radius: var(--radius);
    background: var(--status-limited-bg);
    color: var(--status-limited);
  }
  .verdict.ready {
    background: var(--status-ok-bg);
    color: var(--status-ok);
  }
  .main {
    font-weight: var(--fw-bold);
  }
  .counts {
    font-size: var(--fs-caption);
    color: inherit;
    opacity: 0.85;
  }
  .group {
    margin: var(--space-3) 0 var(--space-1);
    font-size: var(--fs-body);
  }
  .group + .note {
    margin: 0 0 var(--space-1);
  }
  .checks {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--space-2) var(--space-3);
    align-items: start;
    padding: var(--space-2) 0;
    border-top: 1px solid var(--border);
  }
  li:first-child {
    border-top: none;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.15rem var(--space-2);
  }
  .text {
    display: grid;
    gap: 0.05rem;
    min-width: 0;
  }
  .title {
    font-weight: var(--fw-semibold);
  }
  .line {
    overflow-wrap: anywhere;
  }
  @container main (max-width: 40rem) {
    li[data-status='ok'] .line,
    li[data-status='ok'] .evidence {
      display: none;
    }
    li {
      padding: var(--space-1) 0;
    }
    .note {
      display: none;
    }
    .group {
      margin-top: var(--space-2);
    }
  }
  .tools {
    display: flex;
    align-items: center;
    gap: 0.15rem;
  }
  .go {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border-radius: var(--radius-control);
    color: var(--muted);
  }
  .go:hover {
    background: var(--surface-2);
    color: var(--text);
  }
  .raw {
    margin: 0;
    font-family: var(--font-mono);
    font-size: var(--fs-caption);
  }
</style>
