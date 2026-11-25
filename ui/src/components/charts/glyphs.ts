/**
 * Small 24 × 24 stroke glyphs (1.5 px at full size) used by the chart kit's defaults and the
 * gallery. Charts take any path string, so pages can pass glyphs from the shared icon set.
 */
export const GLYPHS = {
  bolt: 'M13 3 5 13.5h6L10 21l8-10.5h-6z',
  flame:
    'M12 21a6 6 0 0 0 6-6c0-3.5-2.5-5.5-3.5-8.5-1 2-2 3-3.5 3.5C11 7 10 5 9 3 7.5 6.5 6 9.5 6 15a6 6 0 0 0 6 6z',
  snowflake: 'M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9M9.5 4.5 12 7l2.5-2.5M9.5 19.5 12 17l2.5 2.5',
  tap: 'M4 9h9a3 3 0 0 1 3 3v1M8 9V6h4M16 16.5c0 1.4-.9 2.5-2 2.5s-2-1.1-2-2.5c0-1.2 2-3.5 2-3.5s2 2.3 2 3.5z',
  moon: 'M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10z',
  fan: 'M12 12c0-4 1-7 3.5-7S18 8 12 12zm0 0c4 0 7 1 7 3.5S16 18 12 12zm0 0c0 4-1 7-3.5 7S6 16 12 12zm0 0c-4 0-7-1-7-3.5S8 6 12 12z',
  pause: 'M9 5v14M15 5v14',
  gear: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8',
  lock: 'M7 11V8a5 5 0 0 1 10 0v3M5.5 11h13v9h-13z',
  check: 'M5 12.5 10 17.5 19 7',
  warning: 'M12 4 21.5 20h-19zM12 10v4.5M12 17.2v.1',
  critical: 'M8 3.5h8l4.5 4.5v8L16 20.5H8L3.5 16V8zM9 9l6 6M15 9l-6 6',
  arrow: 'M5 12h14M13 6l6 6-6 6',
} as const;

export type GlyphName = keyof typeof GLYPHS;
