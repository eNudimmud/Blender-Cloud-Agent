import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60000,
  expect: { timeout: 15000 },
  workers: 1,
  fullyParallel: false,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8765',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
  projects: [
    { name: 'android-chromium', use: { ...devices['Pixel 7'] } },
    { name: 'desktop-chromium', use: { viewport: { width: 1280, height: 900 } } },
  ],
  webServer: {
    command: `${process.env.PYTHON_BIN || '.venv/bin/python'} -m tests.serve_e2e`,
    url: 'http://127.0.0.1:8765/health',
    timeout: 30000,
    reuseExistingServer: false,
  },
});
