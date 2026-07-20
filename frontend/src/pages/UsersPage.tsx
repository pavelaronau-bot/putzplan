import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Page, User } from '../api/types'
import { useAuth } from '../shared/auth'
import { EmptyState, ErrorState, Spinner, StatusBadge } from '../shared/ui'
import { UserFormModal } from '../features/UserFormModal'

const PAGE_SIZE = 20

export function UsersPage() {
  const { can } = useAuth()
  const [page, setPage] = useState<Page<User> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [offset, setOffset] = useState(0)
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<User | null>(null)
  const [creating, setCreating] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setPage(await api.users({ limit: PAGE_SIZE, offset, status: status || undefined,
                                search: search || undefined }))
    } catch (err) {
      setError(err)
    } finally {
      setLoading(false)
    }
  }, [offset, status, search])

  useEffect(() => { void load() }, [load])

  async function deactivate(user: User) {
    const reason = window.prompt(`Причина деактивации ${user.full_name ?? user.email}:`)
    if (!reason || reason.trim().length < 4) return
    try {
      await api.deactivateUser(user.id, reason.trim())
      await load()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <section>
      <header className="page-head">
        <div>
          <h2>Пользователи</h2>
          {page && <p className="muted">{page.total} учётных записей</p>}
        </div>
        {can('users.create') && (
          <button onClick={() => setCreating(true)}>Добавить пользователя</button>
        )}
      </header>

      <div className="filters">
        <input placeholder="Поиск: имя, e-mail, должность" value={search}
               onChange={(e) => { setOffset(0); setSearch(e.target.value) }} />
        <select value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value) }}>
          <option value="">Все статусы</option>
          <option value="active">Активные</option>
          <option value="invited">Приглашённые</option>
          <option value="terminated">Уволенные</option>
        </select>
      </div>

      {loading && <Spinner />}
      {!loading && error !== null && <ErrorState error={error} onRetry={load} />}
      {!loading && !error && page && page.data.length === 0 && (
        <EmptyState title="Пользователи не найдены" hint="Измените фильтры или добавьте сотрудника" />
      )}

      {!loading && !error && page && page.data.length > 0 && (
        <>
          <table>
            <thead>
              <tr>
                <th>Имя</th><th>E-Mail</th><th>Должность</th>
                <th>Роль</th><th>Статус</th><th>Последний вход</th><th />
              </tr>
            </thead>
            <tbody>
              {page.data.map((user) => (
                <tr key={user.id}>
                  <td>{user.full_name ?? '—'}</td>
                  <td>{user.email ?? '—'}</td>
                  <td>{user.position ?? '—'}</td>
                  <td><code>{user.role}</code></td>
                  <td><StatusBadge status={user.status} /></td>
                  <td>{user.last_login_at ? new Date(user.last_login_at).toLocaleString('ru-RU') : 'ни разу'}</td>
                  <td className="row-actions">
                    {can('users.update') && <button onClick={() => setEditing(user)}>Изменить</button>}
                    {can('users.deactivate') && user.status === 'active' && (
                      <button className="danger" onClick={() => deactivate(user)}>Деактивировать</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="pager">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
              Назад
            </button>
            <span>{offset + 1}–{Math.min(offset + PAGE_SIZE, page.total)} из {page.total}</span>
            <button disabled={page.next_offset === null}
                    onClick={() => setOffset(page.next_offset ?? offset)}>Вперёд</button>
          </div>
        </>
      )}

      {(creating || editing) && (
        <UserFormModal user={editing} onClose={() => { setCreating(false); setEditing(null) }}
                       onSaved={() => { setCreating(false); setEditing(null); void load() }} />
      )}
    </section>
  )
}
