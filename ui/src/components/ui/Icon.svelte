<script lang="ts">
  import { FILLS, ICONS, type IconName } from '$lib/core/icons';

  interface Props {
    name: IconName;
    size?: number | string;
    label?: string;
    class?: string;
  }

  let { name, size = 20, label, class: className = '' }: Props = $props();

  const fill = $derived(FILLS[name]);
</script>

<svg
  class="icon {className}"
  viewBox="0 0 24 24"
  width={size}
  height={size}
  fill="none"
  stroke="currentColor"
  stroke-width="1.5"
  stroke-linecap="round"
  stroke-linejoin="round"
  role={label ? 'img' : undefined}
  aria-label={label}
  aria-hidden={label ? undefined : 'true'}
  focusable="false"
  data-icon={name}
>
  {#if fill}<path d={fill} fill="currentColor" stroke="none" />{/if}
  {#if ICONS[name]}<path d={ICONS[name]} />{/if}
</svg>

<style>
  .icon {
    flex: none;
    display: inline-block;
    vertical-align: middle;
  }
</style>
