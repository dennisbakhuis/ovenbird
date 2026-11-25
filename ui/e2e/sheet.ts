import { expect, type Page } from '@playwright/test';

/**
 * The settings version as the mode sheet shows it ("Settings v12"); the strip no longer carries
 * it. Opens the sheet, reads the link and closes it again.
 */
export async function sheetVersion(page: Page): Promise<string> {
  await page.getByTestId('mode-chip').click();
  const link = page.getByTestId('config-version');
  await expect(link).toBeVisible();
  const text = (await link.innerText()).trim();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('mode-sheet')).toBeHidden();
  return text;
}
