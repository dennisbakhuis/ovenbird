import { getOptional } from '$lib/core/api';
import { formatNum } from '$lib/core/chartSummary';
import { formatClock } from '$lib/core/format';
import type { Point } from '$lib/core/chart';
import type { Language, MessageKey, Params } from '$lib/i18n';
import { localDay } from './settings';
import type { HouseControl, PlanEvaluation, PlanHistory } from './shapes';

export type Translate = (key: MessageKey, params?: Params) => string;

export const SHIFT_MIN_K = 0.05;

/**
 * The control state of the house model: how the controller uses it, why it may not act and what it
 * did lately. Null on an older service without the endpoint.
 */
export const fetchHouseControl = (signal?: AbortSignal) =>
  getOptional<HouseControl>('api/v1/insight/house/control', signal);

/** Why-the-planner-may-not-act codes, the ones the owner has to act on first. */
export const BLOCK_ORDER = [
  'weather_off',
  'model_missing',
  'model_not_credible',
  'model_error_high',
  'model_stale',
  'forecast_stale',
  'room_untrusted',
  'stove_active',
  'stove_tail',
] as const;

/**
 * The block codes most important first; a code this version does not know goes last.
 */
export function sortBlocks(blocks: readonly string[]): string[] {
  const rank = (code: string) => {
    const index = (BLOCK_ORDER as readonly string[]).indexOf(code);
    return index === -1 ? BLOCK_ORDER.length : index;
  };
  return [...blocks].sort((a, b) => rank(a) - rank(b));
}

const num = (value: number, lang: Language, digits = 1) => formatNum(Math.abs(value), digits, lang);

/**
 * One sentence on what the planner does now or would do (shadow): a shift with its end, or why
 * there is none.
 */
export function shiftSentence(control: HouseControl, tr: Translate, lang: Language): string {
  const { now, use } = control;
  if (use !== 'off' && !control.verdict.ok) return tr('houseCtlStatus_blocked');
  if (now === null) return tr(use === 'off' ? 'houseCtlNowOff' : 'houseCtlNowNever');
  if (now.status !== 'issued') return tr(`houseCtlStatus_${now.status}` as MessageKey);
  if (Math.abs(now.offset_k) < SHIFT_MIN_K) return tr('houseCtlStatus_inside_dead_zone');
  const direction = now.offset_k < 0 ? 'down' : 'up';
  const params = {
    k: num(now.offset_k, lang),
    until: now.valid_until ? formatClock(now.valid_until, lang) : tr('houseCtlUntilNext'),
  };
  if (use === 'on' && !now.applied) return tr(`houseCtlHeld_${direction}`, params);
  return tr(`houseCtlShift_${use === 'on' ? 'is' : 'would'}_${direction}`, params);
}

type Cause = 'sun' | 'mild' | 'cold' | 'lessSun';

function warmCause(now: PlanEvaluation): Cause {
  return (now.solar_k ?? 0) >= Math.max(now.outside_k ?? 0, 0) ? 'sun' : 'mild';
}

function coolCause(now: PlanEvaluation): Cause {
  return (now.outside_k ?? 0) <= Math.min(now.solar_k ?? 0, 0) ? 'cold' : 'lessSun';
}

/**
 * The expected warming and cooling of the room over the horizon in plain words, with the main
 * cause and the time of the peak; a calm sentence when neither is notable.
 */
export function effectSentence(control: HouseControl, tr: Translate, lang: Language): string {
  const { now, bounds } = control;
  if (now === null || (control.use !== 'off' && !control.verdict.ok)) return '';
  const hours = bounds.horizon_h;
  const parts: string[] = [];
  const rise = Math.abs(now.rise_k ?? 0);
  const fall = Math.abs(now.fall_k ?? 0);
  if (rise >= SHIFT_MIN_K)
    parts.push(
      tr('houseCtlRise', {
        h: hours,
        cause: tr(`houseCtlCause_${warmCause(now)}` as MessageKey),
        k: num(rise, lang),
        at: now.rise_at ? formatClock(now.rise_at, lang) : '–',
      }),
    );
  if (fall >= SHIFT_MIN_K)
    parts.push(
      tr(parts.length > 0 ? 'houseCtlFallThen' : 'houseCtlFall', {
        h: hours,
        cause: tr(`houseCtlCause_${coolCause(now)}` as MessageKey),
        k: num(fall, lang),
        at: now.fall_at ? formatClock(now.fall_at, lang) : '–',
      }),
    );
  return parts.length > 0 ? parts.join(' ') : tr('houseCtlEffectNone', { h: hours });
}

export interface PlanSummary {
  evaluated: number;
  shifted: number;
  applied: number;
  downDays: number;
  upDays: number;
  maxDownK: number;
  maxUpK: number;
  stepS: number;
}

/**
 * What the computed shift did over the history: how many quarter-hours were evaluated, shifted
 * and applied, on how many local days it lowered or raised the target and by how much at most.
 */
export function summarisePlan(history: PlanHistory): PlanSummary {
  const down = new Set<string>();
  const up = new Set<string>();
  const summary: PlanSummary = {
    evaluated: 0,
    shifted: 0,
    applied: 0,
    downDays: 0,
    upDays: 0,
    maxDownK: 0,
    maxUpK: 0,
    stepS: history.step_s,
  };
  for (const [at, offset, applied] of history.points) {
    if (offset === null) continue;
    summary.evaluated += 1;
    if (Math.abs(offset) < SHIFT_MIN_K) continue;
    summary.shifted += 1;
    if (applied === 1) summary.applied += 1;
    const day = localDay(Date.parse(at));
    if (offset < 0) {
      down.add(day);
      summary.maxDownK = Math.max(summary.maxDownK, -offset);
    } else {
      up.add(day);
      summary.maxUpK = Math.max(summary.maxUpK, offset);
    }
  }
  summary.downDays = down.size;
  summary.upDays = up.size;
  return summary;
}

/**
 * The summary as the sentence that also serves as the chart's text alternative.
 */
export function planSummarySentence(
  summary: PlanSummary,
  days: number,
  tr: Translate,
  lang: Language,
): string {
  if (summary.evaluated === 0) return tr('houseCtlSumNone', { n: days });
  const applied = summary.shifted > 0 && summary.applied * 2 >= summary.shifted;
  if (summary.shifted === 0)
    return tr(applied ? 'houseCtlSumFlat_did' : 'houseCtlSumFlat_would', { n: days });
  const tense = applied ? 'did' : 'would';
  const dayText = (n: number) => tr(n === 1 ? 'houseCtlDay_one' : 'houseCtlDay_other', { n });
  const sentences: string[] = [];
  const lead = () => sentences.length === 0;
  if (summary.downDays > 0)
    sentences.push(
      tr(`houseCtlSumDown_${tense}_${lead() ? 'first' : 'next'}` as MessageKey, {
        n: days,
        days: dayText(summary.downDays),
        k: formatNum(summary.maxDownK, 1, lang),
      }),
    );
  if (summary.upDays > 0)
    sentences.push(
      tr(`houseCtlSumUp_${tense}_${lead() ? 'first' : 'next'}` as MessageKey, {
        n: days,
        days: dayText(summary.upDays),
        k: formatNum(summary.maxUpK, 1, lang),
      }),
    );
  if (summary.applied > 0 && summary.applied < summary.shifted)
    sentences.push(
      tr('houseCtlSumApplied', {
        h: formatNum((summary.applied * summary.stepS) / 3600, 1, lang),
      }),
    );
  return sentences.join(' ');
}

export interface PlanLines {
  computed: Point[];
  applied: Point[];
}

/**
 * Chart points: the computed shift wherever it was computed and the same value again where the
 * controller applied it; gaps (not computed) are left out.
 */
export function planLines(history: PlanHistory): PlanLines {
  const computed: Point[] = [];
  const applied: Point[] = [];
  for (const [at, offset, flag] of history.points) {
    if (offset === null) continue;
    const t = Date.parse(at);
    computed.push([t, offset]);
    if (flag === 1) applied.push([t, offset]);
  }
  return { computed, applied };
}
