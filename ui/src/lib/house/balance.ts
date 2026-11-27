import { ApiError, getJson, isMissing } from '$lib/core/api';
import { formatNum } from '$lib/core/chartSummary';
import type { Language, MessageKey, Params } from '$lib/i18n';
import type { HouseBalance } from './shapes';

export type Translate = (key: MessageKey, params?: Params) => string;

export type BalanceResult =
  { kind: 'ready'; data: HouseBalance } | { kind: 'no_model' } | { kind: 'absent' };

/**
 * The heat balance of the house now. `no_model`: the service has neither a learned model nor
 * enough facts for an estimate (404 `house_model_missing`); `absent`: an older service without
 * the endpoint.
 */
export async function fetchHouseBalance(signal?: AbortSignal): Promise<BalanceResult> {
  try {
    return {
      kind: 'ready',
      data: await getJson<HouseBalance>('api/v1/insight/house/balance', signal),
    };
  } catch (error) {
    if (error instanceof ApiError && error.code === 'house_model_missing')
      return { kind: 'no_model' };
    if (isMissing(error)) return { kind: 'absent' };
    throw error;
  }
}

export const MIN_ARROW_PX = 2;
export const MAX_ARROW_PX = 12;
export const STEADY_BELOW_W = 50;

/**
 * Stroke weight of a flow arrow in px: grows with the power, clamped; null for an unknown flow.
 */
export function flowWeight(watts: number | null): number | null {
  if (watts === null || !Number.isFinite(watts)) return null;
  const weight = MIN_ARROW_PX + 3.5 * (Math.abs(watts) / 1000);
  return Math.min(MAX_ARROW_PX, Math.round(weight * 10) / 10);
}

/**
 * A power for people: whole watts below 1 kW (rounded to 10 W), kW with one decimal above.
 */
export function formatPower(watts: number | null, lang: Language): string {
  if (watts === null || !Number.isFinite(watts)) return '–';
  const abs = Math.abs(watts);
  if (abs < 1000) return `${formatNum(Math.round(abs / 10) * 10, 0, lang)}\u202fW`;
  return `${formatNum(abs / 1000, 1, lang)}\u202fkW`;
}

export type StorageKind = 'storing' | 'giving' | 'steady' | 'unknown';

/**
 * What the building does with heat: storing it, giving it back, neither (within 50 W) or not
 * known (a wood-stove episode or an unknown input).
 */
export function storageKind(storageW: number | null): StorageKind {
  if (storageW === null) return 'unknown';
  if (Math.abs(storageW) < STEADY_BELOW_W) return 'steady';
  return storageW > 0 ? 'storing' : 'giving';
}

/**
 * Break a label into lines of at most `max` characters at spaces (a longer word stays whole).
 */
export function wrapLabel(text: string, max: number): string[] {
  const lines: string[] = [];
  let line = '';
  for (const word of text.split(' ')) {
    if (line && `${line} ${word}`.length > max) {
      lines.push(line);
      line = word;
    } else line = line ? `${line} ${word}` : word;
  }
  if (line) lines.push(line);
  return lines;
}

/**
 * The balance as one plain sentence, built from the numbers (never from service text).
 */
export function balanceSentence(balance: HouseBalance, tr: Translate, lang: Language): string {
  const { flows } = balance;
  const head =
    flows.loss_w === null
      ? tr('houseBalLossUnknown')
      : tr('houseBalLoss', { loss: formatPower(flows.loss_w, lang) });
  const gains = [
    flows.heat_pump_w === null
      ? tr('houseBalPumpUnknown')
      : tr(flows.heat_pump_w < 0 ? 'houseBalPumpNegative' : 'houseBalPump', {
          value: formatPower(flows.heat_pump_w, lang),
        }),
    flows.sun_w === null
      ? tr('houseBalSunUnknown')
      : tr('houseBalSun', { value: formatPower(flows.sun_w, lang) }),
    tr('houseBalInternal', { value: formatPower(flows.internal_w, lang) }),
  ];
  const list = `${gains[0]}, ${gains[1]} ${tr('houseAnd')} ${gains[2]}`;
  const kind = storageKind(flows.storage_w);
  let tail: string;
  if (flows.stove_active) tail = tr('houseBalTailStove');
  else if (kind === 'unknown') tail = tr('houseBalTailUnknown');
  else if (kind === 'steady') tail = tr('houseBalTailSteady');
  else
    tail = tr(kind === 'storing' ? 'houseBalTailStoring' : 'houseBalTailGiving', {
      value: formatPower(flows.storage_w, lang),
    });
  return tr('houseBalSentence', { head, list, tail });
}
