const { test, expect } = require('@playwright/test');
const path = require('path');

const pages = [
  { name: 'index', url: process.env.APP_URL || `file://${path.resolve(__dirname, '..', 'index.html')}` },
  { name: 'queue', url: process.env.APP_URL ? `${process.env.APP_URL}/queue` : `file://${path.resolve(__dirname, '..', 'queue.html')}` },
  { name: 'webhooks', url: process.env.APP_URL ? `${process.env.APP_URL}/webhooks` : `file://${path.resolve(__dirname, '..', 'webhooks.html')}` },
  { name: 'workers', url: process.env.APP_URL ? `${process.env.APP_URL}/workers` : `file://${path.resolve(__dirname, '..', 'workers.html')}` },
  { name: 'simulation', url: process.env.APP_URL ? `${process.env.APP_URL}/simulation` : `file://${path.resolve(__dirname, '..', 'simulation.html')}` },
  { name: 'scheduler', url: process.env.APP_URL ? `${process.env.APP_URL}/scheduler` : `file://${path.resolve(__dirname, '..', 'scheduler.html')}` },
  { name: 'backend', url: process.env.APP_URL ? `${process.env.APP_URL}/backend` : `file://${path.resolve(__dirname, '..', 'backend.html')}` },
];

for (const p of pages) {
  test(`${p.name} page smoke`, async ({ page }) => {
    await page.goto(p.url, { waitUntil: 'domcontentloaded' });
    // take a screenshot for manual review
    await page.screenshot({ path: `frontend/smoke/screenshots/${p.name}.png`, fullPage: true });

    // top nav links should not use href="#"
    const badLinks = await page.$$eval('a', (links) => links.filter(l => (l.getAttribute('href')||'').trim() === '#').map(l => l.textContent));
    expect(badLinks.length, `found placeholder href="#" on ${p.name}`).toBe(0);

    // check for at least one interactive control
    const hasButton = await page.$$('button');
    expect(hasButton.length).toBeGreaterThan(0);

    // for pages that should show structured content, check the expected primary container
    if (['queue','webhooks','simulation','scheduler','backend'].includes(p.name)) {
      if (p.name === 'scheduler') {
        const hasKanban = await page.$$('[data-ui="kanban-queued-list"], [data-ui="kanban-scheduled-list"], [data-ui="kanban-running-list"]');
        expect(hasKanban.length).toBeGreaterThan(0);
      } else {
        const hasTable = await page.$('table');
        expect(!!hasTable).toBeTruthy();
      }
    }
  });
}
