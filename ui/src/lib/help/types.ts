/**
 * Contract for the in-app help: one topic per page or tab, in English and Dutch.
 *
 * Content lives in `content/<language>/<file>.ts`; each file exports `topic` (a HelpTopic)
 * or `glossary` (GlossaryEntry[]). Bodies use a small, safe markup that the drawer renders
 * without HTML:
 *
 * - paragraphs separated by a blank line; lines starting with "- " form a list;
 * - `**bold**`;
 * - `[[term]]` or `[[term|shown text]]` links a glossary entry by id;
 * - `[shown text](#/route/sub)` links another page of the app.
 *
 * Topics `start` and `switching` are guides, not pages: they have no route and are listed
 * first on the help index.
 *
 * A section's `target` names the element on the page that "Show me" points at: the page
 * marks it with `data-help="<target>"` (Card takes it as the `help` prop).
 *
 * Parts of an installation the app can hide (`HelpFeature`, such as hot water) are handled in
 * two ways, kept the same in EN and NL: a section, question or glossary entry about the part
 * itself carries `feature` and is left out while the part is hidden; one that only mentions it
 * in passing carries its text without the part under `without.<feature>`.
 */

export type HelpTopicId =
  | 'start'
  | 'switching'
  | 'home'
  | 'setpoint'
  | 'weather'
  | 'pump'
  | 'settings'
  | 'settings/curve'
  | 'settings/room'
  | 'settings/pump-duty'
  | 'settings/behaviour'
  | 'settings/quiet'
  | 'settings/stove'
  | 'settings/house'
  | 'settings/ha'
  | 'settings/mqtt'
  | 'settings/emitter'
  | 'settings/weather'
  | 'settings/versions'
  | 'activity'
  | 'activity/holds'
  | 'activity/commands'
  | 'activity/audit'
  | 'system'
  | 'system/signals'
  | 'system/shadow'
  | 'system/trial'
  | 'system/replay'
  | 'system/data'
  | 'more'
  | 'house';

export type ArtName =
  | 'home'
  | 'setpoint'
  | 'weather'
  | 'pump'
  | 'settings'
  | 'activity'
  | 'system'
  | 'welcome'
  | 'allQuiet'
  | 'weatherOff'
  | 'shadow'
  | 'noData';

export type HelpSectionKind = 'see' | 'do' | 'know';

/** A part of the installation the app hides when it is not used (Settings → Pump). */
export type HelpFeature = 'hotWater';

/** Text to show instead while a feature is hidden, per feature. */
export type Without<T> = Partial<Record<HelpFeature, Partial<T>>>;

export interface HelpSection {
  id: string;
  kind: HelpSectionKind;
  title: string;
  body: string;
  steps?: string[];
  target?: string;
  /** About this feature only: left out while it is hidden. */
  feature?: HelpFeature;
  /** The title, body or steps without a feature it mentions in passing. */
  without?: Without<Pick<HelpSection, 'title' | 'body' | 'steps'>>;
}

export interface HelpQuestion {
  id: string;
  q: string;
  a: string;
  /** About this feature only: left out while it is hidden. */
  feature?: HelpFeature;
  /** The question or answer without a feature it mentions in passing. */
  without?: Without<Pick<HelpQuestion, 'q' | 'a'>>;
}

export interface HelpTopic {
  id: HelpTopicId;
  title: string;
  lead: string;
  art: ArtName;
  sections: HelpSection[];
  questions?: HelpQuestion[];
  related?: HelpTopicId[];
  /** Other words people search for, such as Node-RED names; matched by search only. */
  aliases?: string[];
}

export interface GlossaryEntry {
  id: string;
  term: string;
  short: string;
  body?: string;
  related?: string[];
  /** Other words people search for, such as Node-RED names; matched by search only. */
  aliases?: string[];
  /** About this feature only: left out while it is hidden. */
  feature?: HelpFeature;
  /** The definition without a feature it mentions in passing. */
  without?: Without<Pick<GlossaryEntry, 'short' | 'body'>>;
}
