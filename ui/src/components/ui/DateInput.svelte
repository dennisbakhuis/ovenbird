<!--
  DateInput: a calendar date as `YYYY-MM-DD`, with the browser's own date picker. An empty or
  incomplete entry reports nothing.
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

  let { value, onchange, invalid = false, width = '11rem', ...rest }: Props = $props();

  function commit(event: Event & { currentTarget: HTMLInputElement }): void {
    const next = event.currentTarget.value;
    if (/^\d{4}-\d{2}-\d{2}$/.test(next)) onchange(next);
  }
</script>

<TextInput
  {...rest}
  type="date"
  {value}
  {invalid}
  {width}
  block={false}
  onchange={commit}
  oninput={commit}
/>
