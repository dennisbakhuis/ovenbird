import { expect, test } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { settled } from './settle';

test.skip(Boolean(process.env['BASE_URL']), 'mock scenarios');

for (const width of [960, 1000, 1100, 1280]) {
  for (const drawer of [false, true]) {
    test(`no top nav label is clipped at ${width} px, help drawer ${drawer ? 'open' : 'closed'}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(() => localStorage.setItem('ovenbird.language', 'en'));
      await page.goto('./#/home');
      await expect(page.getByTestId('top-nav')).toBeVisible();
      if (drawer) {
        await page.getByTestId('help-button').click();
        await expect(page.locator('html.help-docked')).toHaveCount(1);
      }
      const clipped = await page.getByTestId('top-nav').evaluate((nav) =>
        [...nav.querySelectorAll('a')]
          .filter((link) => {
            const label = link.querySelector<HTMLElement>('.nav-label');
            if (!label || getComputedStyle(label).position === 'absolute') return false;
            return (
              label.scrollWidth > label.clientWidth ||
              link.scrollWidth > link.clientWidth ||
              link.getBoundingClientRect().right > nav.getBoundingClientRect().right + 0.5
            );
          })
          .map((link) => link.textContent?.trim()),
      );
      expect(clipped).toEqual([]);
    });
  }
}

const SHOTS = process.env['TOPBAR_SHOTS'] ?? 'e2e/shots';
mkdirSync(SHOTS, { recursive: true });

for (const lang of ['en', 'nl'] as const) {
  test(`the version sits next to the logo on desktop ${lang}`, async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    await page.addInitScript((l) => localStorage.setItem('ovenbird.language', l), lang);
    await page.goto('./#/home');
    const version = page.getByTestId('app-version');
    await expect(version).toHaveText(/^v\d+\.\d+\.\d+/);
    await settled(page);
    const box = await page.getByTestId('topbar').locator('.brand').boundingBox();
    const label = await version.boundingBox();
    expect(box && label && label.x >= box.x + box.width - 1).toBe(true);
    expect(
      box && label && Math.abs(label.y + label.height / 2 - (box.y + box.height / 2)),
    ).toBeLessThan(6);
    const shift = await page.evaluate(() => {
      const nav = document.querySelector('[data-testid="top-nav"]')!;
      const link = document.querySelector<HTMLElement>('[data-testid="app-version"]')!;
      const before = nav.getBoundingClientRect().left;
      link.style.display = 'none';
      const after = nav.getBoundingClientRect().left;
      link.style.display = '';
      return before - after;
    });
    expect(shift).toBe(0);
    await settled(page);
    await page
      .getByTestId('topbar')
      .screenshot({ path: join(SHOTS, `topbar-version-${lang}-1400.png`) });
    await version.click();
    await expect(page).toHaveURL(/#\/system$/);
    await expect(page.getByTestId('about-card')).toBeVisible();
  });

  test(`the version heads the More page on the phone ${lang}`, async ({ page }) => {
    await page.setViewportSize({ width: 400, height: 860 });
    await page.addInitScript((l) => localStorage.setItem('ovenbird.language', l), lang);
    await page.goto('./#/more');
    await expect(page.getByTestId('app-version')).toBeHidden();
    const version = page.getByTestId('more-version');
    await expect(version).toHaveText(/^ovenbird\s*v\d+\.\d+\.\d+/);
    await settled(page);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    const shift = await page.evaluate(() => {
      const links = document.querySelector('[data-testid="more-links"]')!;
      const link = document.querySelector<HTMLElement>('[data-testid="more-version"]')!;
      const before = links.getBoundingClientRect().top;
      link.style.display = 'none';
      const after = links.getBoundingClientRect().top;
      link.style.display = '';
      return before - after;
    });
    expect(shift).toBe(0);
    await settled(page);
    await page.screenshot({ path: join(SHOTS, `more-version-${lang}-400.png`) });
    await version.click();
    await expect(page).toHaveURL(/#\/system$/);
    await expect(page.getByTestId('about-card')).toBeVisible();
  });
}
