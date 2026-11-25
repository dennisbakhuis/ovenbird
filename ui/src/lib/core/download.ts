import { ApiError, failureKind, type FailureKind } from './api';

/**
 * The file name from a `Content-Disposition` header, or null.
 */
export function dispositionName(header: string | null): string | null {
  if (!header) return null;
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''));
    } catch {
      return null;
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  return plain?.[1]?.trim() ?? null;
}

/**
 * Add `format=csv` to an API path, keeping its other query parameters.
 */
export function csvPath(path: string): string {
  const [base = '', query = ''] = path.split('?', 2);
  const params = new URLSearchParams(query);
  params.set('format', 'csv');
  return `${base}?${params.toString()}`;
}

/**
 * Save a blob as a file through a temporary link.
 */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/**
 * Fetch an API download (a CSV export or the diagnostics bundle) and save it under the name the
 * service gives, or `fallback`. Resolves to null when saved, or the kind of failure.
 */
export async function downloadFrom(path: string, fallback: string): Promise<FailureKind | null> {
  try {
    const response = await fetch(path, { headers: { Accept: 'text/csv, application/json' } });
    if (!response.ok) return failureKind(new ApiError(path, response.status));
    const name = dispositionName(response.headers.get('Content-Disposition')) ?? fallback;
    saveBlob(await response.blob(), name);
    return null;
  } catch {
    return 'failed';
  }
}

/**
 * CSV text from a header and rows, quoting cells that need it and neutralising text a
 * spreadsheet would evaluate (a leading `=`, `+`, `-`, `@`).
 */
export function toCsv(header: string[], rows: (string | number | null | undefined)[][]): string {
  const cell = (value: string | number | null | undefined): string => {
    if (value === null || value === undefined) return '';
    let text = String(value);
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return /[",\n\r;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [header, ...rows].map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n';
}
