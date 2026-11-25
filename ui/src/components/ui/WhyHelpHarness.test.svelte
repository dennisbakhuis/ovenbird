<script lang="ts">
  import Why from './Why.svelte';

  let { helpId }: { helpId?: string } = $props();
</script>

<div data-help={helpId}><Why title="Wait time" sheet="never"><p>Explanation text</p></Why></div>
