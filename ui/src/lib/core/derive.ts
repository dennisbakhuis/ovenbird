import type { MessageKey } from '$lib/i18n';
import type { ControlStatus, Decision, Signal, Snapshot } from './types';

export interface StatusLine {
  key: MessageKey;
  params: Record<string, string>;
}

export interface RoomView {
  signal: string | null;
  value: number | null;
  age: number | null;
  fresh: boolean;
  target: number | null;
}

/**
 * The room reading as the controller sees it: the signal named by the control status
 * (`control.room`), else the room input recorded in the latest decision. Never guessed from
 * signal names. The live snapshot value wins over the status value when the signal is in it.
 */
export function roomView(
  snapshot: Snapshot | null,
  control: ControlStatus | null,
  decision: Decision | null,
): RoomView {
  const record = decision?.record ?? null;
  const target = record?.controller_state['room_target_c'];
  const targetValue = typeof target === 'number' ? target : null;
  const status = control?.room ?? null;
  const ref = record?.inputs_used.find((input) => input.source === 'room') ?? null;
  const signalId = status?.signal ?? null;
  const live = signalId !== null ? snapshot?.signals[signalId] : undefined;
  if (live && typeof live.value === 'number') {
    return {
      signal: signalId,
      value: live.value,
      age: live.age,
      fresh: live.fresh,
      target: targetValue,
    };
  }
  if (status && typeof status.value === 'number') {
    return {
      signal: signalId,
      value: status.value,
      age: status.alive_s,
      fresh: status.fresh,
      target: targetValue,
    };
  }
  if (ref && typeof ref.value === 'number') {
    return {
      signal: signalId,
      value: ref.value,
      age: ref.age,
      fresh: ref.fresh,
      target: targetValue,
    };
  }
  return { signal: signalId, value: null, age: null, fresh: false, target: targetValue };
}

export type RoomTrust = 'ok' | 'reduced' | 'untrusted' | 'implausible';

export interface RoomTrustView {
  trust: RoomTrust;
  authority: number | null;
}

/**
 * How far the controller trusts the room value, from the control status (cooling authority and
 * cross-check of the latest decision) and the decision itself: `implausible` when the cross-check
 * disagrees, `untrusted` at zero authority, `reduced` below full authority, else `ok`.
 */
export function roomTrust(control: ControlStatus | null, decision: Decision | null): RoomTrustView {
  const status = control?.room ?? null;
  const fromState = decision?.record.controller_state['room_authority'];
  const raw = status?.authority ?? (typeof fromState === 'number' ? fromState : null);
  const authority = raw === null ? null : Math.min(Math.max(raw, 0), 1);
  if (status?.plausible === false || decision?.reason === 'room_implausible')
    return { trust: 'implausible', authority };
  if (authority === null) return { trust: 'ok', authority };
  if (authority < 0.005) return { trust: 'untrusted', authority };
  if (authority < 0.995) return { trust: 'reduced', authority };
  return { trust: 'ok', authority };
}

/**
 * Look up a signal by id.
 */
export function getSignal(snapshot: Snapshot | null, id: string | null): Signal | undefined {
  if (!snapshot || id === null) return undefined;
  return snapshot.signals[id];
}

/**
 * Build the one-line status from heat pump liveness and derived signals.
 */
export function statusLine(snapshot: Snapshot | null, formatKw: (w: number) => string): StatusLine {
  if (!snapshot) return { key: 'statusUnknown', params: {} };
  if (!snapshot.heishamon.alive) return { key: 'statusOffline', params: {} };
  const d = snapshot.derived;
  if (d['defrost_active']?.value === true) return { key: 'statusDefrost', params: {} };
  if (d['dhw_active']?.value === true) return { key: 'statusDhw', params: {} };
  const running = d['compressor_running']?.value;
  if (running === true) {
    const heat = d['heat_delivered_w']?.value;
    if (typeof heat === 'number')
      return { key: 'statusRunningHeat', params: { kw: formatKw(heat) } };
    return { key: 'statusRunning', params: {} };
  }
  if (running === false) return { key: 'statusIdle', params: {} };
  return { key: 'statusUnknown', params: {} };
}
