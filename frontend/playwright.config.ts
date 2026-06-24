import { defineConfig, devices } from '@playwright/test';

// Playwright E2E config for the AI document-summarization feature.
//
// Two kinds of specs live under ./e2e:
//   * *.smoke.spec.ts  -> fully offline; Storage + Edge Function are mocked via
//                         page.route, so they always run deterministically.
//   * *.live.spec.ts   -> exercises the real local stack (make up) and a real
//                         Azure/Claude call; gated behind RUN_AI_E2E=1.
//
// baseURL points at the local frontend (Vite dev server / Docker frontend on
// :3000). When no server is already listening, Playwright starts `npm run dev`.
const PORT = 3000;
const baseURL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: 'e2e-results/results.json' }]],
  timeout: 30_000,
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: {
    command: 'npm run dev -- --port 3000 --strictPort',
    url: baseURL,
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
