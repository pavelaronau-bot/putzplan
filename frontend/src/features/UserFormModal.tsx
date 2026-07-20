import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Role, User } from '../api/types'
import { ErrorState } from '../shared/ui'

/** Создание и редактирование пользователя, включая назначение роли. */
export function UserFormModal({ user, onClose, onSaved }:
  { user: User | null; onClose: () => void; onSaved: () => void }) {
  const [roles, setRoles] = useState<Role[]>([])
  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [position, setPosition] = useState(user?.position ?? '')
  const [role, setRole] = useState(user?.role ?? 'worker')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { api.roles().then(setRoles).catch(setError) }, [])

  const isEdit = user !== null
  const nameValid = fullName.trim().length >= 2
  const emailValid = isEdit || /^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$/.test(email)
  const passwordValid = password === '' || password.length >= 12

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!nameValid || !emailValid || !passwordValid) return
    setBusy(true); setError(null)
    try {
      if (isEdit) {
        await api.updateUser(user.id, { full_name: fullName, position, role })
      } else {
        await api.createUser({ email, full_name: fullName, role,
                               position: position || undefined,
                               password: password || undefined })
      }
      onSaved()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit} noValidate>
        <h3>{isEdit ? 'Изменение пользователя' : 'Новый пользователь'}</h3>

        <label>Имя и фамилия
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} required />
        </label>
        {!nameValid && <span className="field-error">Минимум 2 символа</span>}

        {!isEdit && (
          <>
            <label>E-Mail
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            {!emailValid && <span className="field-error">Укажите корректный e-mail</span>}
          </>
        )}

        <label>Должность
          <input value={position} onChange={(e) => setPosition(e.target.value)} />
        </label>

        <label>Роль
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {roles.map((r) => <option key={r.id} value={r.key}>{r.name}</option>)}
          </select>
        </label>

        {!isEdit && (
          <>
            <label>Пароль (пусто — отправить приглашение)
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            {!passwordValid && <span className="field-error">Минимум 12 символов</span>}
          </>
        )}

        {error ? <ErrorState error={error} /> : null}

        <div className="modal-actions">
          <button type="button" onClick={onClose}>Отмена</button>
          <button type="submit" disabled={busy || !nameValid || !emailValid || !passwordValid}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </div>
      </form>
    </div>
  )
}
