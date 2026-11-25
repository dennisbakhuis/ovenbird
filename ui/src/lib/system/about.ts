import type { Schemas } from '$lib/core/types';
import { getOptional, postJson } from '$lib/core/api';

export type EnvelopeRuleState = Schemas['EnvelopeStateName'];
export type EnvelopeEvidence = Schemas['EnvelopeEvidence'];
export type SafetyNet = Schemas['SafetyNet'];
export type SystemAbout = Schemas['SystemAbout'];
export type NotifyTest = Schemas['NotifyTest'];
export type NotificationStatus = Schemas['NotificationStatus'];
export type NotifyHealthState = Schemas['NotifyHealth'];

/**
 * Facts about this installation; null when the backend does not have the endpoint.
 */
export function fetchAbout(signal?: AbortSignal): Promise<SystemAbout | null> {
  return getOptional<SystemAbout>('api/v1/system/about', signal);
}

/**
 * The notification channels; null when the backend does not have the endpoint.
 */
export function fetchNotifications(signal?: AbortSignal): Promise<NotificationStatus | null> {
  return getOptional<NotificationStatus>('api/v1/notifications/status', signal);
}

/**
 * Send a test notification now (operate).
 */
export function sendTestNotification(): Promise<{ test: NotifyTest; status: NotificationStatus }> {
  return postJson('api/v1/notifications/test', {});
}
