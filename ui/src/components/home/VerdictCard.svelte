<!--
  VerdictCard: one line at the top of Home that says how the house is ("The house is at
  temperature", "Warming up", "Needs attention: …", "Wood stove burning, heating backed off", or
  "Wood stove burning; ovenbird only watches, so nothing is backed off"),
  driven by alarms, a hold, whether ovenbird may send, room trust and wood-stove mode, with a link
  to where to look; under it the outlook for tonight.

  Props: verdict (Verdict), tonight (sentence | null), clock (service clock, for hold times).
-->
<script lang="ts">
  import { formatDateTime } from '$lib/core/format';
  import type { IconName } from '$lib/core/icons';
  import type { MessageKey } from '$lib/i18n';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import type { Verdict } from '$lib/home/verdict';
  import Icon from '$ui/Icon.svelte';

  let {
    verdict,
    tonight = null,
    clock,
  }: { verdict: Verdict; tonight?: string | null; clock: number } = $props();

  const ICON: Record<Verdict['tone'], IconName> = {
    good: 'check',
    info: 'info',
    warn: 'warning',
    bad: 'critical',
    neutral: 'info',
  };

  const what = $derived.by(() => {
    const a = verdict.attention;
    if (!a) return '';
    if (a.kind === 'alarm') {
      const title = tc('alarm_', a.code);
      return a.more > 0 ? t('alertAlarmWorst', { title, n: a.more }) : title;
    }
    if (a.kind === 'held') {
      if (a.latched) return t('verdictHeldLatched');
      if (a.reason) return tc('holdWhy_', a.reason);
      return a.until === null
        ? t('verdictHeldLatched')
        : t('verdictHeld', { time: formatDateTime(a.until, settings.language, clock) });
    }
    if (a.kind === 'refused') return t('verdictRefused');
    if (a.kind === 'notify') return t('verdictNotify');
    return t(`verdictRoom_${a.trust}` as MessageKey);
  });
  const text = $derived(
    verdict.kind === 'attention'
      ? t('verdict_attention', { what })
      : verdict.kind === 'stove_idle'
        ? (tOpt(`verdict_stove_idle_${verdict.control ?? ''}`) ?? t('verdict_stove_idle'))
        : t(`verdict_${verdict.kind}` as MessageKey),
  );
  const link = $derived.by(() => {
    const a = verdict.attention;
    if (!a) return null;
    if (a.kind === 'held') return '#/activity/holds';
    if (a.kind === 'room') return '#/setpoint';
    if (a.kind === 'refused' || a.kind === 'notify') return '#/system';
    return '#/activity';
  });
</script>

<section
  class="verdict tone-{verdict.tone}"
  role={verdict.tone === 'bad' ? 'alert' : 'status'}
  data-testid="home-verdict"
  data-verdict={verdict.kind}
  data-help="home.verdict"
>
  <Icon name={ICON[verdict.tone]} size={20} />
  <div class="text">
    {#if link}
      <a class="line" href={link} data-testid="verdict-link"
        ><span data-testid="verdict-text">{text}</span><Icon name="chevronRight" size={16} /></a
      >
    {:else}
      <p class="line" data-testid="verdict-text">{text}</p>
    {/if}
    {#if tonight}<p class="tonight" data-testid="tonight">{tonight}</p>{/if}
  </div>
</section>

<style>
  .verdict {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    border: 1px solid var(--border);
    border-left-width: 4px;
    border-radius: var(--radius);
    background: var(--surface);
  }
  .verdict > :global(.icon) {
    flex: none;
  }
  .tone-good {
    border-left-color: var(--status-ok);
  }
  .tone-good > :global(.icon) {
    color: var(--status-ok);
  }
  .tone-info,
  .tone-neutral {
    border-left-color: var(--status-manual);
  }
  .tone-info > :global(.icon),
  .tone-neutral > :global(.icon) {
    color: var(--status-manual);
  }
  .tone-warn {
    border-color: var(--status-limited);
    background: var(--status-limited-bg);
  }
  .tone-warn > :global(.icon) {
    color: var(--status-limited);
  }
  .tone-bad {
    border-color: var(--status-stopped);
    background: var(--status-stopped-bg);
  }
  .tone-bad > :global(.icon) {
    color: var(--status-stopped);
  }
  .text {
    flex: 1;
    min-width: 0;
  }
  p {
    margin: 0;
  }
  .line {
    font-weight: var(--fw-bold);
    line-height: var(--lh-tight);
  }
  a.line {
    display: inline-flex;
    align-items: center;
    gap: 0.15rem;
    color: inherit;
    text-decoration: none;
  }
  a.line:hover span {
    text-decoration: underline;
  }
  a.line :global(.icon) {
    flex: none;
    color: var(--muted);
  }
  .tonight {
    margin-top: 0.15rem;
    color: var(--muted);
    font-size: var(--fs-caption);
  }
</style>
