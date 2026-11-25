<!--
  FlipMeter: what would change the setpoint. A short scale of the flip input (room, outside or
  calculated water temperature) with the current value, the room target, the zone in which the
  issued setpoint stays and the flip point(s) where it steps to the next whole degree.

  Props: model (FlipModel from lib/explain), dwellLeftS (wait time still running, seconds).
  A11y: role="img" with the sentence that is also printed under the scale ("The setpoint becomes
  32 °C when the room falls to 21.6 °C (−0.3 K)").
-->
<script lang="ts">
  import { niceStep } from '$lib/core/chart';
  import { numberFormats, type FlipModel } from '$lib/setpoint/explain';
  import { settings, t } from '$lib/core/settings.svelte';

  let { model, dwellLeftS = 0 }: { model: FlipModel; dwellLeftS?: number } = $props();

  const fmt = $derived(numberFormats(settings.language));
  const digits = $derived(model.distance < 0.1 && model.subject !== 'water' ? 2 : 1);
  const due = $derived(model.distance < 0.005);

  const scale = $derived.by(() => {
    const values = [model.value, ...model.points.map((p) => p.at)];
    if (model.target !== null) values.push(model.target);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const pad = Math.max((hi - lo) * 0.25, model.subject === 'water' ? 0.5 : 0.3);
    return { min: lo - pad, max: hi + pad };
  });
  const pct = (v: number) => ((v - scale.min) / (scale.max - scale.min)) * 100;
  const ticks = $derived.by(() => {
    const step = niceStep((scale.max - scale.min) / 4);
    const out: number[] = [];
    for (let v = Math.ceil(scale.min / step) * step; v <= scale.max + 1e-9; v += step)
      out.push(Number(v.toFixed(6)));
    return out;
  });
  const zone = $derived.by(() => {
    const below = model.points.filter((p) => p.at <= model.value);
    const above = model.points.filter((p) => p.at > model.value);
    return {
      from: below.length ? (below[below.length - 1]?.at ?? scale.min) : scale.min,
      to: above.length ? (above[0]?.at ?? scale.max) : scale.max,
    };
  });

  const subject = $derived(t(`flipSubject_${model.subject}` as 'flipSubject_room'));
  const sentences = $derived(
    model.points.map((point) =>
      t(point.move < 0 ? 'flipFalls' : 'flipRises', {
        subject,
        setpoint: point.setpoint,
        at: fmt.plain(point.at, digits),
        move: fmt.signed(point.move, digits),
      }),
    ),
  );
  const summary = $derived(
    due
      ? t(dwellLeftS > 0 ? 'flipDueWait' : 'flipDue', { min: Math.ceil(dwellLeftS / 60) })
      : sentences.join(' '),
  );
  const edge = (p: number) => (p < 12 ? 'start' : p > 88 ? 'end' : 'mid');
</script>

<div class="flip" data-testid="flip-meter">
  <div class="scale" role="img" aria-label={summary}>
    <div class="track"></div>
    <div
      class="zone"
      style:left="{pct(zone.from)}%"
      style:width="{pct(zone.to) - pct(zone.from)}%"
    ></div>
    {#each ticks as tick (tick)}
      <span class="tick" style:left="{pct(tick)}%"></span>
    {/each}
    {#if model.target !== null}
      <span class="target" style:left="{pct(model.target)}%" title={t('flipTarget')}></span>
    {/if}
    {#each model.points as point, index (point.at)}
      <span class="point" style:left="{pct(point.at)}%"></span>
      <span
        class="point-label {model.points.length > 1
          ? index === 0
            ? 'end'
            : 'start'
          : edge(pct(point.at))}"
        style:left="{pct(point.at)}%"
      >
        {fmt.plain(point.at, digits)} → <strong>{point.setpoint} °C</strong>
      </span>
    {/each}
    <span class="value" style:left="{pct(model.value)}%"></span>
    <span class="value-label {edge(pct(model.value))}" style:left="{pct(model.value)}%"
      >{t('flipNow', { value: fmt.plain(model.value, 1) })}</span
    >
  </div>
  <p class="sentence" data-testid="flip-sentence">
    {#if due}
      {summary}
    {:else}
      {#each sentences as sentence, index (index)}<span>{sentence}</span>{/each}
    {/if}
  </p>
  {#if model.target !== null}
    <p class="legend">
      <i class="key target-key"></i>{t('flipTarget')}
      <i class="key zone-key"></i>{t('flipZone', { setpoint: model.stays })}
    </p>
  {/if}
</div>

<style>
  .flip {
    display: grid;
    gap: var(--space-2);
  }
  .scale {
    position: relative;
    height: 4.3rem;
    margin: 0 var(--space-1);
  }
  .track {
    position: absolute;
    left: 0;
    right: 0;
    top: 2.1rem;
    height: 6px;
    border-radius: var(--radius-xs);
    background: var(--surface-2);
    box-shadow: inset 0 0 0 1px var(--border);
  }
  .zone {
    position: absolute;
    top: 1.95rem;
    height: 10px;
    border-radius: var(--radius-m);
    background: color-mix(in srgb, var(--status-ok) 28%, transparent);
    border: 1px solid color-mix(in srgb, var(--status-ok) 60%, transparent);
  }
  .value-label {
    position: absolute;
    top: 0.2rem;
    font-size: var(--fs-caption);
    white-space: nowrap;
    transform: translateX(-50%);
  }
  .value-label {
    font-weight: var(--fw-semibold);
  }
  .tick {
    position: absolute;
    top: 2.5rem;
    width: 1px;
    height: 0.35rem;
    background: var(--chart-axis, var(--border));
  }
  .target {
    position: absolute;
    top: 1.6rem;
    height: 1.25rem;
    border-left: 2px dashed var(--series-comfort, var(--ok));
    transform: translateX(-1px);
  }
  .point {
    position: absolute;
    top: 1.95rem;
    width: 0.7rem;
    height: 0.7rem;
    background: var(--status-limited);
    transform: translate(-50%, 0) rotate(45deg);
    box-shadow: 0 0 0 2px var(--surface);
  }
  .point-label {
    position: absolute;
    top: 0.2rem;
    font-size: var(--fs-caption);
    white-space: nowrap;
    color: var(--status-limited);
    transform: translateX(-50%);
  }
  .value {
    position: absolute;
    top: 1.8rem;
    width: 0.95rem;
    height: 0.95rem;
    border-radius: 50%;
    background: var(--series-room, var(--text));
    box-shadow: 0 0 0 2px var(--surface);
    transform: translateX(-50%);
  }
  .value-label {
    top: 3rem;
  }
  .point-label.start,
  .value-label.start {
    transform: none;
  }
  .point-label.end,
  .value-label.end {
    transform: translateX(-100%);
  }
  .sentence {
    margin: 0;
    display: grid;
    gap: 0.15rem;
  }
  .legend {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-1) 0.4rem;
    font-size: var(--fs-caption);
    color: var(--muted);
  }
  .key {
    display: inline-block;
    width: 0.9rem;
    height: 0.6rem;
    margin-left: 0.4rem;
  }
  .key:first-child {
    margin-left: 0;
  }
  .target-key {
    width: 0;
    height: 0.8rem;
    border-left: 2px dashed var(--series-comfort, var(--ok));
  }
  .zone-key {
    border-radius: var(--radius-xs);
    background: color-mix(in srgb, var(--status-ok) 28%, transparent);
    border: 1px solid color-mix(in srgb, var(--status-ok) 60%, transparent);
  }
</style>
