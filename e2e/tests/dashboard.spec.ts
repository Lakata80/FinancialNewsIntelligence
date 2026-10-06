import { expect, test } from '@playwright/test'

test.describe('Dashboard', () => {
  test('loads NVDA stories in 24h window', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="story-list"]')

    // Select NVDA from watchlist
    await page.click('[data-testid="watchlist"] button:has-text("NVDA")')
    await page.waitForSelector('[data-testid="story-card"]')

    const cards = page.locator('[data-testid="story-card"]')
    await expect(cards).toHaveCountGreaterThan(0)

    // Funnel stats should show
    await expect(page.locator('[data-testid="funnel-stats"]')).toBeVisible()
  })

  test('story list shows results without ticker filter', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="story-list"]')

    const cards = page.locator('[data-testid="story-card"]')
    await expect(cards).toHaveCountGreaterThan(0)
  })
})
