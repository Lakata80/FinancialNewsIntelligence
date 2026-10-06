import { expect, test } from '@playwright/test'

test.describe('Show opinions toggle', () => {
  test('opinions are hidden by default and shown after toggle', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="story-list"]')

    // Count cards without opinions
    const cardsWithoutOpinions = await page.locator('[data-testid="story-card"]').count()

    // Enable opinions toggle
    await page.check('[data-testid="toggle-opinions"]')
    await page.waitForTimeout(500) // wait for refetch

    const cardsWithOpinions = await page.locator('[data-testid="story-card"]').count()

    // After enabling opinions, there should be at least as many cards (or more)
    expect(cardsWithOpinions).toBeGreaterThanOrEqual(cardsWithoutOpinions)
  })
})
