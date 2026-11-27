import { expect, test, type Page } from '@playwright/test';
import { mkdirSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { HelpTopic } from '../src/lib/help/types';

const here = dirname(fileURLToPath(import.meta.url));
const CONTENT = join(here, '../src/lib/help/content/en');

async function loadTopics(): Promise<HelpTopic[]> {
  const files = readdirSync(CONTENT).filter(
    (file) => file.endsWith('.ts') && !file.startsWith('glossary'),
  );
  const modules = await Promise.all(
    files.map((file) => import(join(CONTENT, file)) as Promise<{ topic?: HelpTopic }>),
  );
  return modules.flatMap((module) => (module.topic ? [module.topic] : []));
}

const topics = await loadTopics();

/** Guides have no page of their own: they open from the help index. */
const GUIDES = new Set(['start', 'switching']);

/** Targets that sit on a tab of their page rather than on its first one. */
const TARGET_TAB: Record<string, string> = {
  'house.prediction': 'model',
  'house.whatif': 'what-if',
  'house.signature': 'model',
  'house.bounds': 'model',
  'house.learning': 'learning',
  'house.quality': 'model',
  'house.run': 'learning',
  'house.timeline': 'learning',
  'house.proposal': 'learning',
};

const VIEWPORTS = [
  { label: 'desktop', width: 1400, height: 1000 },
  { label: 'phone', width: 400, height: 860 },
] as const;

async function boot(page: Page, hash: string): Promise<void> {
  await page.goto(`./${hash}`);
  await expect(page.getByTestId('status-strip')).toBeVisible();
}

async function goTo(page: Page, hash: string): Promise<void> {
  await page.evaluate((value) => (window.location.hash = value), hash);
}

const drawer = (page: Page) => page.getByTestId('help-drawer');

for (const viewport of VIEWPORTS) {
  test.describe(`help ${viewport.label}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test('the button and the ? key open it; it follows navigation; Esc closes', async ({
      page,
    }) => {
      await boot(page, '#/home');
      const button = page.getByTestId('help-button');
      await expect(button).toBeVisible();
      await expect(page.getByTestId('help-dot')).toBeVisible();
      const box = await button.boundingBox();
      expect(box?.width ?? 0).toBeGreaterThanOrEqual(40);

      await button.click();
      await expect(drawer(page)).toBeVisible();
      await expect(drawer(page)).toHaveAttribute('data-topic', 'home');
      await expect(page.getByTestId('help-dot')).toHaveCount(0);

      await goTo(page, '#/pump');
      await expect(drawer(page)).toHaveAttribute('data-topic', 'pump');
      await goTo(page, '#/settings/curve');
      await expect(drawer(page)).toHaveAttribute('data-topic', 'settings/curve');
      await goTo(page, '#/activity/holds');
      await expect(drawer(page)).toHaveAttribute('data-topic', 'activity/holds');

      await page.getByTestId('help-search').focus();
      await page.keyboard.type('?');
      await expect(drawer(page)).toBeVisible();
      await expect(page.getByTestId('help-search')).toHaveValue('?');

      await page.keyboard.press('Escape');
      await expect(drawer(page)).toHaveCount(0);
      await expect(button).toBeFocused();

      await page.keyboard.press('?');
      await expect(drawer(page)).toBeVisible();
      await expect(drawer(page).getByTestId('help-title')).toBeFocused();
      if (viewport.width > 640) {
        await page.locator('main').click({ position: { x: 5, y: 5 } });
        await page.keyboard.press('?');
        await expect(drawer(page)).toHaveCount(0);
      } else {
        await page.keyboard.press('Escape');
        await expect(drawer(page)).toHaveCount(0);
      }

      const overflow = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        inner: window.innerWidth,
      }));
      expect(overflow.scroll).toBeLessThanOrEqual(overflow.inner);
    });

    test('keyboard: sections, terms and Show me are reachable', async ({ page }) => {
      await boot(page, '#/home');
      await page.keyboard.press('?');
      await expect(drawer(page).getByTestId('help-title')).toBeFocused();
      const toggle = drawer(page).getByTestId('help-section-toggle').first();
      for (let i = 0; i < 40; i += 1) {
        await page.keyboard.press('Tab');
        if (await toggle.evaluate((node) => node === document.activeElement)) break;
      }
      await expect(toggle).toBeFocused();
      await page.keyboard.press('Enter');
      await expect(toggle).toHaveAttribute('aria-expanded', 'true');
      const section = drawer(page).getByTestId('help-section').first();
      const term = section.getByTestId('help-term').first();
      if ((await term.count()) > 0) {
        await term.focus();
        await page.keyboard.press('Enter');
        await expect(term).toHaveAttribute('aria-expanded', 'true');
      }
      const show = section.getByTestId('help-show-me');
      if ((await show.count()) > 0) {
        await show.focus();
        await page.keyboard.press('Enter');
        await expect(page.getByTestId('help-spotlight')).toBeVisible();
      }
    });

    test('"More in help" in a why? popover opens the drawer at that section', async ({ page }) => {
      const trigger = page.locator('[data-help] button[aria-haspopup="dialog"]:visible').first();
      let found = false;
      for (const hash of ['#/home', '#/setpoint', '#/pump', '#/weather', '#/settings/room']) {
        await boot(page, hash);
        await page.waitForTimeout(300);
        if ((await trigger.count()) > 0) {
          found = true;
          break;
        }
      }
      test.skip(!found, 'no why? inside a data-help element yet');
      const target = await trigger.evaluate(
        (node) => node.closest<HTMLElement>('[data-help]')?.dataset['help'] ?? '',
      );
      await trigger.click();
      await page.getByTestId('why-more-help').click();
      await expect(drawer(page)).toBeVisible();
      const topic = topics.find((item) => target.startsWith(`${item.id}.`));
      const section = topic?.sections.find((item) => item.target === target);
      if (section) {
        const card = drawer(page).locator(`[data-section="${section.id}"]`);
        await expect(card.getByTestId('help-section-toggle')).toHaveAttribute(
          'aria-expanded',
          'true',
        );
        await expect(card.getByTestId('help-section-toggle')).toBeFocused();
      }
      await page.keyboard.press('Escape');
      await expect(drawer(page)).toHaveCount(0);
      await expect(trigger).toBeFocused();
    });

    test('the index lists "Start here" first and opens it without a page link', async ({
      page,
    }) => {
      await boot(page, '#/home');
      await page.getByTestId('help-button').click();
      await expect(drawer(page)).toBeVisible();
      await drawer(page).getByTestId('help-all-topics').click();
      const entries = drawer(page).getByTestId('help-index').locator('button');
      await expect(entries.first()).toHaveAttribute('data-topic', 'start');
      await expect(entries.first()).toContainText('Start here');
      await expect(entries.nth(1)).toHaveAttribute('data-topic', 'switching');
      await expect(entries.nth(2)).toHaveAttribute('data-topic', 'home');
      await entries.first().click();
      await expect(drawer(page)).toHaveAttribute('data-topic', 'start');
      await expect(drawer(page).getByTestId('help-title')).toHaveText('Start here');
      await expect(drawer(page).getByTestId('help-goto')).toHaveCount(0);
      await expect(drawer(page).getByTestId('help-section').first()).toBeVisible();
    });

    test('searching "WAR" puts the heating curve or the switching guide first', async ({
      page,
    }) => {
      await boot(page, '#/home');
      await page.getByTestId('help-button').click();
      await drawer(page).getByTestId('help-search').fill('WAR');
      const first = drawer(page).getByTestId('help-results').locator('button').first();
      await expect(first).toContainText(/Coming from another controller|Heating curve/);
      await expect(first).toHaveAttribute('data-kind', /^(topic|term)$/);
      await first.click();
      await expect(drawer(page)).toHaveAttribute('data-topic', /^(switching|glossary)$/);
    });

    for (const topic of topics.filter((item) => !GUIDES.has(item.id))) {
      const targets = topic.sections.filter((section) => section.target);
      test(`topic ${topic.id}: every target is on the page and Show me rings it`, async ({
        page,
      }) => {
        await boot(page, `#/${topic.id}`);
        await page.getByTestId('help-button').click();
        await expect(drawer(page)).toHaveAttribute('data-topic', topic.id);
        await expect(drawer(page).getByTestId('help-title')).toHaveText(topic.title);
        for (const section of targets) {
          const tab = TARGET_TAB[section.target!];
          const hash = `#/${topic.id}${tab ? `/${tab}` : ''}`;
          if ((await page.evaluate(() => window.location.hash)) !== hash) await goTo(page, hash);
          const element = page.locator(`[data-help="${section.target}"]`).first();
          await expect(element, `${section.target} on the page`).toBeAttached();
          await expect(element, `${section.target} visible`).toBeVisible();
          const card = drawer(page).locator(`[data-section="${section.id}"]`);
          const toggle = card.getByTestId('help-section-toggle');
          if ((await toggle.getAttribute('aria-expanded')) !== 'true') await toggle.click();
          const show = card.getByTestId('help-show-me');
          await expect(show, `Show me for ${section.target}`).toBeVisible();
          await show.click();
          const ring = page.getByTestId('help-spotlight');
          await expect(ring).toHaveAttribute('data-target', section.target!);
          await expect(ring).toBeVisible();
          await expect(element).toBeInViewport();
          if (viewport.width <= 640) {
            await expect(drawer(page)).toBeHidden();
            await page.getByTestId('help-return').click();
            await expect(drawer(page)).toBeVisible();
          }
        }
      });
    }
  });
}

const SHOTS = process.env['HELP_SHOTS'];

/** Leaves the mock in Shadow: run it on its own (`-g "Shadow"`), after the other shots. */
test.describe('help shadow top bar', () => {
  test.skip(
    !process.env['HELP_SHOTS'] || Boolean(process.env['BASE_URL']),
    'mock screenshots only',
  );
  test.use({ viewport: { width: 400, height: 860 } });

  for (const language of ['en', 'nl'] as const) {
    test(`phone top bar fits in Shadow, ${language}`, async ({ page }) => {
      await page.addInitScript((lang) => localStorage.setItem('ovenbird.language', lang), language);
      await boot(page, '#/home');
      const chip = page.getByTestId('mode-chip');
      await expect(chip).toHaveAttribute('data-mode', /auto|paused/);
      if ((await chip.getAttribute('data-mode')) === 'auto') {
        await chip.click();
        await page.getByTestId('pause').click();
      } else await chip.click();
      await expect(chip).toHaveAttribute('data-mode', 'paused');
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
      await page.screenshot({
        path: join(process.env['HELP_SHOTS']!, `phone-shadow-${language}-topbar.png`),
        clip: { x: 0, y: 0, width: 400, height: 120 },
      });
      const bar = await page.getByTestId('topbar').boundingBox();
      expect(bar?.height ?? 0).toBeLessThanOrEqual(60);
      await expect(page.getByTestId('help-button')).toBeInViewport({ ratio: 1 });
    });
  }
});

test.describe('help screenshots', () => {
  test.skip(!SHOTS, 'set HELP_SHOTS=<dir> to capture');

  for (const viewport of [...VIEWPORTS, { label: 'tablet', width: 900, height: 900 }]) {
    for (const scheme of ['light', 'dark'] as const) {
      for (const language of ['en', 'nl'] as const) {
        test(`${viewport.label} ${scheme} ${language}`, async ({ page }) => {
          mkdirSync(SHOTS!, { recursive: true });
          await page.setViewportSize({ width: viewport.width, height: viewport.height });
          await page.emulateMedia({ colorScheme: scheme });
          await page.addInitScript(
            (lang) => localStorage.setItem('ovenbird.language', lang),
            language,
          );
          const name = (what: string) =>
            join(SHOTS!, `${viewport.label}-${scheme}-${language}-${what}.png`);

          await boot(page, '#/home');
          await page.waitForTimeout(600);
          await page.screenshot({
            path: name('0-topbar'),
            clip: { x: 0, y: 0, width: viewport.width, height: 120 },
          });
          await page.getByTestId('help-button').click();
          await expect(drawer(page)).toBeVisible();
          await page.waitForTimeout(800);
          await page.screenshot({ path: name('1-home') });

          const first = drawer(page).getByTestId('help-section-toggle').first();
          await first.click();
          const term = drawer(page).getByTestId('help-term').first();
          if ((await term.count()) > 0) await term.click();
          await page.waitForTimeout(200);
          await page.screenshot({ path: name('2-section') });

          const show = drawer(page).getByTestId('help-show-me').first();
          if ((await show.count()) > 0) {
            await show.click();
            await page.waitForTimeout(700);
            await page.screenshot({ path: name('3-showme') });
            if (viewport.width <= 640) await page.getByTestId('help-return').click();
          }

          await goTo(page, '#/settings/curve');
          await page.waitForTimeout(800);
          await page.screenshot({ path: name('4-curve') });

          await drawer(page)
            .getByTestId('help-search')
            .fill(language === 'nl' ? 'stooklijn' : 'curve');
          await page.waitForTimeout(200);
          await page.screenshot({ path: name('5-search') });
          await drawer(page).getByTestId('help-search').fill('');

          await drawer(page).getByTestId('help-all-topics').click();
          await page.waitForTimeout(600);
          await page.screenshot({ path: name('6-index') });

          await drawer(page).getByTestId('help-glossary-link').click();
          await page.waitForTimeout(300);
          await page.screenshot({ path: name('7-glossary') });
        });
      }
    }
  }
});
