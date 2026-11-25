/**
 * Linux and macOS lay out the same font a little differently, so phone page heights
 * are checked against their budget plus this share.
 */
export const RENDER_MARGIN = 0.05;

/** Return the largest page height a phone budget allows on any platform. */
export function allowedHeight(budget: number): number {
  return Math.round(budget * (1 + RENDER_MARGIN));
}
