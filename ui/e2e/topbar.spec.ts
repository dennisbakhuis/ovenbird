import { expect, test } from '@playwright/test';

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
