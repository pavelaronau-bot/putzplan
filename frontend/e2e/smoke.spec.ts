import { expect, test } from '@playwright/test'

/**
 * Сквозной сценарий Sprint 1:
 * вход → пользователи → создание → назначение роли.
 *
 * Требует поднятых API и фронтенда;
 * в CI запускается на шаге e2e.
 */

// Учётные данные берутся из окружения.
// Значения по умолчанию используются только для локального прогона
// против демонстрационной базы.
const OWNER = {
  email: process.env.E2E_OWNER_EMAIL ?? 'owner@demo.putzplan.de',
  password: process.env.E2E_OWNER_PASSWORD ?? 'Owner12345678',
}

const DISPATCHER = {
  email: process.env.E2E_DISPATCHER_EMAIL ?? 'dispatcher@demo.putzplan.de',
  password: process.env.E2E_DISPATCHER_PASSWORD ?? 'Dispatcher12345678',
}

test('владелец создаёт пользователя и назначает роль', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('E-Mail').fill(OWNER.email)
  await page.getByLabel('Пароль').fill(OWNER.password)
  await page.getByRole('button', { name: 'Войти' }).click()

  await expect(
    page.getByRole('heading', { name: 'Мой профиль' }),
  ).toBeVisible()

  await page.getByRole('link', { name: 'Пользователи' }).click()

  await expect(
    page.getByRole('heading', { name: 'Пользователи' }),
  ).toBeVisible()

  const unique = Date.now().toString().slice(-8)

  await page
    .getByRole('button', { name: 'Добавить пользователя' })
    .click()

  await page.getByLabel('Имя и фамилия').fill('E2E Person')
  await page
    .getByLabel('E-Mail')
    .fill(`e2e-${unique}@demo.putzplan.de`)

  // Временная диагностика endpoint ролей.
  const rolesResponse = await page.request.get(
    'http://127.0.0.1:8000/api/v1/roles',
  )

  console.log('ROLES STATUS:', rolesResponse.status())
  console.log('ROLES BODY:', await rolesResponse.text())

  const roleSelect = page.getByLabel('Роль', { exact: true })

  await expect(roleSelect).toBeVisible()

  await expect(
    roleSelect.locator('option[value="dispatcher"]'),
  ).toHaveCount(1)

  await roleSelect.selectOption('dispatcher')

  await page.getByLabel(/Пароль/).fill('E2ePasswort12345')

  await page
    .getByRole('button', { name: 'Сохранить' })
    .click()

  await expect(page.getByText('E2E Person')).toBeVisible()
})

test('владелец видит каталог прав', async ({ page }) => {
  await page.goto('/')

  await page.getByLabel('E-Mail').fill(OWNER.email)
  await page.getByLabel('Пароль').fill(OWNER.password)
  await page.getByRole('button', { name: 'Войти' }).click()

  await page.getByRole('link', { name: 'Роли' }).click()

  await expect(page.getByText('users.read')).toBeVisible()
})

test('пользователь без прав не видит раздел пользователей', async ({
  page,
}) => {
  await page.goto('/')

  await page.getByLabel('E-Mail').fill(DISPATCHER.email)
  await page.getByLabel('Пароль').fill(DISPATCHER.password)
  await page.getByRole('button', { name: 'Войти' }).click()

  await expect(
    page.getByRole('heading', { name: 'Мой профиль' }),
  ).toBeVisible()

  await expect(
    page.getByRole('link', { name: 'Пользователи' }),
  ).toHaveCount(0)
})
