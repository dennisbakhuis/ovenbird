<!--
  "Show me": scrolls the element marked data-help="<target>" into view and draws a ring
  around it that follows scroll and resize, fading after a few seconds or on any click.
-->
<script lang="ts" module>
  /** The visible page element marked with a help target, if any. */
  export function findTarget(target: string): HTMLElement | null {
    for (const element of document.querySelectorAll<HTMLElement>('[data-help]')) {
      if (element.dataset['help'] !== target || element.closest('[data-help-drawer]')) continue;
      if (element.getClientRects().length > 0) return element;
    }
    return null;
  }
</script>

<script lang="ts">
  interface Props {
    target: string;
    duration?: number;
    ondone: () => void;
  }

  let { target, duration = 4000, ondone }: Props = $props();

  let rect = $state<{ top: number; left: number; width: number; height: number } | null>(null);
  let fading = $state(false);

  $effect(() => {
    const element = findTarget(target);
    if (!element) {
      ondone();
      return;
    }
    const reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    element.scrollIntoView?.({
      block: 'center',
      inline: 'nearest',
      behavior: reduced ? 'auto' : 'smooth',
    });
    let frame = 0;
    let last = '';
    const measure = () => {
      const box = element.getBoundingClientRect();
      const key = `${box.top}:${box.left}:${box.width}:${box.height}`;
      if (key !== last) {
        last = key;
        rect = { top: box.top, left: box.left, width: box.width, height: box.height };
      }
      frame = requestAnimationFrame(measure);
    };
    measure();
    let fadeTimer = 0;
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      fading = true;
      fadeTimer = window.setTimeout(ondone, reduced ? 0 : 350);
    };
    const timer = window.setTimeout(finish, duration);
    const arm = window.setTimeout(() => document.addEventListener('pointerdown', finish, true), 0);
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
      clearTimeout(arm);
      clearTimeout(fadeTimer);
      document.removeEventListener('pointerdown', finish, true);
    };
  });
</script>

{#if rect}
  <div
    class="ring"
    class:fading
    aria-hidden="true"
    data-testid="help-spotlight"
    data-target={target}
    style:top="{rect.top - 6}px"
    style:left="{rect.left - 6}px"
    style:width="{rect.width + 12}px"
    style:height="{rect.height + 12}px"
  ></div>
{/if}

<style>
  .ring {
    position: fixed;
    z-index: 1;
    pointer-events: none;
    border: 3px solid var(--brand-ember);
    border-radius: calc(var(--radius) + var(--radius-sm));
    box-shadow:
      0 0 0 4px color-mix(in srgb, var(--brand-ember) 28%, transparent),
      0 6px 24px color-mix(in srgb, var(--brand-ember) 30%, transparent);
    animation: ring-in 0.45s ease-out;
    transition: opacity 0.35s ease;
  }
  .ring.fading {
    opacity: 0;
  }
  @keyframes ring-in {
    from {
      opacity: 0;
      transform: scale(1.06);
    }
    to {
      opacity: 1;
      transform: scale(1);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .ring {
      animation: none;
      transition: none;
    }
  }
</style>
