<script lang="ts">
  import Overlay from './Overlay.svelte';

  let {
    modal = false,
    outside = false,
    onclose = () => undefined,
  }: { modal?: boolean; outside?: boolean; onclose?: () => void } = $props();
</script>

<button type="button" data-testid="opener">Open</button>
<div data-testid="elsewhere">Elsewhere</div>
<Overlay {modal} {outside} {onclose} autofocus restoreFocus role="dialog" aria-label="Panel">
  <button type="button" data-testid="first">First</button>
  <button type="button" data-testid="last">Last</button>
</Overlay>
