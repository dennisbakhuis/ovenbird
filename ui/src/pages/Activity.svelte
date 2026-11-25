<script lang="ts">
  import Card from '$ui/Card.svelte';
  import TextInput from '$ui/TextInput.svelte';
  import Segmented from '$ui/Segmented.svelte';
  import { DOWNLOAD_PREFIX } from '$lib/core/brand';
  import { fetchAlarms, fetchAudit, fetchCommands, isForbidden, isMissing } from '$lib/core/api';
  import AlarmList from '$components/activity/AlarmList.svelte';
  import AuditTable from '$components/activity/AuditTable.svelte';
  import CommandTable from '$components/activity/CommandTable.svelte';
  import DownloadCsv from '$components/activity/DownloadCsv.svelte';
  import EmptyState from '$ui/EmptyState.svelte';
  import HoldCard from '$components/hold/HoldCard.svelte';
  import MonitorTable from '$components/activity/MonitorTable.svelte';
  import BulletBar from '$components/charts/BulletBar.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';
  import Tabs from '$ui/Tabs.svelte';
  import Why from '$ui/Why.svelte';
  import type { ControlStore } from '$lib/core/control.svelte';
  import ActivityTimeline from '$components/activity/ActivityTimeline.svelte';
  import {
    groupCommands,
    holdsTable,
    pairJournal,
    type JournalPair,
  } from '$lib/activity/commandGroups';
  import { holdIncidentText } from '$lib/activity/serviceText';
  import { auditDetail } from '$lib/activity/audit';
  import { formatDateTime, formatDuration, formatNumber } from '$lib/core/format';
  import type { LiveStore } from '$lib/core/live.svelte';
  import { buildHash, router } from '$lib/core/router.svelte';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import type { AlarmEvent, AuditEvent, CommandEvent } from '$lib/core/types';

  let { live, ctl }: { live: LiveStore; ctl: ControlStore } = $props();

  const TABS = ['alarms', 'holds', 'commands', 'audit'] as const;
  type Tab = (typeof TABS)[number];
  const TAB_ICON = { alarms: 'bell', holds: 'pause', commands: 'bolt', audit: 'eye' } as const;

  const active = $derived<Tab>(TABS.find((tab) => tab === router.location.sub[0]) ?? 'alarms');
  const items = $derived(
    TABS.map((tab) => ({
      id: tab,
      label: t(`tab_${tab}` as 'tab_alarms'),
      href: buildHash('activity', tab === 'alarms' ? [] : [tab]),
      icon: TAB_ICON[tab],
      count:
        tab === 'alarms'
          ? (ctl.control?.alarms.length ?? 0)
          : tab === 'holds' && ctl.control?.adapter?.hold
            ? 1
            : 0,
    })),
  );

  const RANGES = ['24h', '7d', 'custom'] as const;
  type RangeKind = (typeof RANGES)[number];
  const HOUR_MS = 3_600_000;
  let rangeKind = $state<RangeKind>('24h');
  let customFrom = $state('');
  let customTo = $state('');
  const presetTo = $derived(Math.round(live.clock / 60_000) * 60_000);
  const customWindow = $derived.by(() => {
    const from = Date.parse(customFrom);
    const to = Date.parse(customTo);
    return Number.isFinite(from) && Number.isFinite(to) && from < to ? { from, to } : null;
  });
  const windowTo = $derived(rangeKind === 'custom' && customWindow ? customWindow.to : presetTo);
  const windowFrom = $derived(
    rangeKind === 'custom' && customWindow
      ? customWindow.from
      : windowTo - (rangeKind === '7d' ? 7 * 24 : 24) * HOUR_MS,
  );
  const rangeOptions = $derived(
    RANGES.map((kind) => ({
      value: kind,
      label: t(`activityRange_${kind}`),
      testid: `activity-range-${kind}`,
    })),
  );
  const rangeInvalid = $derived(rangeKind === 'custom' && customWindow === null);
  const windowQuery = $derived(
    `from=${encodeURIComponent(new Date(windowFrom).toISOString())}&to=${encodeURIComponent(new Date(windowTo).toISOString())}`,
  );

  function localInput(ms: number): string {
    const d = new Date(ms);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function pickRange(kind: RangeKind): void {
    if (kind === 'custom' && rangeKind !== 'custom') {
      customFrom = localInput(windowFrom);
      customTo = localInput(windowTo);
    }
    rangeKind = kind;
  }

  let events = $state<AlarmEvent[]>([]);
  let commands = $state<CommandEvent[]>([]);
  let audit = $state<AuditEvent[]>([]);
  let auditState = $state<'loading' | 'ok' | 'missing' | 'forbidden' | 'failed'>('loading');
  let journalError = $state(false);

  $effect(() => {
    void live.decisionSeq;
    const from = new Date(windowFrom);
    const to = new Date(windowTo);
    const controller = new AbortController();
    Promise.all([
      fetchAlarms({ from, to }, controller.signal),
      fetchCommands({ from, to }, controller.signal),
    ])
      .then(([alarms, journal]) => {
        events = alarms.events;
        commands = journal.commands;
        journalError = false;
      })
      .catch(() => {
        if (!controller.signal.aborted) journalError = true;
      });
    return () => controller.abort();
  });

  $effect(() => {
    void live.decisionSeq;
    const from = new Date(windowFrom);
    const to = new Date(windowTo);
    const controller = new AbortController();
    fetchAudit({ from, to, limit: 200 }, controller.signal)
      .then((response) => {
        audit = response.events;
        auditState = 'ok';
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        audit = [];
        auditState = isMissing(error) ? 'missing' : isForbidden(error) ? 'forbidden' : 'failed';
      });
    return () => controller.abort();
  });

  const auditWords = {
    version: (n: number) => t('auditVersion', { n }),
    rollbackTo: (n: number) => t('auditRollbackTo', { n }),
    field: (id: string) => tOpt(`cfg.${id}.label`) ?? id,
    bool: (value: boolean) => (value ? t('on') : t('off')),
    number: (value: number) => formatNumber(value, 2, settings.language),
  };
  const configEvents = $derived(
    audit
      .filter((event) => event.action === 'config_apply' || event.action === 'config_rollback')
      .map((event) => {
        const detail = auditDetail(event, auditWords);
        const action = tc('audit_', event.action);
        return { at: Date.parse(event.at), text: detail ? `${action} · ${detail}` : action };
      }),
  );
  const kindName = (kind: string) => tOpt(`kind_${kind}`) ?? tOpt(`pumpSetting_${kind}`) ?? kind;
  const commandEvents = $derived(
    groupCommands(commands).map((group) => ({
      at: Date.parse(group.startedAt),
      text: [
        group.value === null
          ? kindName(group.kind)
          : `${kindName(group.kind)} ${formatNumber(group.value, 1, settings.language)}`,
        tc('cmd_', group.latest.status),
      ].join(' · '),
    })),
  );

  const control = $derived(ctl.control);
  const adapter = $derived(control?.adapter ?? null);
  const holdEvents = $derived(events.filter((event) => event.code === 'command_hold'));
  const journal = $derived(pairJournal(events.filter((event) => event.code !== 'command_hold')));
  const holdPairs = $derived(pairJournal(holdEvents));
  const openHold = $derived(holdPairs.find((pair) => pair.to === null) ?? null);
  const holdStarted = $derived(openHold?.from ?? null);
  const escalationH = $derived.by(() => {
    const value = ctl.config?.fields['command_escalation_hours']?.value;
    return typeof value === 'number' && value > 0 ? value : 12;
  });
  const budget = $derived(adapter?.budget ?? null);
  const ALWAYS_COUNTED = ['failed', 'retried'];
  const counters = $derived.by(() => {
    const raw = adapter?.counters ?? {};
    const shown = Object.entries(raw).filter(
      ([name, value]) => value > 0 || ALWAYS_COUNTED.includes(name),
    );
    for (const name of ALWAYS_COUNTED) if (!(name in raw) && adapter) shown.push([name, 0]);
    return shown;
  });

  function holdTitle(pair: JournalPair): string {
    return (
      holdIncidentText(
        pair.detail,
        (reason) => tc('holdWhy_', reason),
        (key, params) => tOpt(key, params),
      ) ?? pair.message
    );
  }

  const SEVERITY_ICON = { critical: 'critical', warning: 'warning', info: 'info' } as const;

  function span(pair: JournalPair): string {
    const from = formatDateTime(pair.from, settings.language);
    if (pair.to === null) return t('journalOpen', { from });
    if (pair.durationS === null) return from;
    return t('journalSpan', { from, duration: formatDuration(pair.durationS) });
  }
</script>

<h1>{t('activityTitle')}</h1>

<div class="range-bar" data-testid="activity-range" data-help="activity.range">
  <Segmented
    options={rangeOptions}
    value={rangeKind}
    onchange={pickRange}
    label={t('activityRangeLabel')}
    appearance="joined"
  />
  {#if rangeKind === 'custom'}
    <div class="custom">
      <label>
        <span>{t('activityRangeFrom')}</span>
        <TextInput
          block={false}
          type="datetime-local"
          bind:value={customFrom}
          aria-invalid={rangeInvalid}
          data-testid="activity-range-from"
        />
      </label>
      <label>
        <span>{t('activityRangeTo')}</span>
        <TextInput
          block={false}
          type="datetime-local"
          bind:value={customTo}
          aria-invalid={rangeInvalid}
          data-testid="activity-range-to"
        />
      </label>
    </div>
    {#if rangeInvalid}<p class="err" role="alert">{t('activityRangeInvalid')}</p>{/if}
  {/if}
</div>

<ActivityTimeline
  from={windowFrom}
  to={windowTo}
  alarms={journal}
  holds={holdPairs}
  {configEvents}
  {commandEvents}
  help="activity.timeline"
/>

<Tabs {items} {active} label={t('activityTabs')} />

{#snippet pairList(pairs: JournalPair[], named: boolean, testid: string)}
  <ul class="events" data-testid={testid}>
    {#each pairs as pair (pair.id)}
      <li class="sev-{pair.severity}">
        <Icon name={SEVERITY_ICON[pair.severity]} size={16} />
        <div class="text">
          <strong>{named ? tc('alarm_', pair.code) : holdTitle(pair)}</strong>
          <span class="caption">
            {span(pair)}
            {#if !named && pair.message}
              <Why title={t('serviceMessage')} label={t('whyButton')} width="22rem">
                <p class="raw">{pair.message}</p>
              </Why>
            {/if}
          </span>
        </div>
        <Pill tone={pair.endEvent === null ? 'warn' : 'good'}>
          {pair.endEvent === null ? t('journalActive') : tc('event_', pair.endEvent)}
        </Pill>
      </li>
    {/each}
  </ul>
{/snippet}

{#if active === 'alarms'}
  <div class="stack">
    <Card
      bare
      data-testid="alarms-active"
      data-help="activity.active"
      aria-labelledby="active-title"
    >
      <h2 id="active-title">{t('alarmsActive')}</h2>
      {#if control && control.alarms.length === 0}
        <EmptyState
          art="allQuiet"
          title={t('alarmsNone')}
          text={t('alarmsNoneText')}
          testid="no-alarms"
        />
      {:else}
        <AlarmList alarms={control?.alarms ?? []} monitors={control?.safety?.monitors ?? []} />
      {/if}
    </Card>

    <Card
      bare
      data-testid="alarms-monitors"
      data-help="activity.monitors"
      aria-labelledby="monitors-title"
    >
      <h2 id="monitors-title">{t('monitorsTitle')}</h2>
      {#if control?.safety}
        <p class="muted level">
          {t('monitorsLevel', {
            level: tc('severity_', control.safety.level === 'ok' ? 'ok' : control.safety.level),
          })}
        </p>
        <MonitorTable monitors={control.safety.monitors} />
      {:else}
        <p class="muted">{t('noControl')}</p>
      {/if}
    </Card>

    <Card
      bare
      data-testid="alarms-journal"
      data-help="activity.journal"
      aria-labelledby="journal-title"
    >
      <div class="card-head">
        <h2 id="journal-title">{t('journalTitle')}</h2>
        <DownloadCsv
          path={`api/v1/alarms?${windowQuery}`}
          name={`${DOWNLOAD_PREFIX}alarms.csv`}
          label={t('csvAlarms')}
          testid="csv-alarms"
        />
      </div>
      {#if journalError}
        <p class="muted">{t('journalError')}</p>
      {:else if journal.length === 0}
        <p class="muted">{t('journalEmpty')}</p>
      {:else}
        {@render pairList(journal, true, 'journal-list')}
      {/if}
    </Card>
  </div>
{:else if active === 'holds'}
  <div class="stack">
    <Card
      bare
      data-testid="holds-current"
      data-help="activity/holds.current"
      aria-labelledby="hold-title"
    >
      <h2 id="hold-title">{t('holdTitle')}</h2>
      <HoldCard
        {adapter}
        admin={ctl.admin}
        startedAt={holdStarted}
        windowH={escalationH}
        detail={openHold?.detail ?? null}
        onrelease={(reason) => ctl.release(reason)}
      />
    </Card>

    <Card
      bare
      data-testid="holds-incidents"
      data-help="activity/holds.history"
      aria-labelledby="incidents-title"
    >
      <div class="card-head">
        <h2 id="incidents-title">{t('incidentsTitle')}</h2>
        {#if holdPairs.length > 0}
          <DownloadCsv
            table={() => holdsTable(holdPairs)}
            name={`${DOWNLOAD_PREFIX}holds.csv`}
            label={t('csvHolds')}
            testid="csv-holds"
          />
        {/if}
      </div>
      {#if holdPairs.length === 0}
        <p class="muted">{t('incidentsEmpty')}</p>
      {:else}
        {@render pairList(holdPairs, false, 'hold-history')}
      {/if}
    </Card>
  </div>
{:else if active === 'commands'}
  <div class="stack">
    <Card
      bare
      data-testid="commands-budget"
      data-help="activity/commands.budget"
      aria-labelledby="budget-title"
    >
      <h2 id="budget-title">{t('budgetTitle')}</h2>
      {#if budget}
        <BulletBar
          label={t('budgetTitle')}
          value={budget.used}
          limit={budget.limit}
          warn={budget.limit - budget.safety_reserve}
          digits={0}
          min={0}
          showLabel={false}
          summary={t('budgetUsed', { used: budget.used, limit: budget.limit })}
        />
        <p class="budget">
          <strong>{t('budgetUsed', { used: budget.used, limit: budget.limit })}</strong>
          <span class="muted">{t('budgetReserve', { n: budget.safety_reserve })}</span>
        </p>
        {#if counters.length > 0}
          <h3 class="counters-title" id="counters-title">{t('countersTitle')}</h3>
          <ul class="chips" aria-labelledby="counters-title" data-testid="command-counters">
            {#each counters as [name, value] (name)}
              <li class="chip-static" data-counter={name}>
                {tc('counter_', name)} <strong>{value}</strong>
              </li>
            {/each}
          </ul>
        {/if}
      {:else}
        <p class="muted">{t('noAdapter')}</p>
      {/if}
    </Card>

    <Card
      bare
      data-testid="commands-journal"
      data-help="activity/commands.journal"
      aria-labelledby="commands-title"
    >
      <div class="card-head">
        <h2 id="commands-title">{t('commandsTitle')}</h2>
        <DownloadCsv
          path={`api/v1/commands?${windowQuery}`}
          name={`${DOWNLOAD_PREFIX}commands.csv`}
          label={t('csvCommands')}
          testid="csv-commands"
        />
      </div>
      {#if journalError}
        <p class="muted">{t('journalError')}</p>
      {:else}
        <CommandTable {commands} />
      {/if}
    </Card>
  </div>
{:else}
  <Card
    bare
    data-testid="audit-card"
    data-help="activity/audit.trail"
    aria-labelledby="audit-title"
  >
    <div class="card-head">
      <h2 id="audit-title">{t('auditTitle')}</h2>
      {#if auditState === 'ok'}
        <DownloadCsv
          path={`api/v1/audit?${windowQuery}`}
          name={`${DOWNLOAD_PREFIX}audit.csv`}
          label={t('csvAudit')}
          testid="csv-audit"
        />
      {/if}
    </div>
    {#if auditState === 'loading'}
      <p class="muted">{t('loading')}</p>
    {:else if auditState === 'missing'}
      <p class="muted" data-testid="audit-missing">{t('auditMissing')}</p>
    {:else if auditState === 'forbidden'}
      <p class="muted" data-testid="audit-forbidden">{t('auditForbidden')}</p>
    {:else if auditState === 'failed'}
      <p class="muted">{t('auditFailed')}</p>
    {:else}
      <AuditTable events={audit} />
    {/if}
  </Card>
{/if}

<style>
  .card-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2) var(--space-3);
    margin-bottom: var(--space-2);
  }
  .card-head h2 {
    margin: 0;
  }
  .range-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: var(--space-2) var(--space-3);
    margin-bottom: var(--space-3);
  }
  .custom {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-3);
  }
  .custom label {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .err {
    flex-basis: 100%;
    margin: 0;
    color: var(--err-text);
  }
  .counters-title {
    margin: var(--space-3) 0 0;
    font-size: var(--fs-body);
    color: var(--muted);
    font-weight: var(--fw-semibold);
  }
  .counters-title + .chips {
    margin-top: var(--space-2);
  }
  h2 {
    margin: 0 0 var(--space-2);
    font-size: var(--fs-emph);
  }
  .level {
    margin: 0 0 var(--space-2);
  }
  .events {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .events li {
    display: flex;
    gap: var(--space-3);
    align-items: center;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  .events li:last-child {
    border-bottom: none;
  }
  .events .text {
    display: grid;
    flex: 1;
    min-width: 0;
  }
  .raw {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .sev-critical :global(.icon) {
    color: var(--status-stopped);
  }
  .sev-warning :global(.icon) {
    color: var(--status-limited);
  }
  .sev-info :global(.icon) {
    color: var(--status-manual);
  }
  .budget {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-3);
    margin: var(--space-2) 0 0;
  }
  .chips {
    list-style: none;
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin: var(--space-3) 0 0;
    padding: 0;
  }
  .chip-static {
    padding: 0.15rem 0.6rem;
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    border: 1px solid var(--border);
    font-size: var(--fs-body);
  }
</style>
