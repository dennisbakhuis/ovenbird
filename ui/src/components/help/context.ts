import { getContext, setContext } from 'svelte';
import type { GlossaryEntry } from '$lib/help/types';

export interface GlossaryAccess {
  get(id: string): GlossaryEntry | undefined;
  more(id: string): void;
}

const KEY = Symbol('help-glossary');

/** Give the help texts below access to the glossary. */
export function provideGlossary(access: GlossaryAccess): void {
  setContext(KEY, access);
}

/** The glossary provided by the drawer, if any. */
export function useGlossary(): GlossaryAccess | undefined {
  return getContext<GlossaryAccess | undefined>(KEY);
}
