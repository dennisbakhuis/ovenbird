import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { dictionaries } from '.';

const SRC = join(__dirname, '..', '..');

/**
 * Keys built at run time are allowed by prefix. Each entry is a prefix some code assembles with
 * a server code, a field name or an enum value (`t(`pumpSetting_${id}`)`, `tc('reason_', code)`),
 * or one translated for every server code that i18n.test.ts checks against the fixtures.
 */
const DYNAMIC_PREFIXES = [
  'activityRange_',
  'alarm_',
  'alarmAction_',
  'alarmNow_',
  'alarmText_',
  'alarmWhy_',
  'alarmYou_',
  'appliedBut_',
  'arbiterAction_',
  'audit_',
  'binding_',
  'busy_',
  'captureRefusal_',
  'check_',
  'cmd_',
  'cfg.',
  'control_',
  'counter_',
  'dayshiftMode_',
  'dayshiftPhase_',
  'dayshiftReason_',
  'dayshiftShadow_',
  'deiceMode_',
  'deiceNote_',
  'envelopeRule_',
  'envelopeRuleText_',
  'event_',
  'explain_binding_',
  'explain_reason_',
  'fact_',
  'feature_',
  'featureAck_',
  'featureHelp_',
  'featureState_',
  'flipSubject_',
  'frozenBy_',
  'group_',
  'haTest_',
  'haUrl_',
  'haVerdict_',
  'helpKind_',
  'houseEmitterReason_',
  'homeAwayPaused_',
  'homeBoostPaused_',
  'houseExcluded_',
  'holdReason_',
  'holdWhy_',
  'houseLossReason_',
  'input_',
  'inputEnum_',
  'journal_',
  'kind_',
  'ladder_',
  'langName_',
  'liveKind_',
  'loopState_',
  'modeExplain_',
  'modeName_',
  'modeShort_',
  'mode_',
  'mon_',
  'monitorStatus_',
  'mqttProblem_',
  'mqttRefused_',
  'mqttSaveBlock_',
  'mqttTest_',
  'mqttVerdict_',
  'notifyHealth_',
  'origin_',
  'outsideWhy_',
  'preset_',
  'presetText_',
  'previewComfort_',
  'previewLimit_',
  'pumpEffect_',
  'pumpGroup_',
  'pumpLabel_',
  'pumpOwner_',
  'pumpRefusal_',
  'pumpSetting_',
  'rampPhase_',
  'range_',
  'reason_',
  'reasonCat_',
  'releaseItem_',
  'releaseRefusal_',
  'replayConfig_',
  'replayCoverageLegend_',
  'replayEpisodeDiff_',
  'replayIdentity_',
  'replayPeriod_',
  'replayPhase_',
  'replayPreset_',
  'replayProblem_',
  'res_',
  'section_',
  'severity_',
  'shadowEnd_',
  'shadowEpisodeDiff_',
  'shadowLean_',
  'shadowRange_',
  'shadowWindow_',
  'shadowWriter_',
  'shadowWriterBy_',
  'sig_',
  'signalGroup_',
  'sigval_',
  'snapshotOrigin_',
  'source_',
  'stage_',
  'state_',
  'step',
  'step_',
  'stoveBannerIdle_',
  'stoveExit_',
  'stoveRef_',
  'stoveSource_',
  'stoveWait_',
  'tab_',
  'term_',
  'theme_',
  'tonightHeating_',
  'trialCheck_',
  'trialCriteriaSource_',
  'trialCriterion_',
  'trialCriterionStatus_',
  'trialEv_',
  'trialGroup_',
  'trialMsg_',
  'trialOutcome_',
  'trialState_',
  'trialStatus_',
  'verdict_',
  'verdictRoom_',
  'weatherSky_',
  'weatherSource_',
  'wf_',
  'write_',
  'writeNew_',
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      return path.endsWith(join('lib', 'i18n', 'en')) || path.endsWith(join('lib', 'i18n', 'nl'))
        ? []
        : sourceFiles(path);
    }
    return /\.(ts|svelte)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

function quotedLiterals(): Set<string> {
  const found = new Set<string>();
  for (const file of sourceFiles(SRC)) {
    for (const match of readFileSync(file, 'utf8').matchAll(/['"`]([A-Za-z0-9_]+)['"`]/g)) {
      found.add(match[1]!);
    }
  }
  return found;
}

describe('translation keys', () => {
  it('are all referenced by the app or allowed by a dynamic prefix', () => {
    const referenced = quotedLiterals();
    const unused = Object.keys(dictionaries.en).filter(
      (key) => !referenced.has(key) && !DYNAMIC_PREFIXES.some((prefix) => key.startsWith(prefix)),
    );
    expect(unused, 'delete these keys from en and nl, or allow their prefix').toEqual([]);
  });

  it('allow only prefixes that some key still uses', () => {
    const keys = Object.keys(dictionaries.en);
    const stale = DYNAMIC_PREFIXES.filter((prefix) => !keys.some((key) => key.startsWith(prefix)));
    expect(stale).toEqual([]);
  });
});
