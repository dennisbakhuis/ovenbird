<script lang="ts">
  import FormRow from './FormRow.svelte';
  import TextInput from './TextInput.svelte';

  let { hint, error }: { hint?: string; error?: string } = $props();
</script>

<FormRow label="Comment" {hint} {error}>
  {#snippet control({ id, describedby, invalid })}
    <TextInput {id} aria-describedby={describedby} {invalid} />
  {/snippet}
</FormRow>
