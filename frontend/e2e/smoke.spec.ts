import { expect, test } from '@playwright/test'

/**
 * Сквозной сценарий Sprint 1: вход → пользователи → создание → назначение роли.
 * Требует поднятых API и фронтенда; в CI запускается на шаге e2e.
 */
// Учётные данные берутся из окружения; значения по умолчанию существуют
// только для локального прогона против демонстрационной базы.
const OWNER = {
  email: process.env.E2E_OWNER_EMAIL ?? 'owner@demo.putzplan.de',
  password: process.env.E2E_OWNER_PASSWORD ?? 'Owner12345678',
}
const DISPATCHER = {
  email: process.env.E2E_DISPATCHER_EMAIL ?? 'disp@demo.putzplan.de',
  password: process.env.E2E_DISPATCHER_PASSWORD ?? 'Disp12345678',
}

test('вход, список пользователей, создание пользователя, роли', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('E-Mail').fill(OWNER.email)
  await page.getByLabel('Пароль').fill(OWNER.password)
  await page.getByRole('button', { name: 'Войти' }).click()

  await expect(page.getByRole('heading', { name: 'Пользователи' })).toBeVisible()
  await expect(page.locator('table tbody tr').first()).toBeVisible()

  const unique = Date.now().toString().slice(-8)
  await page.getByRole('button', { name: 'Добавить пользователя' }).click()
  await page.getByLabel('Имя и фамилия').fill('E2E Person')
  await page.getByLabel('E-Mail').fill(`e2e-${unique}@demo.putzplan.de`)
  await page.getByLabel('Роль').selectOption('dispatcher')
  await page.getByLabel(/Пароль/).fill('E2ePasswort12345')
  await page.getByRole('button', { name: 'Сохранить' }).click()

  await expect(page.getByText('E2E Person')).toBeVisible()

  await page.getByRole('link', { name: 'Роли и права' }).click()
  await expect(page.getByRole('heading', { name: 'Роли и права' })).toBeVisible()
  await page.getByRole('button', { name: 'Права' }).first().click()
  await expect(page.getByText('users.read')).toBeVisible()
})

test('пользователь без прав не видит раздел пользователей', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('E-Mail').fill(DISPATCHER.email)
  await page.getByLabel('Пароль').fill(DISPATCHER.password)
  await page.getByRole('button', { name: 'Войти' }).click()

  await expect(page.getByRole('heading', { name: 'Мой профиль' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Пользователи' })).toHaveCount(0)
})
