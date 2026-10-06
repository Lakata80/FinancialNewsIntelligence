import { expect, test } from '@playwright/test'

test.describe('Quarantine', () => {
  test('quarantined article appears in Debug but not on Dashboard', async ({ page }) => {
    // Dashboard should not show quarantined article
    await page.goto('/')
    await page.waitForSelector('[data-testid="story-list"]')

    const dashboardContent = await page.locator('[data-testid="story-list"]').textContent()
    expect(dashboardContent).not.toContain('Buy NVDA now!')

    // Debug page should show it in quarantine table
    await page.goto('/debug')
    await page.waitForSelector('[data-testid="quarantine-table"]')

    const quarantineTable = page.locator('[data-testid="quarantine-table"]')
    await expect(quarantineTable).toContainText('Buy NVDA now!')
  })
})
