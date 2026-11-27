import { describe, expect, it } from 'vitest';
import schema from '$mock/fixtures/schema.json';
import { auditDetail } from '$lib/activity/audit';
import { dictionaries, translateOptional } from '$lib/i18n';
import { issueText, type Lookup } from './issues';
import { rollbackDiff } from '$lib/core/rollback';
import config from '$mock/fixtures/config.json';
import type { ConfigDoc, ConfigSchema } from '$lib/core/types';

const sch = schema as unknown as ConfigSchema;
const doc = config as unknown as ConfigDoc;
const english: Lookup = (key, params) => translateOptional('en', key, params);

describe('issueText', () => {
  it('names both fields of a house bound by their labels', () => {
    const params = {
      min_field: 'house_ua_min_w_per_k',
      max_field: 'house_ua_max_w_per_k',
      min: 300,
      max: 200,
    };
    expect(
      issueText(
        { code: 'house_bounds_order', message: 'x', params },
        sch.fields['house_ua_max_w_per_k'],
        english,
      ),
    ).toBe('Heat loss, at least (300 W/K) must not exceed Heat loss, at most (200 W/K).');
  });

  it('uses the display unit for hard bounds', () => {
    const text = issueText(
      { code: 'below_min', message: 'x', params: { min: 300 } },
      sch.fields['control_dwell_s'],
      english,
    );
    expect(text).toBe('Must be at least 5 min.');
  });

  it('fills server params, joining lists', () => {
    expect(
      issueText(
        { code: 'ramp_below_envelope', message: 'x', params: { max: 6 } },
        sch.fields['control_ramp_max_below_curve_k'],
        english,
      ),
    ).toContain('6 K');
    expect(
      issueText(
        { code: 'emitter_changed', message: 'x', params: { from: 'mixed', to: 'radiators' } },
        undefined,
        english,
      ),
    ).toContain('from mixed to radiators');
  });

  it('shows a whole-configuration issue without a field', () => {
    expect(
      issueText({ code: 'no_change', message: 'nothing changed', params: {} }, undefined, english),
    ).toBe('Nothing changed compared with the active configuration.');
  });

  it('falls back to the server message and then the code', () => {
    expect(issueText({ code: 'brand_new', message: 'from server' }, undefined, english)).toBe(
      'from server',
    );
    expect(issueText({ code: 'brand_new', message: '' }, undefined, english)).toBe('brand_new');
  });

  it('has the same placeholders in Dutch for every check text', () => {
    const names = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of Object.keys(dictionaries.en).filter((k) => k.startsWith('check_'))) {
      const nl = (dictionaries.nl as Record<string, string>)[key] ?? '';
      expect(names(nl), key).toEqual(names((dictionaries.en as Record<string, string>)[key] ?? ''));
    }
  });
});

describe('rollbackDiff', () => {
  it('lists changed editable fields and resets fields the old version did not store', () => {
    const entries = rollbackDiff(
      { control_comfort_c: 21, control_min_setpoint_c: 26, control_emitter: 'mixed' },
      doc,
      sch,
    );
    const fields = entries.map((e) => e.field).sort();
    expect(fields).toContain('control_comfort_c');
    expect(fields).toContain('control_room_signal');
    expect(fields).not.toContain('control_emitter');
    expect(fields).not.toContain('control_interval_s');
    expect(entries.find((e) => e.field === 'control_room_signal')).toMatchObject({ reset: true });
  });
});

describe('auditDetail', () => {
  const words = {
    version: (n: number) => `version ${n}`,
    rollbackTo: (n: number) => `back to ${n}`,
    field: (id: string) => id,
  };
  const event = (action: string, detail: Record<string, unknown>) => ({
    at: '',
    actor: '',
    source_ip: null,
    action,
    detail,
  });

  it('summarises applies, rollbacks and reasons', () => {
    expect(
      auditDetail(
        event('config_apply', {
          version: 13,
          changed: [{ field: 'control_comfort_c', from: 21.0, to: 20.8 }],
          comment: 'cooler',
        }),
        words,
      ),
    ).toBe('version 13 · control_comfort_c 21 → 20.8 · cooler');
    expect(auditDetail(event('config_rollback', { rollback_to: 9 }), words)).toBe('back to 9');
    expect(auditDetail(event('mode_pause', { reason: 'away' }), words)).toBe('away');
    expect(auditDetail(event('mode_resume', {}), words)).toBe('');
    expect(auditDetail(event('mode_pause', { reason: null }), words)).toBe('');
  });
});
