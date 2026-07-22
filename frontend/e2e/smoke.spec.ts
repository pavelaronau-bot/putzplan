import { expect, test, type Page } from '@playwright/test'

/**
 * Сквозные сценарии Sprint 1:
 * вход → пользователи → создание пользователя → назначение роли.
 *
 * Требуют запущенных API и фронтенда.
 * В CI выполняются в задаче E2E · Playwright Chromium.
 */

// Учётные данные берутся из переменных окружения.
// Значения по умолчанию предназначены для демонстрационной базы.
const OWNER = {
  email: process.env.E2E_OWNER_EMAIL ?? 'owner@demo.putzplan.de',
  password: process.env.E2E_OWNER_PASSWORD ?? 'Owner12345678',
}

const DISPATCHER = {
  email:
    process.env.E2E_DISPATCHER_EMAIL ?? 'dispatcher@demo.putzplan.de',
  password:
    process.env.E2E_DISPATCHER_PASSWORD ?? 'Dispatcher12345678',
}

/**
 * Выполняет вход и выводит в лог настоящий ответ API.
 * Это временная диагностика и не изменяет данные приложения.
 */
async function login(
  page: Page,
  credentials: {
    email: string
    password: string
  },
  label: string,
): Promise<void> {
  await page.goto('/')

  await page.getByLabel('E-Mail').fill(credentials.email)
  await page.getByLabel('Пароль').fill(credentials.password)

  const loginResponsePromise = page.waitForResponse(
    response =>
      response.url().includes('/api/v1/auth/login') &&
      response.request().method() === 'POST',
  )

  await page.getByRole('button', { name: 'Войти' }).click()

  const loginResponse = await loginResponsePromise

  console.log(`${label} LOGIN STATUS:`, loginResponse.status())
  console.log(`${label} LOGIN BODY:`, await loginResponse.text())
  console.log(`${label} CURRENT URL:`, page.url())
}

test('владелец создаёт пользователя и назначает роль', async ({ page }) => {
  await login(page, OWNER, 'OWNER')

  await expect(
    page.getByRole('heading', { name: 'Мой профиль' }),
  ).toBeVisible()

  await page.getByRole('link', { name: 'Пользователи' }).click()

  await expect(
    page.getByRole('heading', { name: 'Пользователи' }),
  ).toBeVisible()

  const unique = Date.now().toString().slice(-8)

  // Настоящий запрос ролей выполняется самим интерфейсом
  // после открытия окна добавления пользователя.
  const rolesResponsePromise = page.waitForResponse(
    response =>
      response.url().includes('/api/v1/roles') &&
      response.request().method() === 'GET',
  )

  await page
    .getByRole('button', { name: 'Добавить пользователя' })
    .click()

  const rolesResponse = await rolesResponsePromise

  console.log('ROLES STATUS:', rolesResponse.status())
  console.log('ROLES BODY:', await rolesResponse.text())

  await page.getByLabel('Имя и фамилия').fill('E2E Person')

  await page
    .getByLabel('E-Mail')
    .fill(`e2e-${unique}@demo.putzplan.de`)

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
  await login(page, OWNER, 'OWNER')

  await expect(
    page.getByRole('heading', { name: 'Мой профиль' }),
  ).toBeVisible()

  await page.getByRole('link', { name: 'Роли' }).click()

  await expect(page.getByText('users.read')).toBeVisible()
})

test('пользователь без прав не видит раздел пользователей', async ({
  page,
}) => {
  await login(page, DISPATCHER, 'DISPATCHER')

  await expect(
    page.getByRole('heading', { name: 'Мой профиль' }),
  ).toBeVisible()

  await expect(
    page.getByRole('link', { name: 'Пользователи' }),
  ).toHaveCount(0)
})
