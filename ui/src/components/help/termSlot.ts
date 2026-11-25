/**
 * Lets a help text show an opened glossary definition below its paragraph instead of in
 * the middle of the sentence. HelpText provides it; Term without a slot unfolds in place.
 */
export interface TermSlot {
  openId: string | null;
  controls: string;
  toggle: (id: string) => void;
}
