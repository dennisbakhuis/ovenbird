/**
 * Loading the app's lazy parts (pages, the help drawer) so that a failed load is retried and a
 * tab that still runs an older build reloads itself.
 *
 * Every build gives the lazy files new names. A tab opened before a rebuild still asks for the
 * old names and gets 404; a load that failed while the service restarted would otherwise be
 * remembered for good, leaving that page or menu blank until a manual reload.
 */
import { STORAGE_PREFIX } from './brand';

const RELOAD_KEY = `${STORAGE_PREFIX}staleReloadAt`;
const RELOAD_SPACING_MS = 30_000;

/**
 * Wrap a loader so concurrent calls share one load and a failed load is tried again next time.
 */
export function retrying<T>(
  load: () => Promise<T>,
  onError: (error: unknown) => void = () => void recover(),
) {
  let pending: Promise<T> | undefined;
  return (): Promise<T> =>
    (pending ??= load().catch((error: unknown) => {
      pending = undefined;
      onError(error);
      throw error;
    }));
}

/**
 * The app's entry script in this tab (the last module script), or null when there is none.
 */
function runningEntry(doc: Document): string | null {
  const scripts = doc.querySelectorAll<HTMLScriptElement>('script[type="module"][src]');
  const script = scripts[scripts.length - 1];
  return script ? new URL(script.src, doc.baseURI).pathname : null;
}

/**
 * The entry script the service serves now, or null when the page cannot be fetched.
 */
async function servedEntry(base: string): Promise<string | null> {
  try {
    const response = await fetch(base, { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) return null;
    const html = await response.text();
    const sources = [...html.matchAll(/<script[^>]*type="module"[^>]*src="([^"]+)"/g)];
    const last = sources[sources.length - 1]?.[1];
    return last ? new URL(last, base).pathname : null;
  } catch {
    return null;
  }
}

function reloadedRecently(now: number): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY) ?? 0);
    if (now - last < RELOAD_SPACING_MS) return true;
    sessionStorage.setItem(RELOAD_KEY, String(now));
  } catch {
    return false;
  }
  return false;
}

/**
 * Reload the tab when the service now serves a different build than the one running here.
 */
export async function recover(): Promise<boolean> {
  if (typeof document === 'undefined') return false;
  const running = runningEntry(document);
  if (!running) return false;
  const served = await servedEntry(new URL('./', document.baseURI).href);
  if (!served || served === running) return false;
  if (reloadedRecently(Date.now())) return false;
  location.reload();
  return true;
}
