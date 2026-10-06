import { expect, test } from '@playwright/test'

test.describe('Unverified stories', () => {
  test('pending story shows no AI text, only original titles and links', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="story-list"]')

    // Find the unverified story card (Apple product announcement)
    const unverifiedCard = page.locator('[data-testid="story-card"]:has-text("Непроверено")').first()
    await expect(unverifiedCard).toBeVisible()

    // Should NOT have a "Разгъни" expand button
    const expandBtn = unverifiedCard.locator('button[aria-expanded]')
    await expect(expandBtn).toHaveCount(0)

    // Should have links to original articles
    const links = unverifiedCard.locator('a[href]')
    await expect(links).toHaveCountGreaterThan(0)

    // Should NOT have story-detail section
    const detail = unverifiedCard.locator('[data-testid="story-detail"]')
    await expect(detail).toHaveCount(0)
  })
})
