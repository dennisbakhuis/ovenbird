import type { AlarmEvent, CommandEvent } from '$lib/core/types';

export interface CommandGroup {
  id: string;
  kind: string;
  value: number | null;
  steps: CommandEvent[];
  latest: CommandEvent;
  startedAt: string;
  durationS: number | null;
}

const TERMINAL = new Set(['verified', 'failed', 'refused', 'dropped', 'recorded']);
const RANK: Record<string, number> = {
  queued: 0,
  sent: 1,
  retry: 2,
  verified: 3,
  failed: 3,
  refused: 3,
  dropped: 3,
  recorded: 3,
};

/**
 * Whether a command status ends the lifecycle of a command.
 */
export function isTerminal(status: string): boolean {
  return TERMINAL.has(status);
}

function chronological(commands: CommandEvent[]): CommandEvent[] {
  return commands
    .map((command, index) => ({ command, index, at: Date.parse(command.at) }))
    .sort(
      (a, b) =>
        a.at - b.at ||
        (RANK[a.command.status] ?? 1) - (RANK[b.command.status] ?? 1) ||
        a.index - b.index,
    )
    .map((entry) => entry.command);
}

/**
 * Group journal rows into one entry per command, newest first. A command starts with its
 * `queued` row and ends with a terminal status; rows of the same kind and value in between
 * belong to it. The order of the input does not matter.
 */
export function groupCommands(commands: CommandEvent[]): CommandGroup[] {
  const open = new Map<string, CommandEvent[]>();
  const groups: CommandEvent[][] = [];

  for (const event of chronological(commands)) {
    const current = open.get(event.kind);
    const continues =
      current !== undefined && event.status !== 'queued' && current[0]?.value === event.value;
    if (continues) {
      current.push(event);
    } else {
      const fresh = [event];
      groups.push(fresh);
      open.set(event.kind, fresh);
    }
    if (isTerminal(event.status)) open.delete(event.kind);
  }

  return groups
    .map((steps): CommandGroup => {
      const first = steps[0] as CommandEvent;
      const latest = steps[steps.length - 1] as CommandEvent;
      const ended = isTerminal(latest.status);
      const seconds = (Date.parse(latest.at) - Date.parse(first.at)) / 1000;
      return {
        id: `${first.kind}-${first.at}-${steps.length}`,
        kind: first.kind,
        value: first.value,
        steps: [...steps].reverse(),
        latest,
        startedAt: first.at,
        durationS: ended && steps.length > 1 && Number.isFinite(seconds) ? seconds : null,
      };
    })
    .reverse();
}

export interface JournalPair {
  id: string;
  code: string;
  severity: AlarmEvent['severity'];
  from: string;
  to: string | null;
  endEvent: AlarmEvent['event'] | null;
  durationS: number | null;
  message: string;
  detail: Record<string, unknown>;
}

const OPENING = new Set(['raised', 'started']);

/**
 * Pair raise/clear (or start/expire/release) events of the same code into one row with a
 * duration, newest first. A pair without its end is still open.
 */
export function pairJournal(events: AlarmEvent[]): JournalPair[] {
  const sorted = [...events].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const open = new Map<string, JournalPair>();
  const pairs: JournalPair[] = [];
  for (const event of sorted) {
    if (OPENING.has(event.event)) {
      const pair: JournalPair = {
        id: `${event.code}-${event.at}`,
        code: event.code,
        severity: event.severity,
        from: event.at,
        to: null,
        endEvent: null,
        durationS: null,
        message: event.message,
        detail: event.detail ?? {},
      };
      pairs.push(pair);
      open.set(event.code, pair);
      continue;
    }
    const pair = open.get(event.code);
    if (pair) {
      pair.to = event.at;
      pair.endEvent = event.event;
      pair.durationS = Math.max(0, (Date.parse(event.at) - Date.parse(pair.from)) / 1000);
      open.delete(event.code);
    } else {
      pairs.push({
        id: `${event.code}-${event.at}-end`,
        code: event.code,
        severity: event.severity,
        from: event.at,
        to: event.at,
        endEvent: event.event,
        durationS: null,
        message: event.message,
        detail: event.detail ?? {},
      });
    }
  }
  return pairs.reverse();
}

/**
 * The hold history as CSV columns: start, end (empty while open), duration in seconds, the
 * reason, whether it was latched, the setting, ovenbird's value, the value seen on the pump, and
 * the service message.
 */
export function holdsTable(pairs: JournalPair[]): {
  header: string[];
  rows: (string | number | null)[][];
} {
  const field = (detail: Record<string, unknown>, key: string): string | number | null => {
    const value = detail[key];
    return typeof value === 'string' || typeof value === 'number' ? value : null;
  };
  return {
    header: [
      'from',
      'to',
      'duration_s',
      'reason',
      'latched',
      'setting',
      'ovenbird_value',
      'seen_value',
      'message',
    ],
    rows: [...pairs]
      .sort((a, b) => Date.parse(a.from) - Date.parse(b.from))
      .map((pair) => [
        pair.from,
        pair.to,
        pair.durationS === null ? null : Math.round(pair.durationS),
        field(pair.detail, 'reason'),
        pair.detail['latched'] === true
          ? 'true'
          : pair.detail['latched'] === false
            ? 'false'
            : null,
        field(pair.detail, 'setting'),
        field(pair.detail, 'ovenbird_value'),
        field(pair.detail, 'seen_value'),
        pair.message,
      ]),
  };
}
