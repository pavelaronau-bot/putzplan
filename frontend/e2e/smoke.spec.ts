import { expect, test, type Page } from '@playwright/test'

/**
 * Сквозные сценарии Sprint 1:
 * вход → пользователи → создание → назначение роли → проверка прав.
 *
 * Требуют поднятых API и фронтенда.
 * В CI выполняются в задаче E2E · Playwright Chromium.
 */

const OWNER = {
  email: process.env.E2E_OWNER_EMAIL ?? 'owner@demo.putzplan.de',
  password: process.env.E2E_OWNER_PASSWORD ?? 'Owner12345678',
}

const TEST_PASSWORD = 'E2ePasswort12345'

async function login(
  page: Page,
  credentials: {
    email: string
    password: string
  },
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

  console.log('LOGIN STATUS:', loginResponse.status())

  expect(
    loginResponse.status(),
    `Вход пользователя ${credentials.email} должен завершиться успешно`,
  ).toBe(200)
}

async function openCreateUserModal(page: Page): Promise<void> {
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

  expect(
    rolesResponse.status(),
    'Запрос списка ролей должен завершиться успешно',
  ).toBe(200)
}

async function selectDispatcherRole(page: Page): Promise<void> {
  const roleSelect = page.getByLabel('Роль', { exact: true })

  await expect(roleSelect).toBeVisible()

  await expect(
    roleSelect.locator('option[value="dispatcher"]'),
  ).toHaveCount(1)

  await roleSelect.selectOption('dispatcher')
}

async function createDispatcher(
  page: Page,
  email: string,
  fullName: string,
): Promise<void> {
  await openCreateUserModal(page)

  await page.getByLabel('Имя и фамилия').fill(fullName)
  await page.getByLabel('E-Mail').fill(email)

  await selectDispatcherRole(page)

  await page.getByLabel(/Пароль/).fill(TEST_PASSWORD)

  await page
    .getByRole('button', { name: 'Сохранить' })
    .click()

  await expect(page.getByText(fullName)).toBeVisible()
}

test('владелец создаёт пользователя и назначает роль', async ({ page }) => {
  await login(page, OWNER)

  // Владелец имеет users.read, поэтому App автоматически
  // перенаправляет его с "/" на страницу "/users".
  await expect(
    page.getByRole('heading', { name: 'Пользователи' }),
  ).toBeVisible()

  const unique = Date.now().toString().slice(-8)
  const email = `e2e-${unique}@demo.putzplan.de`

  await createDispatcher(page, email, 'E2E Person')
})

test('владелец видит каталог прав', async ({ page }) => {
  await login(page, OWNER)

  await expect(
    page.getByRole('heading', { name: 'Пользователи' }),
  ).toBeVisible()

  await page
    .getByRole('link', { name: 'Роли и права' })
    .click()

  await expect(page.getByText('users.read')).toBeVisible()
})

test('пользователь без прав не видит раздел пользователей', async ({
  page,
}) => {
  await login(page, OWNER)

  await expect(
    page.getByRole('heading', { name: 'Пользователи' }),
  ).toBeVisible()

  const unique = Date.now().toString().slice(-8)
  const dispatcherEmail = `dispatcher-e2e-${unique}@demo.putzplan.de`
  const dispatcherName = `E2E Dispatcher ${unique}`

  // Создаём отдельного Dispatcher прямо в этом тесте.
  // Тест больше не зависит от пароля пользователя из seed_dev.py.
  await createDispatcher(
    page,
    dispatcherEmail,
    dispatcherName,
  )

  await page.getByRole('button', { name: 'Выйти' }).click()

  await expect(
    page.getByRole('button', { name: 'Войти' }),
  ).toBeVisible()

  await login(page, {
    email: dispatcherEmail,
    password: TEST_PASSWORD,
  })

  // Dispatcher не имеет users.read, поэтому App направляет его
  // на страницу собственного профиля.
  await expect(
    page.getByRole('heading', { name: 'Мой профиль' }),
  ).toBeVisible()

  await expect(
    page.getByRole('link', { name: 'Пользователи' }),
  ).toHaveCount(0)
})
