import { test, expect } from '@playwright/test';

// Live end-to-end test against the real local stack (make up) and a real
// Azure/Claude summarization call. It is OPT-IN: it only runs when RUN_AI_E2E=1
// is set, because it requires the full stack up, a configured AZURE_AI_API_KEY,
// and it makes a billable model call. By default it is skipped so the suite
// stays offline and deterministic.
//
//   Prerequisites: `make up` running, frontend on :3000, Supabase + Temporal
//   worker healthy, AZURE_AI_API_KEY set in .env.
//   Run with:  RUN_AI_E2E=1 npx playwright test ai-summarize.live

const RUN = process.env.RUN_AI_E2E === '1';
const ROUTE = '/tools/summarize';

// A short French document containing a title-prefixed personal name. The worker
// redacts such names ("Monsieur Jean Dupont" -> "[nom]") BEFORE sending text to
// Claude, so the name must not leak into the English summary.
const FRENCH_DOC = [
  "Compte rendu de reunion du 12 mars.",
  "Monsieur Jean Dupont a presente le rapport trimestriel sur les ventes.",
  "Les resultats montrent une hausse de quinze pour cent des revenus.",
  "L'equipe prevoit de lancer un nouveau produit au printemps prochain.",
  "Une discussion a porte sur le budget marketing et les embauches.",
].join('\n');

test.describe('AI summarize (live, gated by RUN_AI_E2E=1)', () => {
  test.skip(!RUN, 'Set RUN_AI_E2E=1 to run against the real stack + Azure.');

  test('summarizes a real French document into English with name redaction', async ({
    page,
  }) => {
    // Real model round-trip: extraction + summarization can take a while.
    test.setTimeout(180_000);

    await page.goto(ROUTE);
    await expect(
      page.getByText(/Summarize a French document/i),
    ).toBeVisible();

    await page.getByLabel(/Document/i).setInputFiles({
      name: 'reunion.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from(FRENCH_DOC, 'utf-8'),
    });

    await page.getByRole('button', { name: /Summarize/i }).click();

    // Wait for the real workflow to complete and render the English summary.
    const summaryHeading = page.getByRole('heading', { name: /English summary/i });
    await expect(summaryHeading).toBeVisible({ timeout: 150_000 });

    // The rendered summary should contain text and must not leak the redacted name.
    const summaryBlock = page.locator('.whitespace-pre-wrap');
    await expect(summaryBlock).toBeVisible();
    const text = (await summaryBlock.textContent())?.trim() ?? '';
    expect(text.length).toBeGreaterThan(20);
    expect(text).not.toMatch(/Dupont/i);
  });
});
