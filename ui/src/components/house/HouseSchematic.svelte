<!--
  HouseSchematic: the house as the three-node model sees it, with the heat flows of the moment:
  heat pump (heating loop), sun, people and appliances and a wood stove going in, the loss to
  outside going out, and whether the building mass is storing heat or giving it back. Arrow weight
  grows with the flow (clamped); an unknown flow is drawn dashed and muted with "unknown", never
  as 0. Drawn left to right from 560 px of width, stacked below that; the SVG is sized in pixels
  from the measured width so text never scales down. Static.

  Props: balance (BalanceResult | null, null while loading), failed (the load failed),
  onfacts (opens the facts card; shown with the hint when there is nothing to draw).
  Honesty: a pill says "measured model", "estimate from your answers, not measured" or "still
  learning". A wood-stove episode makes the storage unknown (stove heat is not measured).
  A11y: the SVG is role="img" and its label is the generated sentence, which is also shown below.
-->
<script lang="ts">
  import { formatValue } from '$lib/core/chartSummary';
  import { formatDateTime } from '$lib/core/format';
  import { ICONS } from '$lib/core/icons';
  import { hotWater, textKey } from '$lib/core/hotWater.svelte';
  import { minus } from '$lib/core/minus';
  import { settings, t } from '$lib/core/settings.svelte';
  import {
    balanceSentence,
    flowWeight,
    formatPower,
    storageKind,
    wrapLabel,
    type BalanceResult,
  } from '$lib/house/balance';
  import Button from '$ui/Button.svelte';
  import Card from '$ui/Card.svelte';
  import Pill from '$ui/Pill.svelte';

  interface Props {
    balance: BalanceResult | null;
    failed?: boolean;
    onfacts?: () => void;
  }

  let { balance, failed = false, onfacts }: Props = $props();

  const lang = $derived(settings.language);
  let measured = $state(640);
  const width = $derived(Math.max(280, Math.min(measured, 900)));
  const wide = $derived(measured >= 560);

  const data = $derived(balance?.kind === 'ready' ? balance.data : null);
  const flows = $derived(data?.flows ?? null);
  const stove = $derived(flows?.stove_active === true);
  const kind = $derived(storageKind(flows?.storage_w ?? null));
  const NOTE_KEYS = {
    dhw_active: 'houseNote_dhw_active',
    defrost: 'houseNote_defrost',
    room_unknown: 'houseNote_room_unknown',
    outside_unknown: 'houseNote_outside_unknown',
    heat_unknown: 'houseNote_heat_unknown',
  } as const;
  const notes = $derived(
    (data?.notes ?? []).filter((note): note is keyof typeof NOTE_KEYS => note in NOTE_KEYS),
  );
  const sentence = $derived(data ? balanceSentence(data, t, lang) : '');
  const temp = (value: number | null) => minus(formatValue(value, '°C', 1, lang));

  const COLORS = {
    pump: 'var(--series-heat)',
    sun: 'var(--series-electric)',
    people: 'var(--series-dhw)',
    stove: 'var(--series-outlet)',
    loss: 'var(--series-outside)',
    store: 'var(--series-room)',
  } as const;

  interface Arrow {
    d: string;
    unknown: boolean;
    color: string;
  }

  /**
   * The outline of a block arrow from (x1, y1) to (x2, y2): a shaft of `weight` px and a head.
   * An unknown flow (weight null) is a thin outlined arrow.
   */
  function arrow(
    x1: number,
    y1: number,
    x2: number,
    y2: number,
    weight: number | null,
    color: string,
  ): Arrow {
    const w = weight ?? 4;
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const px = -uy;
    const py = ux;
    const headLen = Math.min(len * 0.6, Math.max(9, w * 1.1 + 5));
    const headHalf = Math.max(w / 2 + 3, 6);
    const bx = x2 - ux * headLen;
    const by = y2 - uy * headLen;
    const h = w / 2;
    const pts = [
      [x1 + px * h, y1 + py * h],
      [bx + px * h, by + py * h],
      [bx + px * headHalf, by + py * headHalf],
      [x2, y2],
      [bx - px * headHalf, by - py * headHalf],
      [bx - px * h, by - py * h],
      [x1 - px * h, y1 - py * h],
    ];
    const d = `M${pts.map(([x, y]) => `${Math.round((x ?? 0) * 10) / 10} ${Math.round((y ?? 0) * 10) / 10}`).join('L')}z`;
    return { d, unknown: weight === null, color };
  }

  const wPump = $derived(flowWeight(flows?.heat_pump_w ?? null));
  const wPeople = $derived(flowWeight(flows?.internal_w ?? null));
  const wLoss = $derived(flowWeight(flows?.loss_w ?? null));
  const wStore = $derived(flowWeight(flows?.storage_w ?? null));
  const power = (watts: number | null | undefined) =>
    watts === null || watts === undefined ? t('houseFlowUnknown') : formatPower(watts, lang);
  const charsFor = (boxWidth: number) => Math.max(8, Math.floor((boxWidth - 16) / 6.4));

  const TILE_H = 76;
  const GAP = 66;
  const boxW = $derived(Math.min(176, Math.max(116, width * 0.2)));
  const x0 = $derived(boxW + GAP);
  const x1 = $derived(width - boxW - GAP);
  const cx = $derived(width / 2);
  const ROW_A = 192;
  const ROW_B = 284;
  const APEX = 80;
  const EAVES = 132;
  const FLOOR = 326;
  const wideHeight = FLOOR + 12;
  const pumpBack = $derived((flows?.heat_pump_w ?? 0) < 0);
  const pumpArrow = $derived(
    pumpBack
      ? arrow(x0 - 2, ROW_A, boxW + 4, ROW_A, wPump, COLORS.pump)
      : arrow(boxW + 4, ROW_A, x0 - 2, ROW_A, wPump, COLORS.pump),
  );
  const wSun = $derived(flowWeight(flows?.sun_w ?? null));

  const sources = $derived([
    {
      id: 'pump',
      name: t('houseNodePump'),
      sub: t('houseNodePumpSub'),
      w: flows?.heat_pump_w ?? null,
      weight: wPump,
      color: COLORS.pump,
      icon: ICONS.pump,
    },
    {
      id: 'sun',
      name: t('houseNodeSun'),
      sub:
        data?.sun_wm2 != null
          ? t('houseSun', { value: formatValue(data.sun_wm2, '', 0, lang) })
          : '',
      w: flows?.sun_w ?? null,
      weight: wSun,
      color: COLORS.sun,
      icon: ICONS.sun,
    },
    {
      id: 'people',
      name: t('houseNodePeople'),
      sub: '',
      w: flows?.internal_w ?? null,
      weight: wPeople,
      color: COLORS.people,
      icon: ICONS.bolt,
    },
    ...(stove
      ? [
          {
            id: 'stove',
            name: t('houseNodeStove'),
            sub: t('houseFlowNotMeasured'),
            w: null as number | null,
            weight: 6 as number | null,
            color: COLORS.stove,
            icon: ICONS.flame,
          },
        ]
      : []),
  ]);

  const NARROW_TILE_H = 70;
  const narrowCols = $derived(sources.length);
  const narrowTileW = $derived((width - (narrowCols - 1) * 6) / narrowCols);
  const roofY = (x: number, apex: number, eaves: number) =>
    apex + ((eaves - apex) * Math.abs(x - width / 2)) / (width / 2);
  const N_TOP = NARROW_TILE_H + 34;
  const N_EAVES = N_TOP + 20;
  const N_ROOM = N_EAVES + 24;
  const N_MASS = N_ROOM + 52 + 28;
  const N_FLOOR = N_MASS + 52 + 10;
  const N_OUT = N_FLOOR + 40;
  const narrowHeight = N_OUT + 48 + 4;

  const lossFlow = $derived(
    wide
      ? arrow(x1 + 4, ROW_A, width - boxW - 4, ROW_A, wLoss, COLORS.loss)
      : arrow(cx, N_FLOOR + 2, cx, N_OUT - 4, wLoss, COLORS.loss),
  );
  const storeFlow = $derived.by(() => {
    const [top, bottom] = wide ? [ROW_A + 28 + 4, ROW_B - 28 - 4] : [N_ROOM + 52 + 4, N_MASS - 4];
    if (kind === 'steady') return null;
    if (kind === 'giving') return arrow(cx, bottom, cx, top, wStore, COLORS.store);
    return arrow(cx, top, cx, bottom, kind === 'unknown' ? null : wStore, COLORS.store);
  });
  const storageText = $derived(
    kind === 'unknown'
      ? t('houseStorage_unknown')
      : kind === 'steady'
        ? t('houseStorage_steady')
        : t(kind === 'storing' ? 'houseStorage_storing' : 'houseStorage_giving', {
            value: formatPower(flows?.storage_w ?? null, lang),
          }),
  );
  const storageLines = $derived(wrapLabel(storageText, wide ? 14 : 26));
</script>

<Card
  title={t('houseSchemTitle')}
  icon="house"
  testid="house-schematic"
  help="house.balance"
  span={12}
>
  {#if failed && balance === null}
    <p class="muted" data-testid="house-schematic-failed">{t('houseSchemFailed')}</p>
  {:else if balance === null}
    <p class="muted">{t('loading')}</p>
  {:else if data === null || flows === null}
    <p class="hint" data-testid="house-schematic-hint">
      {t('houseError_house_model_missing')}
      {#if onfacts}
        <Button variant="link" onclick={onfacts} data-testid="house-schematic-facts"
          >{t('houseSchemFactsLink')}</Button
        >
      {/if}
    </p>
  {:else}
    <p class="pills">
      <Pill
        tone={data.source === 'model' ? 'good' : 'warn'}
        testid="house-balance-source"
        title={data.source === 'model' ? t('houseSrcModel') : t('houseSrcEstimate')}
      >
        {data.source === 'model' ? t('houseSrcModel') : t('houseSrcEstimate')}
      </Pill>
      {#if data.source === 'model' && !data.credible}
        <Pill tone="warn" testid="house-balance-learning">{t('houseSrcLearning')}</Pill>
      {/if}
      <span class="caption">{t('houseSchemAsOf', { time: formatDateTime(data.at, lang) })}</span>
    </p>

    <div class="schem" bind:clientWidth={measured}>
      <svg
        {width}
        height={wide ? wideHeight : narrowHeight}
        viewBox="0 0 {width} {wide ? wideHeight : narrowHeight}"
        role="img"
        aria-label={sentence}
        data-testid="house-schematic-svg"
        data-layout={wide ? 'wide' : 'narrow'}
        data-storage={kind}
      >
        {#snippet tile(
          x: number,
          y: number,
          w: number,
          h: number,
          lines: string[],
          value: string | null,
          color: string,
          icon: string | null,
          unknown = false,
        )}
          <g class="tile" class:unknown>
            <rect
              class="box"
              {x}
              {y}
              width={w}
              height={h}
              rx="10"
              style:stroke={unknown ? undefined : color}
            />
            {#each lines as line, i (i)}
              <text class={i === 0 ? 'name' : 'cap'} x={x + 10} y={y + 18 + i * 15}>{line}</text>
            {/each}
            {#if value !== null}
              <text class="val" class:muted={unknown} x={x + 10} y={y + h - 10}>{value}</text>
            {/if}
            {#if icon}
              <g class="ico" transform="translate({x + w - 25} {y + 5}) scale(0.8)" style:color>
                <path d={icon} />
              </g>
            {/if}
          </g>
        {/snippet}
        {#snippet flow(a: Arrow)}
          {#if a.unknown}
            <path class="arrow-unknown" d={a.d} />
          {:else}
            <path d={a.d} fill={a.color} />
          {/if}
        {/snippet}

        {#if wide}
          <path class="house" d="M{x0} {EAVES} L{cx} {APEX} L{x1} {EAVES} V{FLOOR} H{x0} Z" />
          <text class="cap env" x={cx} y={EAVES + 20} text-anchor="middle"
            >{t('houseNodeEnvelope')}</text
          >

          <g
            class="ico sun"
            transform="translate({cx - 17} {6}) scale(1.4)"
            style:color={COLORS.sun}
          >
            <path d={ICONS.sun} />
          </g>
          {@render flow(arrow(cx, 44, cx, APEX - 2, wSun, COLORS.sun))}
          <text class="name" x={cx + 28} y="20"
            >{t('houseNodeSun')}{data.sun_wm2 !== null
              ? ` · ${t('houseSun', { value: formatValue(data.sun_wm2, '', 0, lang) })}`
              : ''}</text
          >
          <text class="val" class:muted={flows.sun_w === null} x={cx + 28} y="40"
            >{power(flows.sun_w)}</text
          >

          {@render tile(
            0,
            ROW_A - TILE_H / 2,
            boxW,
            TILE_H,
            [t('houseNodePump'), ...wrapLabel(t('houseNodePumpSub'), charsFor(boxW))],
            null,
            COLORS.pump,
            ICONS.pump,
          )}
          {@render flow(pumpArrow)}
          <text
            class="val gap"
            class:muted={flows.heat_pump_w === null}
            x={boxW + GAP / 2 + 1}
            y={ROW_A - (wPump ?? 4) / 2 - 12}
            text-anchor="middle">{power(flows.heat_pump_w)}</text
          >

          {@render tile(
            0,
            ROW_B - TILE_H / 2,
            boxW,
            TILE_H,
            wrapLabel(t('houseNodePeople'), charsFor(boxW)),
            null,
            COLORS.people,
            ICONS.bolt,
          )}
          {@render flow(arrow(boxW + 4, ROW_B, x0 - 2, ROW_B, wPeople, COLORS.people))}
          <text
            class="val gap"
            x={boxW + GAP / 2 + 1}
            y={ROW_B - (wPeople ?? 4) / 2 - 12}
            text-anchor="middle">{power(flows.internal_w)}</text
          >

          {@render tile(
            width - boxW,
            ROW_A - TILE_H / 2,
            boxW,
            TILE_H,
            [t('houseNodeOutside')],
            temp(data.outside_c),
            COLORS.loss,
            null,
            data.outside_c === null,
          )}
          {@render flow(lossFlow)}
          <text
            class="val gap"
            class:muted={flows.loss_w === null}
            x={x1 + GAP / 2 - 1}
            y={ROW_A - (wLoss ?? 4) / 2 - 12}
            text-anchor="middle">{power(flows.loss_w)}</text
          >
          <text
            class="cap gap"
            x={x1 + GAP / 2 - 1}
            y={ROW_A + (wLoss ?? 4) / 2 + 16}
            text-anchor="middle">{t('houseFlowLoss')}</text
          >

          {#if stove}
            {@render tile(
              width - boxW,
              ROW_B - TILE_H / 2,
              boxW,
              TILE_H,
              [t('houseNodeStove')],
              null,
              COLORS.stove,
              ICONS.flame,
              false,
            )}
            <text class="cap" x={width - boxW + 10} y={ROW_B - TILE_H / 2 + 33}
              >{t('houseFlowNotMeasured')}</text
            >
            {@render flow(arrow(width - boxW - 4, ROW_B, x1 + 2, ROW_B, null, COLORS.stove))}
          {/if}

          {@render tile(
            x0 + 14,
            ROW_A - 28,
            x1 - x0 - 28,
            56,
            [t('houseNodeRoom')],
            temp(data.room_c),
            COLORS.store,
            ICONS.thermometer,
            data.room_c === null,
          )}
          {@render tile(
            x0 + 14,
            ROW_B - 28,
            x1 - x0 - 28,
            56,
            [`${t('houseNodeMass')} · ${t('houseNodeMassSub')}`]
              .flatMap((l) => wrapLabel(l, charsFor(x1 - x0 - 28)))
              .slice(0, 2),
            null,
            COLORS.store,
            null,
          )}
          {#if storeFlow}{@render flow(storeFlow)}{/if}
          {#each storageLines as line, i (i)}
            <text class="cap" class:muted={kind === 'unknown'} x={cx + 16} y={ROW_A + 40 + i * 14}
              >{line}</text
            >
          {/each}
        {:else}
          {#each sources as source, i (source.id)}
            {@const x = i * (narrowTileW + 6)}
            {@const center = x + narrowTileW / 2}
            {@render tile(
              x,
              0,
              narrowTileW,
              NARROW_TILE_H,
              [
                ...wrapLabel(source.name, charsFor(narrowTileW)),
                ...(source.sub ? wrapLabel(source.sub, charsFor(narrowTileW)) : []),
              ],
              source.id === 'stove' ? null : power(source.w),
              source.color,
              null,
              source.w === null && source.id !== 'stove',
            )}
            {@render flow(
              arrow(
                center,
                NARROW_TILE_H + 4,
                center,
                roofY(center, N_TOP, N_EAVES) - 2,
                source.weight,
                source.color,
              ),
            )}
          {/each}

          <path
            class="house"
            d="M1 {N_EAVES} L{cx} {N_TOP} L{width - 1} {N_EAVES} V{N_FLOOR} H1 Z"
          />
          <text class="cap env" x={cx} y={N_EAVES + 16} text-anchor="middle"
            >{t('houseNodeEnvelope')}</text
          >
          {@render tile(
            14,
            N_ROOM,
            width - 28,
            56,
            [t('houseNodeRoom')],
            temp(data.room_c),
            COLORS.store,
            ICONS.thermometer,
            data.room_c === null,
          )}
          {@render tile(
            14,
            N_MASS,
            width - 28,
            56,
            [t('houseNodeMass'), t('houseNodeMassSub')],
            null,
            COLORS.store,
            null,
          )}
          {#if storeFlow}{@render flow(storeFlow)}{/if}
          {#each storageLines as line, i (i)}
            <text
              class="cap"
              class:muted={kind === 'unknown'}
              x={cx + 16}
              y={N_ROOM + 52 + 18 + i * 14}>{line}</text
            >
          {/each}

          {@render flow(lossFlow)}
          <text class="val" class:muted={flows.loss_w === null} x={cx + 16} y={N_FLOOR + 20}
            >{power(flows.loss_w)}</text
          >
          <text class="cap" x={cx + 16} y={N_FLOOR + 33}>{t('houseFlowLoss')}</text>
          {@render tile(
            cx - 80,
            N_OUT,
            160,
            56,
            [t('houseNodeOutside')],
            temp(data.outside_c),
            COLORS.loss,
            null,
            data.outside_c === null,
          )}
        {/if}
      </svg>
    </div>

    <p class="sentence" data-testid="house-balance-sentence">{sentence}</p>
    {#each notes as note (note)}
      <p class="caption note" data-testid="house-balance-note-{note}">
        {t(textKey(NOTE_KEYS[note], hotWater.shown))}
      </p>
    {/each}
  {/if}
</Card>

<style>
  .pills {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    margin: 0 0 var(--space-3);
  }
  .schem {
    width: 100%;
    min-width: 0;
  }
  svg {
    display: block;
    max-width: 100%;
    margin: 0 auto;
    font-family: inherit;
    overflow: visible;
  }
  .house {
    fill: var(--surface-2, var(--surface));
    stroke: var(--muted);
    stroke-width: 2;
    stroke-linejoin: round;
  }
  .box {
    fill: var(--surface);
    stroke-width: 1.5;
  }
  .unknown .box {
    stroke: var(--border);
    stroke-dasharray: 4 3;
  }
  .ico {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .arrow-unknown {
    fill: none;
    stroke: var(--muted);
    stroke-width: 1.5;
    stroke-dasharray: 4 3;
    stroke-linejoin: round;
  }
  text {
    fill: var(--text);
    font-variant-numeric: tabular-nums;
  }
  .name {
    font-size: var(--fs-caption);
    font-weight: var(--fw-semibold);
  }
  .cap {
    fill: var(--muted);
    font-size: var(--fs-caption);
  }
  .val {
    font-size: var(--fs-emph);
    font-weight: var(--fw-semibold);
  }
  .gap {
    font-size: var(--fs-caption);
  }
  .val.gap {
    font-size: var(--fs-body);
  }
  .muted {
    fill: var(--muted);
    font-weight: var(--fw-regular);
  }
  .sentence {
    margin: var(--space-3) 0 0;
  }
  .hint {
    margin: 0;
  }
  .note {
    margin: var(--space-1) 0 0;
  }
</style>
