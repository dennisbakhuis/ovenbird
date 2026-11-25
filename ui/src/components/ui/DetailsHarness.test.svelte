<script lang="ts">
  import Details from './Details.svelte';

  let { id }: { id?: string } = $props();
</script>

<Details summary="Inputs" {id} meta={4}><p>Hidden body</p></Details>
