import type { Page } from '@playwright/test';

/**
 * Wait until the page has stopped moving: fonts loaded, every finite animation and transition
 * finished and two frames painted. Used before screenshots and layout measurements.
 */
export async function settled(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready;
    const finite = document
      .getAnimations()
      .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity);
    await Promise.all(finite.map((animation) => animation.finished.catch(() => undefined)));
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
    );
  });
}
