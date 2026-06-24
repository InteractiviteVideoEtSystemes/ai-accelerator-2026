import { test, expect } from '@playwright/test';

// Offline smoke test for the AI summarization screen. Storage upload and the
// `summaries` Edge Function are intercepted with page.route, so this test is
// deterministic and never touches the real backend or Azure. It verifies the
// end-to-end UI flow: select file -> upload -> create request -> poll -> render
// the English summary with a working Copy control.

const ROUTE = '/tools/summarize';
const SUMMARY_TEXT = 'This is the generated English summary of the document.';

test.describe('AI summarize (offline smoke)', () => {
  test('uploads a document and renders the completed summary', async ({ page }) => {
    let uploadHit = false;
    let createBody: Record<string, unknown> | null = null;

    // Mock the private Storage bucket upload (supabase-js -> /storage/v1/object/...).
    await page.route('**/storage/v1/object/**', async (route) => {
      uploadHit = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ Key: 'documents/mock/sample.txt' }),
      });
    });

    // Mock the Edge Function: POST creates the request, GET polls its status.
    await page.route('**/summaries**', async (route) => {
      const req = route.request();
      const url = req.url();
      if (req.method() === 'POST' && url.endsWith('/summaries')) {
        createBody = req.postDataJSON();
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ id: 'e2e-smoke-1', status: 'summarizing' }),
        });
        return;
      }
      if (req.method() === 'GET' && url.includes('/summaries/')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'e2e-smoke-1',
            status: 'completed',
            summary: SUMMARY_TEXT,
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(ROUTE);

    await expect(
      page.getByText(/Summarize a French document/i),
    ).toBeVisible();

    await page.getByLabel(/Document/i).setInputFiles({
      name: 'sample.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Bonjour, ceci est un document de test.'),
    });

    await page.getByRole('button', { name: /Summarize/i }).click();

    // The polling GET resolves to status=completed -> summary is rendered.
    await expect(
      page.getByRole('heading', { name: /English summary/i }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(SUMMARY_TEXT)).toBeVisible();
    await expect(page.getByRole('button', { name: /Copy/i })).toBeVisible();

    // The UI must honor the real upload + Edge Function contract, not just render
    // a mocked summary: assert the document was uploaded and the create payload.
    expect(uploadHit).toBe(true);
    expect(createBody).toMatchObject({
      original_filename: 'sample.txt',
      mime_type: 'text/plain',
    });
    expect(typeof (createBody as Record<string, unknown>)?.storage_path).toBe('string');
    expect((createBody as Record<string, unknown>)?.size_bytes).toBeGreaterThan(0);
  });

  test('shows a Retry control when the request fails', async ({ page }) => {
    await page.route('**/storage/v1/object/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ Key: 'documents/mock/sample.txt' }),
      });
    });

    await page.route('**/summaries**', async (route) => {
      const req = route.request();
      const url = req.url();
      if (req.method() === 'POST' && url.endsWith('/summaries')) {
        await route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ id: 'e2e-smoke-2', status: 'summarizing' }),
        });
        return;
      }
      if (req.method() === 'GET' && url.includes('/summaries/')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'e2e-smoke-2',
            status: 'failed',
            error_message: 'Summarization provider error.',
          }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto(ROUTE);
    await page.getByLabel(/Document/i).setInputFiles({
      name: 'sample.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Bonjour, ceci est un document de test.'),
    });
    await page.getByRole('button', { name: /Summarize/i }).click();

    await expect(
      page.getByText(/Summarization provider error\./i),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('button', { name: /Retry/i })).toBeVisible();
  });
});
