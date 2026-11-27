import type { Snapshot } from '$lib/core/types';

export type PumpStateKind = 'defrost' | 'dhw' | 'running' | 'idle' | 'off' | 'offline' | 'unknown';

/** Deice mode of a defrost: 1 reverse cycle (water pump running), 2 hot gas (water pump off). */
export type DeiceMode = 1 | 2;

export interface PumpStateInput {
  alive: boolean | null;
  defrost: boolean | null;
  dhw: boolean | null;
  running: boolean | null;
  pumpOn: boolean | null;
}

export interface PumpState {
  kind: PumpStateKind;
  frequencyHz: number | null;
  quiet: boolean;
  deice?: DeiceMode | null;
}

/**
 * Headline pump state by priority: defrost, then hot water, then running, then idle, then off.
 * An offline HeishaMon wins over everything (nothing is known), and a pump with no usable
 * signal at all is "unknown".
 */
export function pumpStateKind(input: PumpStateInput): PumpStateKind {
  if (input.alive === false) return 'offline';
  if (input.defrost === true) return 'defrost';
  if (input.dhw === true) return 'dhw';
  if (input.running === true) return 'running';
  if (input.pumpOn === true || input.running === false) return 'idle';
  if (input.pumpOn === false) return 'off';
  return 'unknown';
}

const asBool = (value: unknown): boolean | null => {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value > 0;
  return null;
};

/**
 * Deice mode of the running defrost as the service latched it; null outside a defrost, for a
 * model without a profile, and from an older service without `defrost` in the snapshot.
 */
export function deiceModeOf(snapshot: Snapshot | null): DeiceMode | null {
  const defrost = snapshot?.defrost;
  if (!defrost?.active) return null;
  return defrost.mode === 1 || defrost.mode === 2 ? defrost.mode : null;
}

/**
 * Pump state, compressor frequency, quiet-mode flag and, in a defrost, its deice mode from a
 * live snapshot.
 */
export function pumpStateOf(snapshot: Snapshot | null): PumpState {
  if (!snapshot) return { kind: 'unknown', frequencyHz: null, quiet: false, deice: null };
  const derived = snapshot.derived;
  const signals = snapshot.signals;
  const kind = pumpStateKind({
    alive: snapshot.heishamon.alive,
    defrost: asBool(derived['defrost_active']?.value),
    dhw: asBool(derived['dhw_active']?.value),
    running: asBool(derived['compressor_running']?.value),
    pumpOn: asBool(signals['main/Heatpump_State']?.value),
  });
  const hz = signals['main/Compressor_Freq']?.value;
  const quiet = signals['main/Quiet_Mode_Level']?.value;
  return {
    kind,
    frequencyHz: typeof hz === 'number' ? hz : null,
    quiet: typeof quiet === 'number' && quiet > 0,
    deice: kind === 'defrost' ? deiceModeOf(snapshot) : null,
  };
}
