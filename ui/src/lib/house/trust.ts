import type { MessageKey, Params } from '$lib/i18n';
import type {
  AtBound,
  ConstraintCost,
  Excitation,
  GateName,
  GateNeed,
  GateSource,
  HouseGates,
  HouseInsight,
  ModelGate,
  Revalidation,
  Validation,
} from './house';
import type { BoundRow } from './settings';

export type Translate = (key: MessageKey, params?: Params) => string;
export type Format = (value: number, digits?: number) => string;

export const GATE_NAMES = ['heat_loss', 'dynamics', 'sun'] as const;

/** What each gate guards, for the plain line under its name. */
export const GATE_USES: Record<GateName, MessageKey> = {
  heat_loss: 'houseGateUses_heat_loss',
  dynamics: 'houseGateUses_dynamics',
  sun: 'houseGateUses_sun',
};

export interface GateRow {
  name: GateName;
  ok: boolean;
  source: GateSource;
  needs: GateNeed[];
  legacy: boolean;
}

/**
 * The three gates in a fixed order (heat loss, room dynamics, sun response); a service without
 * the gates gives nothing.
 */
export function gateRows(gates: HouseGates | null | undefined): GateRow[] {
  if (!gates) return [];
  return GATE_NAMES.map((name) => {
    const gate = gates[name];
    return {
      name,
      ok: gate.ok,
      source: gate.source,
      needs: gate.needed,
      legacy: gate.needed.includes('legacy_model'),
    };
  });
}

/**
 * The amounts still missing for `more_heating_days` and `more_outside_spread`, from the
 * credibility shortfall; empty when the model does not report them.
 */
function shortfall(house: HouseInsight | null | undefined): Record<string, number> {
  const needed = house?.credibility?.needed;
  return {
    more_heating_days: needed && needed.heating_days > 0 ? Math.ceil(needed.heating_days) : 0,
    more_outside_spread:
      needed && needed.outside_span_k > 0 ? Math.round(needed.outside_span_k * 10) / 10 : 0,
  };
}

/**
 * One plain sentence for a gate need code. The two weather codes name the amount when the model
 * reports it.
 */
export function gateNeedText(
  code: GateNeed,
  tr: Translate,
  format: Format,
  house?: HouseInsight | null,
): string {
  if (code === 'more_heating_days') {
    const amount = shortfall(house)[code] ?? 0;
    return amount > 0
      ? tr(
          amount === 1
            ? 'houseGateNeedAmountOne_more_heating_days'
            : 'houseGateNeedAmount_more_heating_days',
          {
            n: amount,
          },
        )
      : tr('houseGateNeed_more_heating_days');
  }
  if (code === 'more_outside_spread') {
    const amount = shortfall(house)[code] ?? 0;
    return amount > 0
      ? tr('houseGateNeedAmount_more_outside_spread', { n: format(amount, 1) })
      : tr('houseGateNeed_more_outside_spread');
  }
  return tr(`houseGateNeed_${code}` as MessageKey);
}

/**
 * The reasons a gate does not pass, one sentence per need code; the service's own message when it
 * names no code, nothing for a gate that passes.
 */
export function gateReasons(
  gate: ModelGate | undefined,
  tr: Translate,
  format: Format,
  house?: HouseInsight | null,
): string[] {
  if (!gate || gate.ok) return [];
  if (gate.needed.length === 0) return gate.message ? [gate.message] : [tr('houseGateNeedUnknown')];
  return gate.needed.map((code) => gateNeedText(code, tr, format, house));
}

/**
 * How many of the three gates pass; 0 without gates.
 */
export function gatesPassing(gates: HouseGates | null | undefined): number {
  return gateRows(gates).filter((row) => row.ok).length;
}

export interface CheckRow {
  id: string;
  ok: boolean;
  value: number | null;
  limit: number | null;
}

/**
 * The per-check results of one gate (value against limit) from the learner's detail, in the
 * order the learner wrote them; empty for a model without that detail.
 */
export function checkRows(detail: { checks?: Record<string, unknown> } | undefined): CheckRow[] {
  return Object.entries(detail?.checks ?? {}).flatMap(([id, raw]) => {
    if (typeof raw !== 'object' || raw === null) return [];
    const check = raw as { ok?: unknown; value?: unknown; limit?: unknown };
    if (typeof check.ok !== 'boolean') return [];
    return [
      {
        id,
        ok: check.ok,
        value: typeof check.value === 'number' ? check.value : null,
        limit: typeof check.limit === 'number' ? check.limit : null,
      },
    ];
  });
}

export type ProgressKind = 'heating_days' | 'outside_range_k';

export interface Progress {
  kind: ProgressKind;
  have: number;
  need: number;
}

/**
 * How far the fit window is on the way to the heating weather it needs: heating days and the
 * spread of their outside temperatures. Empty when the weather is enough or the model does not
 * report it.
 */
export function excitationProgress(excitation: Excitation | null | undefined): Progress[] {
  if (!excitation || excitation.excited) return [];
  const { rules } = excitation;
  return [
    { kind: 'heating_days' as const, have: excitation.heating_days, need: rules.heating_days },
    {
      kind: 'outside_range_k' as const,
      have: excitation.outside_range_k,
      need: rules.outside_range_k,
    },
  ].filter((item) => item.need > 0 && item.have < item.need);
}

/**
 * The share of a progress item that is done, 0 to 1.
 */
export function progressShare(item: Progress): number {
  return item.need > 0 ? Math.min(1, Math.max(0, item.have / item.need)) : 1;
}

/**
 * The reasons a re-validation gives, in our own words where we know them (no skill over "no
 * change") and the service's words otherwise.
 */
export function revalidationReasons(revalidation: Revalidation, tr: Translate): string {
  if (revalidation.skill !== null && revalidation.skill <= 0) return tr('houseReasonNoSkill');
  return revalidation.reasons.join('; ');
}

/**
 * The gates a re-validation's own judgement does not pass, in the fixed order; empty when it
 * passes all of them or comes from a learner without gates.
 */
export function failingGates(revalidation: Revalidation): GateName[] {
  const gates = revalidation.gates;
  if (!gates) return [];
  return GATE_NAMES.filter((name) => !gates[name].ok);
}

/**
 * How many of the three gates a re-validation passes; null from a learner without gates.
 */
export function revalidationPassing(revalidation: Revalidation): number | null {
  const gates = revalidation.gates;
  return gates ? GATE_NAMES.filter((name) => gates[name].ok).length : null;
}

/**
 * "Last checked against new data on …: still good" or "… no longer trusted because …".
 */
export function revalidationSentence(
  revalidation: Revalidation,
  tr: Translate,
  time: string,
): string {
  const failing = failingGates(revalidation);
  if (failing.length > 0)
    return tr('houseRevalGates', {
      time,
      uses: failing
        .map((name) => tr(`houseGateName_${name}` as MessageKey).toLowerCase())
        .join(', '),
    });
  if (revalidation.credible) return tr('houseRevalGood', { time });
  const reasons = revalidationReasons(revalidation, tr);
  return reasons ? tr('houseRevalBad', { time, reasons }) : tr('houseRevalBadPlain', { time });
}

/**
 * The error of a re-validation against "the room stays as it is", both over 24 h; null when
 * either is unknown.
 */
export function revalidationErrors(
  revalidation: Revalidation,
  tr: Translate,
  format: Format,
): string | null {
  if (revalidation.room_rmse_k === null || revalidation.persistence_room_rmse_k === null)
    return null;
  return tr('houseRevalErrors', {
    model: format(revalidation.room_rmse_k, 2),
    persistence: format(revalidation.persistence_room_rmse_k, 2),
  });
}

/**
 * The errors with and without the owner's limits when the limits cost accuracy; null otherwise.
 */
export function constraintSentence(
  validation: Validation | null | undefined,
  tr: Translate,
  format: Format,
): string | null {
  const cost: ConstraintCost | null | undefined = validation?.constraint_cost;
  if (!validation || !cost?.worse) return null;
  const constrained = validation.held_out_room_rmse_k ?? validation.challenger_room_rmse_k;
  const free = validation.unconstrained_room_rmse_k;
  if (typeof constrained !== 'number' || typeof free !== 'number')
    return tr('houseConstraintWorsePlain');
  return tr('houseConstraintWorse', { with: format(constrained, 2), without: format(free, 2) });
}

const PARAMETER_ROW: Record<string, BoundRow['id']> = {
  h_air_out: 'ua',
  time_constant_h: 'tau',
  solar_aperture_m2: 'aperture',
  q_int_w: 'gain',
};

/**
 * The bound row (heat loss, time constant, solar aperture, internal gains) a learned parameter
 * belongs to; null for the model's inner parameters.
 */
export function boundRowOf(parameter: string): BoundRow['id'] | null {
  return PARAMETER_ROW[parameter] ?? null;
}

/**
 * The owner's own limit a quantity ended at, if any.
 */
export function ownerBound(atBound: AtBound[] | undefined, row: BoundRow['id']): AtBound | null {
  return (
    (atBound ?? []).find(
      (entry) => entry.kind === 'owner' && boundRowOf(entry.parameter) === row,
    ) ?? null
  );
}

/**
 * Values that ended at the edge of the model's own range (not a setting of the owner's).
 */
export function structuralBounds(atBound: AtBound[] | undefined): AtBound[] {
  return (atBound ?? []).filter((entry) => entry.kind === 'structural');
}
