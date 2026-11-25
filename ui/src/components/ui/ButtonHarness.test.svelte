<script lang="ts">
  import Button from './Button.svelte';

  let {
    extra = {},
    ...props
  }: {
    extra?: Record<string, string>;
    onclick?: () => void;
    type?: 'button' | 'submit';
    busy?: boolean;
    href?: string;
    disabled?: boolean;
  } = $props();
</script>

<Button {...extra} {...props}>Label</Button>
