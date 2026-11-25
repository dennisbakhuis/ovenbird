<!--
  Switch: an on/off toggle (role="switch" on a checkbox) with an optional state word. Wrap it in
  a FormRow or give it an id and a label elsewhere.
-->
<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLInputAttributes, 'class' | 'type' | 'children'> {
    checked?: boolean;
    state?: string;
    class?: string;
  }

  let { checked = $bindable(false), state, class: extra = '', disabled, ...rest }: Props = $props();
</script>

<label class="switch {extra}">
  <input {...rest} type="checkbox" role="switch" {disabled} bind:checked />
  <span class="track" aria-hidden="true"><span class="thumb"></span></span>
  {#if state !== undefined}<span class="state">{state}</span>{/if}
</label>

<style>
  @layer components {
    .switch {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-height: var(--tap);
      cursor: pointer;
    }
    input {
      position: absolute;
      opacity: 0;
      width: 100%;
      height: 100%;
      margin: 0;
      cursor: pointer;
    }
    .track {
      position: relative;
      width: 2.6rem;
      height: 1.5rem;
      border-radius: var(--radius-pill);
      background: var(--surface-2);
      border: 1px solid var(--border);
      transition: background var(--dur-fast);
    }
    .thumb {
      position: absolute;
      top: 2px;
      left: 2px;
      width: calc(1.5rem - 6px);
      height: calc(1.5rem - 6px);
      border-radius: 50%;
      background: var(--muted);
      transition: transform var(--dur-fast);
    }
    input:checked + .track {
      background: var(--accent);
      border-color: var(--accent);
    }
    input:checked + .track .thumb {
      background: var(--on-accent);
      transform: translateX(1.1rem);
    }
    input:focus-visible + .track {
      outline: 3px solid var(--accent);
      outline-offset: 2px;
    }
    input:disabled + .track {
      opacity: 0.5;
    }
    .state {
      min-width: 2rem;
      color: var(--muted);
    }
    @media (prefers-reduced-motion: reduce) {
      .track,
      .thumb {
        transition: none;
      }
    }
  }
</style>
