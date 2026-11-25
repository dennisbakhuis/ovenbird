// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import { makeDecisions, makeSeries } from '$mock/decisions';
import recorded from '$mock/fixtures/decisions-sim.json';
import { buildEpisodes } from '$lib/setpoint/episodes';
import { flipModel } from '$lib/setpoint/explain';
import type { Decision, DecisionRecord } from '$lib/core/types';
import DecisionTable from './DecisionTable.svelte';
import InputsTable from './InputsTable.svelte';
import ReasonStrip from './ReasonStrip.svelte';
import ArbiterList from './ArbiterList.svelte';
import FactList from './FactList.svelte';
import FlipMeter from './FlipMeter.svelte';
import NoteClauses from './NoteClauses.svelte';
import Pipeline from './Pipeline.svelte';
import RoomSensor from './RoomSensor.svelte';
import StateGauges from './StateGauges.svelte';

afterEach(cleanup);

globalThis.ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

const NOW = Date.parse('2026-11-15T12:00:00Z');
const base = (recorded.decisions as unknown as Decision[])[0] as Decision;
const record = (overrides: Partial<DecisionRecord> = {}): DecisionRecord => ({
  ...structuredClone(base.record),
  ...overrides,
});

describe('DecisionTable', () => {
  const series = makeSeries(NOW - 24 * 3_600_000, NOW, 0, NOW);
  const episodes = buildEpisodes(series);

  it('lists the newest episodes first with a link per row and a show-all toggle', async () => {
    render(DecisionTable, { episodes, decisions: [], now: NOW, limit: 5 });
    const table = screen.getByTestId('decision-table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(5);
    const newest = episodes[episodes.length - 1] as (typeof episodes)[number];
    expect(rows[0]?.getAttribute('data-episode')).toBe(newest.group);
    expect(
      within(rows[0] as HTMLElement)
        .getByRole('link')
        .getAttribute('href'),
    ).toContain(encodeURIComponent(new Date(newest.from).toISOString()));
    await fireEvent.click(screen.getByTestId('episodes-more'));
    expect(within(table).getAllByRole('row').length - 1).toBe(episodes.length);
  });

  it('switches to one row per decision', async () => {
    const decisions = makeDecisions(NOW - 3_600_000, NOW, 60, NOW);
    render(DecisionTable, { episodes, decisions, now: NOW });
    await fireEvent.click(screen.getByTestId('view-all'));
    const rows = within(screen.getByTestId('decision-table')).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(30);
  });
});

describe('FlipMeter', () => {
  it('prints where the setpoint changes and labels the scale', () => {
    const model = flipModel(
      record({
        setpoint: 31,
        pre_round: 31.3,
        flip_distance: 0.3,
        flip_input: 'room_temperature',
        controller_state: { room_target_c: 21.0, room_error_k: 0.4 },
      }),
    );
    if (!model) throw new Error('no model');
    render(FlipMeter, { model });
    const sentence = screen.getByTestId('flip-sentence').textContent ?? '';
    expect(sentence).toContain('Becomes 32 °C when the room falls to 20.3 °C (−0.3 K)');
    expect(screen.getByRole('img').getAttribute('aria-label')).toContain('20.3');
  });

  it('says a change is due when the distance is zero and the wait time runs', () => {
    const model = flipModel(
      record({
        setpoint: 31,
        pre_round: 32.4,
        flip_distance: 0,
        flip_input: 'pre_round',
      }),
    );
    if (!model) throw new Error('no model');
    render(FlipMeter, { model, dwellLeftS: 600 });
    expect(screen.getByTestId('flip-sentence').textContent).toContain('10 min');
  });
});

describe('RoomSensor', () => {
  it('shows held time, proof of life and a reduced cooling authority', () => {
    render(RoomSensor, {
      facts: {
        profile: 'on_change',
        value: 22.9,
        heldS: 7800,
        aliveS: 240,
        aliveBy: 'room_humidity',
        quantumK: 0.2,
        authority: 0.8,
        plausible: true,
        deviationK: 0.3,
        signal: 'room_temperature',
      },
    });
    const text = screen.getByTestId('room-sensor').textContent ?? '';
    expect(text).toContain('22.9 °C');
    expect(text).toContain('unchanged for 2 h 10 min');
    expect(screen.getByTestId('room-alive').textContent).toContain('humidity 4 min ago');
    expect(screen.getByTestId('room-authority').textContent).toContain('80 %');
  });
});

describe('Pipeline and StateGauges', () => {
  it('marks the binding stage and a frozen feedback stage', () => {
    const { container } = render(Pipeline, {
      record: record({ binding: 'cycling_floor', controller_state: { frozen_by: 'defrost' } }),
    });
    expect(container.querySelector('[data-stage="cycling_floor"]')?.className).toContain('binding');
    expect(container.querySelector('[data-stage="room_feedback"]')?.className).toContain('frozen');
  });

  it('shows the integrator, wait time and frozen reason as text', () => {
    render(StateGauges, {
      record: record({
        controller_state: { integral_k: -0.6, dwell_remaining_s: 720, frozen_by: 'defrost' },
      }),
    });
    const text = screen.getByTestId('controller-state').textContent ?? '';
    expect(text).toContain('−0.6 K');
    expect(text).toContain('12 min');
    expect(text).toContain('defrost');
  });
});

describe('notes, facts, inputs, arbiter and reason shares', () => {
  it('renders the controller note as clauses', () => {
    render(NoteClauses, { note: 'Room 0.1 K below target; PI adds -1.2 K; setpoint 29 °C.' });
    expect(within(screen.getByTestId('note-clauses')).getAllByRole('listitem')).toHaveLength(3);
  });

  it('renders facts as sentences', () => {
    render(FactList, { facts: [{ kind: 'ramp_cap', params: { cap: '28' } }] });
    expect(screen.getByTestId('decision-facts').textContent).toContain('28 °C');
  });

  it('renders inputs as labelled chips without internal flags', () => {
    render(InputsTable, { record: base.record });
    const text = screen.getByTestId('inputs-table').textContent ?? '';
    expect(text).toContain('Outside');
    expect(text).toContain('main/Outside_Temp');
    expect(text).not.toContain('stats');
  });

  it('renders the arbiter entries', () => {
    render(ArbiterList, { decision: base });
    expect(screen.getByTestId('arbiter-list').textContent).toContain('wants');
  });

  it('sums the reason shares to the window', () => {
    render(ReasonStrip, {
      segments: [
        { from: 0, to: 75, reason: 'room_feedback' },
        { from: 75, to: 100, reason: 'start_ramp' },
      ],
      from: 0,
      to: 100,
    });
    const label = screen.getByRole('img').getAttribute('aria-label') ?? '';
    expect(label).toContain('Normal control 75%');
    expect(label).toContain('Limited or smoothed 25%');
  });
});
