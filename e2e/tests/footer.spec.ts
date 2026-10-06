import { expect, test } from '@playwright/test'

const DISCLAIMER = 'Не е инвестиционен съвет'

test.describe('Footer disclaimer', () => {
  test('disclaimer is present on Dashboard', async ({ page }) => {
    await page.goto('/')
    const footer = page.locator('[data-testid="footer"]')
    await expect(footer).toBeVisible()
    await expect(footer).toContainText(DISCLAIMER)
  })

  test('disclaimer is present on Debug page', async ({ page }) => {
    await page.goto('/debug')
    const footer = page.locator('[data-testid="footer"]')
    await expect(footer).toBeVisible()
    await expect(footer).toContainText(DISCLAIMER)
  })
})
