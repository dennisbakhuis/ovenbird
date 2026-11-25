<script lang="ts">
  import Why from './Why.svelte';

  let { title, sheet = 'never' }: { title: string; sheet?: 'auto' | 'always' | 'never' } = $props();
</script>

<Why {title} {sheet}><p>Explanation text</p></Why>
