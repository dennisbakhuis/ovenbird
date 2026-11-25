import { describe, expect, it } from 'vitest';
import { limitationKind, replayLines } from './replay';

describe('replay lines', () => {
  it('holds each value until the next tick and measures how often they differ', () => {
    const lines = replayLines({
      to: '2026-11-15T00:30:00Z',
      series: {
        at: ['2026-11-15T00:00:00Z', '2026-11-15T00:10:00Z', '2026-11-15T00:20:00Z'],
        recorded: [30, 31, null],
        candidate: [31, 31, 32],
        candidate_pre_round: [null, null, null],
      },
    });
    const t0 = Date.parse('2026-11-15T00:00:00Z');
    const t1 = Date.parse('2026-11-15T00:10:00Z');
    const t2 = Date.parse('2026-11-15T00:20:00Z');
    expect(lines.recorded).toEqual([
      [t0, 30],
      [t1, 31],
    ]);
    expect(lines.candidate).toHaveLength(3);
    expect(lines.upper).toEqual([
      [t0, 31],
      [t1, 31],
      [t1, 31],
      [t2, 31],
    ]);
    expect(lines.lower[0]).toEqual([t0, 30]);
    expect(lines.differs).toBe(0.5);
  });

  it('classifies the server limitations', () => {
    expect(
      limitationKind(
        "the candidate's room signal was not recorded with the decisions; it runs without that room input",
      ),
    ).toBe('room_signal');
    expect(
      limitationKind("the room value's freshness is as recorded under the active sensor profile"),
    ).toBe('room_profile');
    expect(limitationKind('something new')).toBe('other');
  });
});
