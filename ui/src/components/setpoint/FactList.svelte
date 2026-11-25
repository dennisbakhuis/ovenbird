<!--
  FactList: what shaped the decision beyond the terms (defrost or hot-water run, the latter as
  "pump busy elsewhere" under a gear while hot water is hidden, skipped duty
  command, cycling floor raising the setpoint or only limiting a decrease, start-ramp cap, frozen
  integrator, the chosen outside sensor of the curve or its fall-back to the pump's sensor) as
  short call-outs with an icon and a status colour.

  Props: facts (Fact[] from decisionFacts).
  A11y: a list; every call-out is a full sentence, the icon is decorative.
-->
<script lang="ts">
  import type { Fact, FactKind } from '$lib/setpoint/explain';
  import type { IconName } from '$lib/core/icons';
  import { formatClock } from '$lib/core/format';
  import { BUSY_ICON, hotWater } from '$lib/core/hotWater.svelte';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import { signalName } from '$lib/core/signalView';
  import Icon from '$ui/Icon.svelte';

  const frozenLabel = (name: string) => tOpt(`frozenBy_${name}`) ?? tc('reason_', name);

  let { facts }: { facts: Fact[] } = $props();

  const ICON: Record<FactKind, IconName> = {
    defrost: 'snowflake',
    dhw: 'tap',
    duty_skipped: 'pump',
    cycling_raise: 'trendUp',
    cycling_limit: 'lock',
    ramp_cap: 'ramp',
    held_clamped: 'lock',
    integrator_frozen: 'lock',
    stove: 'flame',
    stove_blocked: 'clock',
    stove_level_blocked: 'clock',
    stove_reentry_wait: 'clock',
    stove_reference_short: 'warning',
    stove_fault: 'warning',
    stove_exited: 'flame',
    outside_source: 'thermometer',
    outside_fallback: 'warning',
  };
  const TONE: Record<FactKind, string> = {
    defrost: 'frozen',
    dhw: 'frozen',
    duty_skipped: 'frozen',
    cycling_raise: 'limited',
    cycling_limit: 'limited',
    ramp_cap: 'limited',
    held_clamped: 'limited',
    integrator_frozen: 'frozen',
    stove: 'limited',
    stove_blocked: 'normal',
    stove_level_blocked: 'normal',
    stove_reentry_wait: 'normal',
    stove_reference_short: 'limited',
    stove_fault: 'limited',
    stove_exited: 'normal',
    outside_source: 'normal',
    outside_fallback: 'limited',
  };

  function text(fact: Fact): string {
    if (fact.kind === 'integrator_frozen') {
      const by = String(fact.params['by'] ?? '')
        .split(',')
        .map((name) => frozenLabel(name))
        .join(', ');
      return t('fact_integrator_frozen', { by });
    }
    if (fact.kind === 'stove') {
      const since = String(fact.params['since'] ?? '');
      return t('fact_stove', {
        ...fact.params,
        since: since ? formatClock(since, settings.language) : '–',
        source: tOpt(`stoveSource_${String(fact.params['source'])}`) ?? '',
      });
    }
    if (fact.kind === 'stove_exited') {
      const reason = String(fact.params['reason'] ?? '');
      return t('fact_stove_exited', { reason: tOpt(`stoveExit_${reason}`) ?? reason });
    }
    if (fact.kind === 'outside_source' || fact.kind === 'outside_fallback') {
      const name = signalName(String(fact.params['signal'] ?? ''), null, tOpt);
      const why = String(fact.params['why'] ?? 'unknown');
      return t(fact.kind === 'outside_source' ? 'fact_outside_source' : 'fact_outside_fallback', {
        ...fact.params,
        name,
        why: tOpt(`outsideWhy_${why}`, { min: fact.params['min'] ?? '–' }) ?? why,
      });
    }
    return t(`fact_${fact.kind}` as 'fact_defrost', fact.params);
  }
</script>

{#if facts.length > 0}
  <ul class="fact-list" data-testid="decision-facts">
    {#each facts as fact (fact.kind)}
      <li class={TONE[fact.kind]} data-fact={fact.kind}>
        <Icon
          name={fact.kind === 'dhw' && !hotWater.shown ? BUSY_ICON : ICON[fact.kind]}
          size={18}
        />
        <span>{text(fact)}</span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  .fact-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.35rem;
  }
  li {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: 0.4rem 0.6rem;
    border-radius: var(--radius-sm);
    font-size: var(--fs-body);
  }
  li :global(svg) {
    margin-top: 0.05rem;
  }
  .frozen {
    background: var(--status-frozen-bg);
  }
  .frozen :global(svg) {
    color: var(--status-frozen);
  }
  .limited {
    background: var(--status-limited-bg);
  }
  .limited :global(svg) {
    color: var(--status-limited);
  }
  .normal {
    background: var(--surface-2);
  }
  .normal :global(svg) {
    color: var(--muted);
  }
</style>
