import { describe, expect, it } from 'vitest';
import codes from '$mock/fixtures/codes.json';
import { dictionaries, translateOptional, type Language } from '.';

const languages: Language[] = ['en', 'nl'];

const PREFIXES: Record<string, string[]> = {
  reason: ['reason_', 'explain_reason_'],
  binding: ['binding_', 'explain_binding_'],
  ladder: ['ladder_'],
  term: ['term_'],
  alarm: ['alarm_'],
  alarm_event: ['event_'],
  alarm_journal: ['alarm_'],
  severity: ['severity_'],
  command_status: ['cmd_'],
  monitor_status: ['monitorStatus_'],
  audit_action: ['audit_'],
  mode: ['modeName_'],
  config_group: ['group_'],
  config_origin: ['origin_'],
  config_source: ['source_'],
  validation_error: ['check_'],
  validation_warning: ['check_'],
  pump_owner: ['pumpOwner_'],
  pump_refusal: ['pumpRefusal_'],
  pump_setting: ['pumpSetting_'],
  weather_check: ['state_'],
  envelope_rule_state: ['envelopeRule_'],
  release_item_status: ['releaseItem_'],
  release_refusal: ['releaseRefusal_'],
  trial_check: ['trialCheck_'],
  trial_check_status: ['trialStatus_'],
  trial_criterion: ['trialCriterion_'],
  trial_phase: ['trialGroup_'],
  trial_summary_state: ['trialState_'],
  release_outcome: ['trialOutcome_'],
  snapshot_origin: ['snapshotOrigin_'],
  snapshot_capture_refusal: ['captureRefusal_'],
  notify_health: ['notifyHealth_'],
  ha_test_error: ['haTest_'],
  mqtt_test_error: ['mqttTest_'],
};

describe('i18n completeness', () => {
  it('has the same keys in EN and NL', () => {
    expect(Object.keys(dictionaries.nl).sort()).toEqual(Object.keys(dictionaries.en).sort());
  });

  it('has no empty texts and the same placeholders in both languages', () => {
    const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const [key, en] of Object.entries(dictionaries.en)) {
      const nl = (dictionaries.nl as Record<string, string>)[key] ?? '';
      expect(en.trim().length, key).toBeGreaterThan(0);
      expect(nl.trim().length, key).toBeGreaterThan(0);
      expect(placeholders(nl), key).toEqual(placeholders(en));
    }
  });

  it.each(languages)('translates every server code in %s', (language) => {
    const record = codes as Record<string, string[]>;
    const missing: string[] = [];
    for (const [category, prefixes] of Object.entries(PREFIXES)) {
      for (const code of record[category] ?? []) {
        for (const prefix of prefixes) {
          if (translateOptional(language, `${prefix}${code}`) === undefined)
            missing.push(`${prefix}${code}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it('covers every category of the generated codes file', () => {
    expect(Object.keys(codes).filter((c) => !(c in PREFIXES) && c !== 'config_tier')).toEqual([]);
  });

  it('keeps the owner-fixed Dutch terms', () => {
    const joined = Object.values(dictionaries.nl).join(' ').toLowerCase();
    for (const term of [
      'stooklijn',
      'ruimtecorrectie',
      'dode band',
      'wachttijd',
      'zachte start',
      'pendelbeveiliging',
      'ontdooien',
      'blokkade',
    ]) {
      expect(joined, term).toContain(term);
    }
  });
});

describe('i18n namespaces', () => {
  const modules = import.meta.glob<Record<string, Record<string, string>>>('./i18n/*/*.ts', {
    eager: true,
  });

  it.each(languages)('defines every %s key in one namespace only', (language) => {
    const owners = new Map<string, string[]>();
    for (const [path, module] of Object.entries(modules)) {
      if (!path.startsWith(`./i18n/${language}/`)) continue;
      const namespace = path.split('/').pop()!.replace(/\.ts$/, '');
      for (const table of Object.values(module)) {
        for (const key of Object.keys(table))
          owners.set(key, [...(owners.get(key) ?? []), namespace]);
      }
    }
    const duplicates = [...owners].filter(([, namespaces]) => namespaces.length > 1);
    expect(duplicates.map(([key, namespaces]) => `${key}: ${namespaces.join(', ')}`)).toEqual([]);
  });
});
