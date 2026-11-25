<!--
  FormRow: label, control, hint and error with the ids wired up. The control comes in as a
  snippet that receives `id`, `describedby` and `invalid`: pass them to TextInput, Select, Switch
  or Checkbox as `id`, `aria-describedby` and `invalid`.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';

  interface ControlProps {
    id: string;
    describedby: string | undefined;
    invalid: boolean;
  }

  interface Props {
    label: string;
    hint?: string;
    error?: string;
    id?: string;
    inline?: boolean;
    testid?: string;
    control: Snippet<[ControlProps]>;
  }

  const uid = Math.random().toString(36).slice(2, 8);
  let { label, hint, error, id = `row-${uid}`, inline = false, testid, control }: Props = $props();

  const hintId = $derived(`${id}-hint`);
  const errorId = $derived(`${id}-error`);
  const describedby = $derived(
    [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined,
  );
</script>

<div class="row" class:inline data-testid={testid}>
  <label for={id}>{label}</label>
  <div class="control">{@render control({ id, describedby, invalid: Boolean(error) })}</div>
  {#if hint}<p class="hint" id={hintId}>{hint}</p>{/if}
  {#if error}<p class="error" id={errorId} role="alert">{error}</p>{/if}
</div>

<style>
  @layer components {
    .row {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      min-width: 0;
    }
    .row.inline {
      flex-direction: row;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-1) var(--space-3);
    }
    label {
      font-weight: var(--fw-semibold);
    }
    .control {
      min-width: 0;
    }
    p {
      margin: 0;
      font-size: var(--fs-caption);
    }
    .hint {
      color: var(--muted);
    }
    .error {
      color: var(--err-text);
    }
  }
</style>
