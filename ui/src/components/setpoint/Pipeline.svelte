<!--
  Pipeline: the controller's stages in order (curve → room feedback → plan → start ramp →
  cycling protection → safety → rounding / dead band / wait time) as connected chips. A stage that
  contributes is filled, the binding stage is outlined in amber, a frozen stage carries a lock.
  Hold and refuse decisions grey out every stage.

  Props: record (DecisionRecord).
  A11y: an ordered list; each chip's state is part of its text ("binding", "frozen", "no
  contribution").
-->
<script lang="ts">
  import type { DecisionRecord } from '$lib/core/types';
  import { fixedBase } from '$lib/setpoint/explain';
  import { t, tc } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  let { record }: { record: DecisionRecord } = $props();

  type StageState = 'active' | 'idle' | 'binding' | 'frozen';

  const BINDING_STAGE: Record<string, string> = {
    safety_min: 'safety',
    safety_max: 'safety',
    envelope_min: 'safety',
    envelope_max: 'safety',
    cycling_floor: 'cycling_floor',
    start_ramp: 'start_ramp',
    room_feedback_limit: 'room_feedback',
    room_authority: 'room_feedback',
    plan_limit: 'plan',
    override: 'override',
    rounding: 'stage',
    deadband: 'stage',
    dwell: 'stage',
    defrost_hold: 'stage',
    dhw_hold: 'stage',
  };

  const stages = $derived.by(() => {
    const stopped = record.ladder === 'hold' || record.ladder === 'refuse';
    const frozenBy = String(record.controller_state['frozen_by'] ?? '');
    const value = (name: string) => record.terms.find((term) => term.name === name);
    const bound = record.binding ? BINDING_STAGE[record.binding] : undefined;
    const ids = ['curve', 'room_feedback', 'plan', 'start_ramp', 'cycling_floor'];
    if (value('override')) ids.push('override');
    ids.push('safety', 'stage');
    return ids.map((id) => {
      let state: StageState = 'idle';
      const term = value(id);
      if (id === 'curve' && term) state = 'active';
      else if (id === 'safety')
        state = term && Math.abs(term.value - term.raw) > 1e-6 ? 'active' : 'idle';
      else if (id === 'stage')
        state =
          record.setpoint !== null &&
          record.pre_round !== null &&
          Math.abs(record.setpoint - record.pre_round) > 1e-6
            ? 'active'
            : 'idle';
      else if (term && Math.abs(term.value) > 1e-6) state = 'active';
      if (id === 'room_feedback' && frozenBy !== '' && !stopped) state = 'frozen';
      if (bound === id) state = 'binding';
      if (stopped) state = 'idle';
      const label =
        id === 'stage'
          ? t('stageRounding')
          : id === 'curve' && fixedBase(record)
            ? t('wf_fixed')
            : tc('term_', id);
      return { id, state, label };
    });
  });
</script>

<ol class="pipeline" data-testid="pipeline" aria-label={t('pipelineLabel')}>
  {#each stages as stage, index (stage.id)}
    <li class={stage.state} data-stage={stage.id}>
      {#if stage.state === 'frozen'}<Icon name="lock" size={12} />{/if}
      {#if stage.state === 'binding'}<Icon name="warning" size={12} />{/if}
      <span>{stage.label}</span>
      <span class="visually-hidden">({t(`stage_${stage.state}` as 'stage_active')})</span>
    </li>
    {#if index < stages.length - 1}<li class="arrow" aria-hidden="true">›</li>{/if}
  {/each}
</ol>

<style>
  .pipeline {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) 0.2rem;
    font-size: var(--fs-caption);
  }
  li {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    padding: 0.1rem 0.45rem;
    border-radius: var(--radius-pill);
    border: 1px solid var(--border);
    color: var(--muted);
    white-space: nowrap;
  }
  .active {
    color: var(--text);
    background: var(--surface-2);
    border-color: var(--text);
  }
  .binding {
    color: var(--status-limited);
    background: var(--status-limited-bg);
    border-color: var(--status-limited);
    font-weight: var(--fw-semibold);
  }
  .frozen {
    color: var(--status-frozen);
    background: var(--status-frozen-bg);
    border-color: var(--status-frozen);
  }
  .arrow {
    border: none;
    padding: 0;
    color: var(--muted);
  }
</style>
