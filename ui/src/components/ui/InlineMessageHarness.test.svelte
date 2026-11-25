<script lang="ts">
  import InlineMessage from './InlineMessage.svelte';

  let { tone }: { tone: 'error' | 'warn' | 'ok' | 'info' } = $props();
</script>

<InlineMessage {tone} icon>Saved?</InlineMessage>
