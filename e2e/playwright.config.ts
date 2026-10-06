import { defineConfig, devices } from '@playwright/test'
import * as path from 'path'

const root = path.resolve(__dirname, '..')
const testDbPath = path.join(__dirname, 'test.db').replace(/\\/g, '/')

export default defineConfig({
  testDir: './tests',
  retries: 0,
  globalSetup: './setup/global-setup.ts',
  use: {
    baseURL: 'http://localhost:5173',
  },
  webServer: [
    {
      command: `uv run uvicorn app.main:app --port 8000`,
      url: 'http://localhost:8000/health',
      reuseExistingServer: true,
      cwd: path.join(root, 'backend'),
      env: {
        DATABASE_URL: `sqlite:///${testDbPath}`,
      },
      timeout: 30_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      cwd: path.join(root, 'frontend'),
      timeout: 30_000,
    },
  ],
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
