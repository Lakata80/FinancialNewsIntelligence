import { expect, test } from '@playwright/test'

test.describe('Story card expand', () => {
  test('expanding a verified card shows at least one fact with English quote and link', async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('[data-testid="story-card"]')

    // Find the first verified story card and expand it
    const expandBtn = page.locator('[data-testid="story-card"] button[aria-expanded="false"]').first()
    await expandBtn.click()

    // Story detail should appear
    await page.waitForSelector('[data-testid="story-detail"]')

    // At least one fact item should be visible
    const facts = page.locator('[data-testid="fact-item"]')
    await expect(facts).toHaveCountGreaterThan(0)

    // Evidence quote should be present
    const quote = page.locator('[data-testid="evidence-quote"]').first()
    await expect(quote).toBeVisible()

    // Link to original article should be present
    const link = page.locator('[data-testid="evidence-link"]').first()
    await expect(link).toBeVisible()
    const href = await link.getAttribute('href')
    expect(href).toBeTruthy()
    expect(href).toContain('http')
  })
})
