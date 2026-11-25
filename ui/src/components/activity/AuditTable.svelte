<!--
  AuditTable: the audit trail, newest first, one compact row per event (time, actor chip,
  action, detail).

  Props: events.
-->
<script lang="ts">
  import { auditActor, auditDetail } from '$lib/activity/audit';
  import { formatDateTime, formatNumber } from '$lib/core/format';
  import { settings, t, tc, tOpt } from '$lib/core/settings.svelte';
  import type { AuditEvent } from '$lib/core/types';

  let { events }: { events: AuditEvent[] } = $props();

  const words = {
    version: (n: number) => t('auditVersion', { n }),
    rollbackTo: (n: number) => t('auditRollbackTo', { n }),
    field: (id: string) => tOpt(`cfg.${id}.label`) ?? id,
    bool: (value: boolean) => (value ? t('on') : t('off')),
    number: (value: number) => formatNumber(value, 2, settings.language),
  };

  const sorted = $derived([...events].sort((a, b) => Date.parse(b.at) - Date.parse(a.at)));
</script>

<ul class="audit" data-testid="audit-table">
  {#each sorted as event, index (`${event.at}-${index}`)}
    <li>
      <span class="caption when">{formatDateTime(event.at, settings.language)}</span>
      <span class="actor">{auditActor(event)}</span>
      <strong class="action">{tc('audit_', event.action)}</strong>
      <span class="detail">{auditDetail(event, words)}</span>
    </li>
  {:else}
    <li class="muted">{t('auditEmpty')}</li>
  {/each}
</ul>

<style>
  .audit {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    display: grid;
    grid-template-columns: auto 1fr;
    grid-template-areas:
      'action actor'
      'detail detail'
      'when when';
    gap: 2px var(--space-3);
    align-items: center;
    padding: var(--space-2) 0;
    border-bottom: 1px solid var(--border);
  }
  li:last-child {
    border-bottom: none;
  }
  .action {
    grid-area: action;
  }
  .actor {
    grid-area: actor;
    justify-self: start;
    padding: 0 var(--space-2);
    border-radius: var(--radius-pill);
    background: var(--surface-2);
    border: 1px solid var(--border);
    font-size: var(--fs-caption);
  }
  .detail {
    grid-area: detail;
    font-size: var(--fs-body);
    color: var(--muted);
    overflow-wrap: anywhere;
  }
  .detail:empty {
    display: none;
  }
  .when {
    grid-area: when;
    color: var(--muted);
  }
  @media (--wide) {
    li {
      grid-template-columns: 9rem 9rem 12rem 1fr;
      grid-template-areas: 'when actor action detail';
    }
  }
</style>
