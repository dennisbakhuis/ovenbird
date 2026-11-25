// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import AlarmList from './AlarmList.svelte';
import CommandTable from './CommandTable.svelte';
import MonitorTable from './MonitorTable.svelte';

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});
afterEach(cleanup);

const alarm = (code: string, severity: 'critical' | 'warning' | 'info') => ({
  code,
  severity,
  message: 'msg',
  since: '2026-11-15T10:00:00Z',
  detail: {},
});

describe('AlarmList', () => {
  it('lists the most severe first and offers a link only when not compact', () => {
    const alarms = [alarm('heishamon_restarted', 'info'), alarm('foreign_writer', 'warning')];
    const { unmount } = render(AlarmList, { alarms });
    const items = screen.getAllByRole('listitem');
    expect(items[0]?.textContent).toContain('Someone else changed the pump');
    expect(screen.getByRole('link', { name: /Show holds/ })).toBeTruthy();
    unmount();
    render(AlarmList, { alarms, compact: true });
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('MonitorTable', () => {
  const base = {
    code: 'outlet_overshoot',
    severity: 'critical' as const,
    status: 'ok' as const,
    message: 'fine',
    value: 30,
    since: null,
    limit: null,
    unit: null,
    direction: null,
  };
  it('draws a bar only when a limit is present', () => {
    const { unmount } = render(MonitorTable, { monitors: [base] });
    expect(screen.queryByRole('img')).toBeNull();
    unmount();
    render(MonitorTable, { monitors: [{ ...base, limit: 45, unit: '°C', direction: 'above' }] });
    expect(screen.getByRole('img')).toBeTruthy();
  });
});

describe('CommandTable', () => {
  const row = (at: string, status: string) => ({
    at,
    kind: 'water_setpoint',
    value: 30,
    status,
    attempt: 1,
    detail: status,
    topic: 't',
    payload: '30',
  });
  it('shows one row per command and expands its timeline', async () => {
    render(CommandTable, {
      commands: [
        row('2026-11-15T10:00:00Z', 'queued'),
        row('2026-11-15T10:00:01Z', 'sent'),
        row('2026-11-15T10:00:09Z', 'verified'),
      ],
    });
    const head = screen.getByRole('button', { name: /Water setpoint/ });
    expect(screen.getAllByRole('button')).toHaveLength(1);
    await fireEvent.click(head);
    expect(screen.getAllByText('sent').length).toBeGreaterThan(0);
    expect(head.getAttribute('aria-expanded')).toBe('true');
  });
});
