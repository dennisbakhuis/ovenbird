<!--
  Slider: a native range input for picking one of a few steps, with a visible label and a spoken
  value. The value is the step number; the caller maps it to what it means.

  Props: id, label, value, min (0), max, step (1), valuetext (spoken value), onchange(value),
  disabled, testid (on the input).
-->
<script lang="ts">
  interface Props {
    id: string;
    label: string;
    value: number;
    max: number;
    min?: number;
    step?: number;
    valuetext?: string;
    disabled?: boolean;
    onchange: (value: number) => void;
    testid?: string;
  }

  let {
    id,
    label,
    value,
    max,
    min = 0,
    step = 1,
    valuetext,
    disabled = false,
    onchange,
    testid,
  }: Props = $props();
</script>

<input
  {id}
  type="range"
  {min}
  {max}
  {step}
  {value}
  {disabled}
  aria-label={label}
  aria-valuetext={valuetext}
  data-testid={testid}
  oninput={(event) => onchange(Number(event.currentTarget.value))}
/>

<style>
  @layer components {
    input {
      width: 100%;
      min-height: var(--control-h);
      margin: 0;
      accent-color: var(--accent);
      cursor: pointer;
    }
    input:disabled {
      cursor: default;
      opacity: 0.6;
    }
  }
</style>
