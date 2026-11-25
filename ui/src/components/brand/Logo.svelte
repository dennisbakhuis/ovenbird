<!--
  The ovenbird mark: a hornero on its clay oven nest, an ember in the door,
  standing on the water line. The bird takes the theme's ink so it stays
  visible on dark surfaces; the clay, the door and the ember keep their
  colours in both themes. `wordmark` adds "ovenbird" in the brand face,
  "oven" bold over a regular "bird".
-->
<script lang="ts">
  import { WORDMARK } from '$lib/core/brand';
  interface Props {
    size?: number;
    wordmark?: boolean;
    label?: string;
  }

  let { size = 32, wordmark = false, label }: Props = $props();
</script>

<span class="logo" role={label ? 'img' : undefined} aria-label={label}>
  <svg viewBox="0 0 64 64" width={size} height={size} aria-hidden="true" focusable="false">
    <path d="M4 56 H60" stroke="var(--brand-cobalt)" stroke-width="4" stroke-linecap="round" />
    <path d="M10 56 C10 39 19.5 29 33 29 C46.5 29 56 39 56 56 Z" fill="var(--brand-clay-deep)" />
    <path d="M8 54 C8 37 17.5 27 31 27 C44.5 27 54 37 54 54 Z" fill="var(--brand-clay)" />
    <path
      d="M13 44 C14.5 36.5 20.5 31.5 27 30.3"
      fill="none"
      stroke="var(--brand-clay-light)"
      stroke-width="2"
      stroke-linecap="round"
    />
    <path d="M24 54 V47.5 A7 7 0 0 1 38 47.5 V54 Z" fill="var(--brand-night)" />
    <path
      class="ember"
      d="M31 53.6 C27.6 53.6 27.6 49.2 31 45.6 C34.4 49.2 34.4 53.6 31 53.6 Z"
      fill="var(--brand-ember)"
    />
    <g fill="var(--brand-ink)">
      <path d="M28.8 20.6 L21.6 26.6 L24.8 27 L28 23.8 Z" />
      <ellipse cx="30.8" cy="17.6" rx="4.2" ry="6.4" transform="rotate(28 30.8 17.6)" />
      <circle cx="34.6" cy="10" r="3" />
      <path d="M37.1 9.1 Q40.2 9.6 42.6 11.4 L37.3 11.1 Z" />
    </g>
    <g stroke="var(--brand-ink)" stroke-width="1.3" stroke-linecap="round">
      <path d="M29.6 23 L29.2 27.2" />
      <path d="M31.8 22.6 L32.5 27.2" />
    </g>
    <circle cx="35.3" cy="9.4" r="0.8" fill="var(--surface)" />
  </svg>
  {#if wordmark}<span class="word" aria-hidden={label ? 'true' : undefined}
      ><b>{WORDMARK.bold}</b>{WORDMARK.light}</span
    >{/if}
</span>

<style>
  .logo {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    line-height: 1;
  }
  svg {
    flex: none;
    display: block;
  }
  .word {
    font-family: var(--font-display);
    font-weight: var(--fw-regular);
    font-size: var(--fs-brand);
    letter-spacing: -0.01em;
    color: var(--text);
  }
  .word b {
    font-weight: var(--fw-bold);
  }
  .ember {
    transform-box: fill-box;
    transform-origin: 50% 100%;
  }
  @media (prefers-reduced-motion: no-preference) {
    .logo:hover .ember {
      animation: flicker 0.9s ease-in-out 2;
    }
  }
  @keyframes flicker {
    0%,
    100% {
      transform: scale(1);
    }
    40% {
      transform: scale(1.12, 1.2);
    }
    70% {
      transform: scale(0.94, 0.9);
    }
  }
</style>
