import { defineConfig } from '@playwright/test';

// End-to-end tests against the running local stack (frontend on 5173, demo backend on 8020).
// They sign in with the Git-ignored synthetic demo credentials and write only to the
// disposable ct_demo database. See docs/LOCAL_DEVELOPMENT.md.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  outputDir: '../.local/ui-audit/e2e-results',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    viewport: { width: 1280, height: 800 },
    reducedMotion: 'reduce',
  },
});
