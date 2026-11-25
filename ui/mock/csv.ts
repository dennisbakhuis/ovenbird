import type { ServerResponse } from 'node:http';

const COLUMNS = {
  history: ['signal', 'unit', 'at', 'value'],
  decisions: [
    'at',
    'controller',
    'mode',
    'ladder',
    'reason',
    'setpoint',
    'config_version',
    'note',
    'arbiter',
    'commands',
  ],
  commands: ['at', 'kind', 'value', 'status', 'attempt', 'topic', 'payload', 'detail'],
  alarms: ['at', 'code', 'severity', 'event', 'message', 'detail'],
  audit: ['at', 'actor', 'source_ip', 'action', 'detail'],
} as const;

export type CsvExport = keyof typeof COLUMNS;

/**
 * One CSV cell as the service writes it: nested values as compact JSON, text that a spreadsheet
 * would evaluate prefixed with `'`, quoted when needed.
 */
export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  let text = typeof value === 'object' ? JSON.stringify(value) : String(value);
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * The CSV text of an export: a header row, then one row per record.
 */
export function toCsv(name: CsvExport, rows: readonly object[]): string {
  const columns = COLUMNS[name];
  const lines = [columns.join(',')];
  for (const row of rows)
    lines.push(
      columns.map((column) => csvCell((row as Record<string, unknown>)[column])).join(','),
    );
  return `${lines.join('\r\n')}\r\n`;
}

/**
 * Send an export as the service does: `text/csv` with an attachment file name.
 */
export function sendCsv(
  res: ServerResponse,
  name: CsvExport,
  from: number,
  rows: readonly object[],
): void {
  const stamp = new Date(from).toISOString().slice(0, 16).replace(/[:]/g, '');
  res.statusCode = 200;
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename="ovenbird-${name}-${stamp}.csv"`);
  res.end(toCsv(name, rows));
}
