<!--
  CommandTable: the command journal, one row per command with its latest status. A row expands
  into the timeline of its steps (queued, sent, verified), newest first.

  Props: commands (raw journal rows, any order), pageSize (rows shown before "show more").
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { groupCommands, isTerminal } from '$lib/activity/commandGroups';
  import { formatDateTime, formatDuration } from '$lib/core/format';
  import { commandDetailText } from '$lib/activity/serviceText';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';
  import Pill from '$ui/Pill.svelte';

  let {
    commands,
    pageSize = 20,
  }: { commands: Parameters<typeof groupCommands>[0]; pageSize?: number } = $props();

  let shown = $state(0);
  let openIds = $state<Record<string, boolean>>({});

  const groups = $derived(groupCommands(commands));
  const limit = $derived(Math.max(shown, pageSize));
  const visible = $derived(groups.slice(0, limit));

  function tone(status: string): 'good' | 'warn' | 'bad' | 'info' | 'neutral' {
    if (status === 'verified') return 'good';
    if (status === 'failed' || status === 'refused') return 'bad';
    if (status === 'retry') return 'warn';
    if (status === 'sent' || status === 'queued') return 'info';
    return 'neutral';
  }

  const kindName = (kind: string) => tOpt(`kind_${kind}`) ?? tOpt(`pumpSetting_${kind}`) ?? kind;

  function summary(group: ReturnType<typeof groupCommands>[number]): string {
    const { latest } = group;
    if (latest.status === 'verified' && group.durationS !== null && group.durationS >= 1)
      return t('cmdVerifiedIn', { time: formatDuration(group.durationS) });
    return detailText(latest.detail);
  }

  function detailText(detail: string): string {
    return (
      commandDetailText(
        detail,
        (key, params) => tOpt(key, params),
        (reason) => tc('holdReason_', reason).toLowerCase(),
      ) ?? detail
    );
  }
</script>

<ul class="commands" data-testid="command-table">
  {#each visible as group (group.id)}
    {@const open = openIds[group.id] === true}
    <li>
      <Button
        variant="bare"
        class="cmd-row-head"
        aria-expanded={open}
        aria-controls="steps-{group.id}"
        onclick={() => (openIds[group.id] = !open)}
      >
        <span class="when caption">{formatDateTime(group.startedAt, settings.language)}</span>
        <span class="what">
          <strong>{kindName(group.kind)}</strong>
          <span class="value num">{group.value ?? '–'}</span>
        </span>
        <span class="state">
          <Pill tone={tone(group.latest.status)}>{tc('cmd_', group.latest.status)}</Pill>
        </span>
        <span class="detail caption">{summary(group)}</span>
        <span class="chev" class:open>
          <Icon name="chevronDown" size={16} label={open ? t('hideSteps') : t('showSteps')} />
        </span>
      </Button>
      {#if open}
        <ol class="steps" id="steps-{group.id}">
          {#each group.steps as step, index (`${step.at}-${step.status}-${index}`)}
            <li>
              <span class="caption">{formatDateTime(step.at, settings.language)}</span>
              <Pill tone={tone(step.status)} size="sm">{tc('cmd_', step.status)}</Pill>
              <span class="caption">{detailText(step.detail)}</span>
              {#if step.attempt > 1}
                <span class="caption">{t('cmdAttempt', { n: step.attempt })}</span>
              {/if}
            </li>
          {/each}
          {#if !isTerminal(group.latest.status)}
            <li class="caption">{t('cmdOpen')}</li>
          {/if}
        </ol>
      {/if}
    </li>
  {:else}
    <li class="muted empty">{t('commandsEmpty')}</li>
  {/each}
</ul>

{#if groups.length > limit}
  <Button class="cmd-more" onclick={() => (shown = limit + pageSize)}>
    {t('showMore', { n: groups.length - limit })}
  </Button>
{/if}

<style>
  .commands {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .commands > li {
    border-bottom: 1px solid var(--border);
  }
  .commands > li:last-child {
    border-bottom: none;
  }
  :global(.cmd-row-head) {
    all: unset;
    box-sizing: border-box;
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto auto;
    grid-template-areas:
      'what what state chev'
      'when detail detail detail';
    gap: 2px var(--space-3);
    align-items: center;
    width: 100%;
    padding: var(--space-2) 0;
    cursor: pointer;
  }
  :global(.cmd-row-head):focus-visible {
    outline: 2px solid var(--accent, currentColor);
    outline-offset: 2px;
    border-radius: var(--radius-s);
  }
  .what {
    grid-area: what;
    display: flex;
    gap: var(--space-2);
    align-items: baseline;
    flex-wrap: wrap;
    min-width: 0;
  }
  .when {
    grid-area: when;
    color: var(--muted);
    white-space: nowrap;
  }
  .state {
    grid-area: state;
  }
  .detail {
    grid-area: detail;
    color: var(--muted);
    text-align: right;
    overflow-wrap: anywhere;
  }
  .chev {
    grid-area: chev;
    display: inline-flex;
    color: var(--muted);
    transition: transform var(--dur-fast);
  }
  .chev.open {
    transform: rotate(180deg);
  }
  .steps {
    list-style: none;
    margin: 0 0 var(--space-2) var(--space-3);
    padding: 0 0 0 var(--space-3);
    border-left: 2px solid var(--border);
    display: grid;
    gap: var(--space-1);
  }
  .steps li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) var(--space-3);
  }
  :global(.cmd-more) {
    margin-top: var(--space-3);
  }
  .empty {
    padding: var(--space-2) 0;
  }
  @media (--wide) {
    :global(.cmd-row-head) {
      grid-template-columns: 9rem minmax(0, 14rem) 7rem minmax(0, 1fr) auto;
      grid-template-areas: 'when what state detail chev';
    }
    .detail {
      text-align: left;
    }
  }
</style>
