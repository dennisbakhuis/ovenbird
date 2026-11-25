<!--
  CommandProgress: where a command is on its way — queued, sent, verified — as three dots on a
  line. Failed ends (failed, refused, dropped) replace the line with one red step; `retry` shows
  as the sent step still waiting; a missing or unknown status (the service reports null while it
  has no verdict) shows one neutral "status unknown" step instead of a broken sequence.

  Props: status (string | null).
  A11y: an ordered list; the current step has aria-current="step"; each step has a text label.
-->
<script lang="ts">
  import { t, tOpt } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  let { status }: { status: string | null | undefined } = $props();

  const STEPS = ['queued', 'sent', 'verified'] as const;
  const FAILED = ['failed', 'refused', 'dropped'];
  const known = $derived(
    status !== null &&
      status !== undefined &&
      ([...STEPS, ...FAILED, 'retry'] as string[]).includes(status),
  );
  const failed = $derived(status !== null && status !== undefined && FAILED.includes(status));
  const index = $derived(
    status === 'retry' ? 1 : Math.max(STEPS.indexOf((status ?? '') as (typeof STEPS)[number]), 0),
  );
  const complete = $derived(status === 'verified');
  const label = (step: string) => tOpt(`cmd_${step}`) ?? step;
</script>

<ol
  class="progress"
  data-testid="command-progress"
  data-status={status ?? 'unknown'}
  class:unknown={!known}
>
  {#if !known}
    <li class="unknown-step" data-testid="progress-unknown">
      <span class="dot" aria-hidden="true"></span>{t('pumpStatusUnknown')}
    </li>
  {:else}
    {#each STEPS as step, i (step)}
      <li
        class:done={!failed && (i < index || complete)}
        class:current={!failed && i === index && !complete}
        aria-current={!failed && i === index ? 'step' : undefined}
      >
        <span class="dot" aria-hidden="true">
          {#if !failed && (i < index || complete)}<Icon name="check" size={10} />{/if}
        </span>
        {step === 'sent' && status === 'retry' ? label('retry') : label(step)}
      </li>
    {/each}
    {#if failed}
      <li class="failed" data-testid="progress-failed">
        <Icon name="critical" size={14} />{label(status ?? 'failed')}
      </li>
    {/if}
  {/if}
</ol>

<style>
  .progress {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) 0.9rem;
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  li {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  li + li:not(.failed)::before {
    content: '';
    width: 0.9rem;
    height: 2px;
    margin-right: 0.15rem;
    background: var(--border);
  }
  .dot {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    border: 1.5px solid var(--border);
    color: var(--on-accent);
  }
  li.done {
    color: var(--status-ok);
  }
  li.done .dot {
    background: var(--status-ok);
    border-color: var(--status-ok);
  }
  li.current {
    color: var(--accent);
    font-weight: var(--fw-semibold);
  }
  li.current .dot {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 30%, transparent);
  }
  li.failed {
    color: var(--status-stopped);
    font-weight: var(--fw-semibold);
  }
  li.failed::before {
    display: none;
  }
  .unknown-step .dot {
    border-style: dashed;
  }
</style>
