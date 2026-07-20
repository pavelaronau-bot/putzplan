import { useState } from 'react'
import { useAuth } from '../shared/auth'
import { ErrorState } from '../shared/ui'

/** Промышленный вход: без демонстрационных кнопок и подстановки паролей. */
export function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [touched, setTouched] = useState(false)

  const emailValid = /^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$/.test(email)
  const passwordValid = password.length >= 8

  // Кнопка не блокируется при неверном вводе: иначе пользователь видит
  // неактивную кнопку без объяснения. Проверка выполняется при отправке.
  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setTouched(true)
    if (!emailValid || !passwordValid || busy) return
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <form onSubmit={onSubmit} noValidate>
        <h1>PUTZPLAN</h1>
        <p className="muted">Вход в систему управления уборкой</p>

        <label>
          E-Mail
          <input type="email" value={email} autoComplete="username" required
                 onChange={(e) => setEmail(e.target.value)} onBlur={() => setTouched(true)} />
        </label>
        {touched && !emailValid && <span className="field-error">Укажите корректный e-mail</span>}

        <label>
          Пароль
          <input type="password" value={password} autoComplete="current-password" required
                 onChange={(e) => setPassword(e.target.value)} onBlur={() => setTouched(true)} />
        </label>
        {touched && !passwordValid && <span className="field-error">Минимум 8 символов</span>}

        {error ? <ErrorState error={error} /> : null}

        <button type="submit" disabled={busy}>{busy ? 'Проверяем…' : 'Войти'}</button>
      </form>
    </div>
  )
}
