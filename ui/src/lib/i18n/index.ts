import { activity as enActivity } from './en/activity';
import { advice as enAdvice } from './en/advice';
import { codes as enCodes } from './en/codes';
import { data as enData } from './en/data';
import { replay as enReplay } from './en/replay';
import { fields as enFields } from './en/fields';
import { help as enHelp } from './en/help';
import { home as enHome } from './en/home';
import { hotwater as enHotwater } from './en/hotwater';
import { integrations as enIntegrations } from './en/integrations';
import { insight as enInsight } from './en/insight';
import { pump as enPump } from './en/pump';
import { settings as enSettings } from './en/settings';
import { setpoint as enSetpoint } from './en/setpoint';
import { shell as enShell } from './en/shell';
import { system as enSystem } from './en/system';
import { shadow as enShadow } from './en/shadow';
import { trial as enTrial } from './en/trial';
import { house as enHouse } from './en/house';
import { houseControl as enHouseControl } from './en/houseControl';
import { houseGates as enHouseGates } from './en/houseGates';
import { houseModel as enHouseModel } from './en/houseModel';
import { weather as enWeather } from './en/weather';
import { activity as nlActivity } from './nl/activity';
import { advice as nlAdvice } from './nl/advice';
import { codes as nlCodes } from './nl/codes';
import { data as nlData } from './nl/data';
import { replay as nlReplay } from './nl/replay';
import { fields as nlFields } from './nl/fields';
import { help as nlHelp } from './nl/help';
import { home as nlHome } from './nl/home';
import { hotwater as nlHotwater } from './nl/hotwater';
import { integrations as nlIntegrations } from './nl/integrations';
import { insight as nlInsight } from './nl/insight';
import { pump as nlPump } from './nl/pump';
import { settings as nlSettings } from './nl/settings';
import { setpoint as nlSetpoint } from './nl/setpoint';
import { shell as nlShell } from './nl/shell';
import { system as nlSystem } from './nl/system';
import { shadow as nlShadow } from './nl/shadow';
import { trial as nlTrial } from './nl/trial';
import { house as nlHouse } from './nl/house';
import { houseControl as nlHouseControl } from './nl/houseControl';
import { houseGates as nlHouseGates } from './nl/houseGates';
import { houseModel as nlHouseModel } from './nl/houseModel';
import { weather as nlWeather } from './nl/weather';

export const en = {
  ...enShell,
  ...enHome,
  ...enSetpoint,
  ...enActivity,
  ...enSystem,
  ...enSettings,
  ...enFields,
  ...enWeather,
  ...enPump,
  ...enInsight,
  ...enCodes,
  ...enHelp,
  ...enAdvice,
  ...enShadow,
  ...enTrial,
  ...enHouse,
  ...enHouseModel,
  ...enHouseControl,
  ...enHouseGates,
  ...enData,
  ...enReplay,
  ...enHotwater,
  ...enIntegrations,
};

export type MessageKey = keyof typeof en;
export type Dictionary = Record<MessageKey, string>;

export const nl: Dictionary = {
  ...nlShell,
  ...nlHome,
  ...nlSetpoint,
  ...nlActivity,
  ...nlSystem,
  ...nlSettings,
  ...nlFields,
  ...nlWeather,
  ...nlPump,
  ...nlInsight,
  ...nlCodes,
  ...nlHelp,
  ...nlAdvice,
  ...nlShadow,
  ...nlTrial,
  ...nlHouse,
  ...nlHouseModel,
  ...nlHouseControl,
  ...nlHouseGates,
  ...nlData,
  ...nlReplay,
  ...nlHotwater,
  ...nlIntegrations,
};

export const dictionaries = { en, nl } as const;
export type Language = keyof typeof dictionaries;
export type LanguagePreference = Language | 'auto';

export const LANGUAGES: Language[] = ['en', 'nl'];

export type Params = Record<string, string | number>;

/**
 * Pick the best supported language from browser language tags.
 */
export function detectLanguage(browserLanguages: readonly string[]): Language {
  for (const tag of browserLanguages) {
    const base = tag.toLowerCase().split('-')[0];
    if (base === 'en' || base === 'nl') return base;
  }
  return 'en';
}

function fill(template: string, params: Params): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}

/**
 * Translate a key, substituting `{name}` placeholders.
 */
export function translate(language: Language, key: MessageKey, params: Params = {}): string {
  return fill(dictionaries[language][key], params);
}

/**
 * Translate a dynamic key (built from a server code); undefined when the key is unknown.
 */
export function translateOptional(
  language: Language,
  key: string,
  params: Params = {},
): string | undefined {
  const dictionary: Record<string, string> = dictionaries[language];
  const template = dictionary[key];
  return template === undefined ? undefined : fill(template, params);
}

/**
 * Translate a server code through `prefix + code`, falling back to the raw code.
 */
export function translateCode(
  language: Language,
  prefix: string,
  code: string,
  params: Params = {},
): string {
  return translateOptional(language, `${prefix}${code}`, params) ?? code;
}
