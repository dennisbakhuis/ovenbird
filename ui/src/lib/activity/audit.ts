import type { AuditEvent } from '$lib/core/types';

export interface AuditWords {
  version: (n: number) => string;
  rollbackTo: (n: number) => string;
  field: (id: string) => string;
  bool?: (value: boolean) => string;
  number?: (value: number) => string;
}

function show(value: unknown, words?: AuditWords): string {
  if (value === null || value === undefined) return '–';
  if (typeof value === 'boolean' && words?.bool) return words.bool(value);
  if (typeof value === 'number' && words?.number) return words.number(value);
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/**
 * A service actor ("admin from 192.168.1.20") as "admin · 192.168.1.20"; anything else as is.
 */
export function actorText(actor: string | null | undefined): string {
  if (!actor) return '';
  const match = /^(.+) from ([\w.:[\]-]+)$/.exec(actor);
  return match ? `${match[1]} · ${match[2]}` : actor;
}

/**
 * Actor as "name · address" instead of the service's "name from address".
 */
export function auditActor(event: Pick<AuditEvent, 'actor' | 'source_ip'>): string {
  const marker = ' from ';
  const index = event.actor.lastIndexOf(marker);
  if (index <= 0) return event.actor;
  const address = event.actor.slice(index + marker.length);
  if (event.source_ip && address !== event.source_ip) return event.actor;
  return `${event.actor.slice(0, index)} · ${address}`;
}

/**
 * One-line description of an audit event's detail object.
 */
export function auditDetail(event: AuditEvent, words: AuditWords): string {
  const detail = (event.detail ?? {}) as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof detail['rollback_to'] === 'number')
    parts.push(words.rollbackTo(detail['rollback_to']));
  else if (typeof detail['version'] === 'number') parts.push(words.version(detail['version']));
  const changed = detail['changed'];
  if (Array.isArray(changed)) {
    for (const item of changed as unknown[]) {
      if (typeof item === 'string') {
        parts.push(words.field(item));
        continue;
      }
      const { field, from, to } = item as { field?: unknown; from?: unknown; to?: unknown };
      parts.push(`${words.field(String(field))} ${show(from, words)} → ${show(to, words)}`);
    }
  }
  for (const key of ['reason', 'loss', 'path', 'status', 'comment', 'url']) {
    if (detail[key] !== undefined && detail[key] !== null && detail[key] !== '')
      parts.push(show(detail[key]));
  }
  const known = Object.fromEntries(
    Object.entries(detail).filter(([, value]) => value !== null && value !== undefined),
  );
  if (parts.length === 0 && Object.keys(known).length > 0) return show(known);
  return parts.join(' · ');
}
