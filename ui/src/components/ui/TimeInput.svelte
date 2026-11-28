<!--
  TimeInput: a time of day as `HH:MM` (24 h), with the browser's own time picker. The value is
  always the plain `HH:MM` string the service stores; an empty or incomplete entry reports
  nothing, so a half-typed time never reaches the draft.
-->
<script lang="ts">
  import type { HTMLInputAttributes } from 'svelte/elements';
  import TextInput from './TextInput.svelte';

  interface Props extends Omit<HTMLInputAttributes, 'class' | 'type' | 'value' | 'onchange'> {
    value: string;
    onchange: (value: string) => void;
    invalid?: boolean;
    width?: string;
  }

  let { value, onchange, invalid = false, width = '8rem', ...rest }: Props = $props();

  function commit(event: Event & { currentTarget: HTMLInputElement }): void {
    const next = event.currentTarget.value;
    if (/^\d{2}:\d{2}$/.test(next)) onchange(next);
  }
</script>

<TextInput
  {...rest}
  type="time"
  {value}
  {invalid}
  {width}
  block={false}
  onchange={commit}
  oninput={commit}
/>
