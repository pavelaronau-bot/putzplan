import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LoginPage } from '../src/pages/LoginPage'
import { AuthProvider } from '../src/shared/auth'
import { api } from '../src/api/client'

vi.mock('../src/api/client', async () => {
  const actual = await vi.importActual<typeof import('../src/api/client')>('../src/api/client')
  return {
    ...actual,
    api: {
      me: vi.fn().mockRejectedValue(new Error('нет сессии')),
      login: vi.fn(),
      logout: vi.fn(),
    },
  }
})

function renderLogin() {
  return render(<AuthProvider><LoginPage /></AuthProvider>)
}

describe('Страница входа', () => {
  beforeEach(() => vi.clearAllMocks())

  it('показывает форму без демонстрационных учётных данных', async () => {
    renderLogin()
    expect(await screen.findByLabelText(/E-Mail/)).toBeDefined()
    expect(screen.getByLabelText(/Пароль/)).toBeDefined()
    expect(document.body.textContent).not.toMatch(/demo|Demo|пароль:.*\d/)
  })

  it('блокирует отправку при некорректном e-mail', async () => {
    renderLogin()
    const email = await screen.findByLabelText(/E-Mail/)
    fireEvent.change(email, { target: { value: 'не-адрес' } })
    fireEvent.change(screen.getByLabelText(/Пароль/), { target: { value: 'Passwort12345' } })
    fireEvent.click(screen.getByRole('button', { name: /Войти/ }))
    await waitFor(() => expect(screen.getByText(/корректный e-mail/i)).toBeDefined())
    expect(api.login).not.toHaveBeenCalled()
  })

  it('блокирует отправку при коротком пароле', async () => {
    renderLogin()
    fireEvent.change(await screen.findByLabelText(/E-Mail/), { target: { value: 'a@b.de' } })
    fireEvent.change(screen.getByLabelText(/Пароль/), { target: { value: 'kurz' } })
    fireEvent.click(screen.getByRole('button', { name: /Войти/ }))
    await waitFor(() => expect(screen.getByText(/Минимум 8 символов/)).toBeDefined())
    expect(api.login).not.toHaveBeenCalled()
  })

  it('отправляет корректные данные и вызывает вход', async () => {
    ;(api.login as ReturnType<typeof vi.fn>).mockResolvedValue({ access_token: 'tok', expires_in: 900 })
    ;(api.me as ReturnType<typeof vi.fn>).mockResolvedValueOnce(Promise.reject(new Error('нет сессии')))
    renderLogin()
    fireEvent.change(await screen.findByLabelText(/E-Mail/), { target: { value: 'owner@demo.putzplan.de' } })
    fireEvent.change(screen.getByLabelText(/Пароль/), { target: { value: 'Owner12345678' } })
    fireEvent.click(screen.getByRole('button', { name: /Войти/ }))
    await waitFor(() => expect(api.login).toHaveBeenCalledWith('owner@demo.putzplan.de', 'Owner12345678'))
  })
})
