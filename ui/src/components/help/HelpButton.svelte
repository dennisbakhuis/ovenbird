<!--
  The "?" button in the top bar, and the `?` key anywhere outside a text field. Until help has
  been opened once in this browser the button carries a small dot.
-->
<script lang="ts">
  import Button from '$ui/Button.svelte';
  import { help } from '$lib/help/store.svelte';
  import { t } from '$lib/core/settings.svelte';
  import Icon from '$ui/Icon.svelte';

  function typing(target: EventTarget | null): boolean {
    return (
      target instanceof Element &&
      target.closest(
        'input, textarea, select, [contenteditable]:not([contenteditable="false"])',
      ) !== null
    );
  }

  function onkeydown(event: KeyboardEvent): void {
    if (
      event.key !== '?' ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      event.defaultPrevented
    )
      return;
    if (typing(event.target)) return;
    event.preventDefault();
    help.toggle();
  }
</script>

<svelte:window {onkeydown} />

<Button
  class="tool hit help-tool"
  aria-label={help.seen ? t('helpTitle') : t('helpButtonNew')}
  aria-expanded={help.open}
  aria-keyshortcuts="?"
  title={t('helpKeyTitle')}
  onclick={() => help.toggle()}
  data-testid="help-button"
>
  <Icon name="why" size={20} />
  {#if !help.seen}<span class="dot" aria-hidden="true" data-testid="help-dot"></span>{/if}
</Button>

<style>
  .dot {
    position: absolute;
    top: 7px;
    right: 7px;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--brand-ember);
    box-shadow: 0 0 0 2px var(--surface);
  }
</style>
