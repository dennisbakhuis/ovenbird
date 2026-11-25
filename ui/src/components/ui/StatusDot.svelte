<!--
  StatusDot: a small coloured dot for a state, with an optional text for screen readers.
-->
<script lang="ts">
  type Tone = 'ok' | 'limited' | 'frozen' | 'stopped' | 'manual' | 'unknown' | 'accent';

  interface Props {
    tone?: Tone;
    size?: number;
    label?: string;
    title?: string;
    testid?: string;
  }

  let { tone = 'unknown', size = 8, label, title, testid }: Props = $props();
</script>

<span
  class="dot {tone}"
  style:width="{size}px"
  style:height="{size}px"
  {title}
  data-testid={testid}
>
  {#if label}<span class="visually-hidden">{label}</span>{/if}
</span>

<style>
  @layer components {
    .dot {
      display: inline-block;
      flex: none;
      border-radius: 50%;
    }
    .ok {
      background: var(--cat-normal);
    }
    .limited {
      background: var(--cat-limited);
    }
    .frozen {
      background: var(--cat-frozen);
    }
    .stopped {
      background: var(--cat-stopped);
    }
    .manual {
      background: var(--cat-manual);
    }
    .unknown {
      background: var(--cat-unknown);
    }
    .accent {
      background: var(--accent);
    }
  }
</style>
