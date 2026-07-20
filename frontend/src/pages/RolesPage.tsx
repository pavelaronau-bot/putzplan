import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { PermissionCatalogItem, Role } from '../api/types'
import { useAuth } from '../shared/auth'
import { ErrorState, Spinner } from '../shared/ui'

export function RolesPage() {
  const { can } = useAuth()
  const [roles, setRoles] = useState<Role[]>([])
  const [catalog, setCatalog] = useState<PermissionCatalogItem[]>([])
  const [selected, setSelected] = useState<Role | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [list, permissions] = await Promise.all([api.roles(), api.permissions()])
      setRoles(list); setCatalog(permissions)
    } catch (err) { setError(err) } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  async function open(role: Role) {
    try {
      const detail = await api.role(role.id)
      setSelected(detail)
      setChecked(new Set(detail.permissions ?? []))
    } catch (err) { setError(err) }
  }

  async function save() {
    if (!selected) return
    setSaving(true); setError(null)
    try {
      await api.setRolePermissions(selected.id, [...checked])
      await load()
      setSelected(null)
    } catch (err) { setError(err) } finally { setSaving(false) }
  }

  const modules = [...new Set(catalog.map((p) => p.module))].sort()

  if (loading) return <Spinner />
  if (error && roles.length === 0) return <ErrorState error={error} onRetry={load} />

  return (
    <section>
      <header className="page-head">
        <h2>Роли и права</h2>
      </header>

      <table>
        <thead><tr><th>Роль</th><th>Ключ</th><th>Тип</th><th>Прав</th><th /></tr></thead>
        <tbody>
          {roles.map((role) => (
            <tr key={role.id}>
              <td>{role.name}</td>
              <td><code>{role.key}</code></td>
              <td>{role.is_system ? 'системная' : 'своя'}</td>
              <td>{role.permissions_count}</td>
              <td className="row-actions">
                <button onClick={() => open(role)}>Права</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected && (
        <div className="modal-backdrop" onClick={() => setSelected(null)}>
          <div className="modal wide" onClick={(e) => e.stopPropagation()}>
            <h3>{selected.name}</h3>
            {selected.is_system && (
              <p className="muted">Системная роль: набор прав изменить нельзя.</p>
            )}
            {error ? <ErrorState error={error} /> : null}
            <div className="perm-grid">
              {modules.map((module) => (
                <fieldset key={module}>
                  <legend>{module}</legend>
                  {catalog.filter((p) => p.module === module).map((p) => (
                    <label key={p.key} className="perm">
                      <input type="checkbox" checked={checked.has(p.key)}
                             disabled={selected.is_system || !can('roles.permissions.manage')}
                             onChange={(e) => {
                               const next = new Set(checked)
                               e.target.checked ? next.add(p.key) : next.delete(p.key)
                               setChecked(next)
                             }} />
                      <span title={p.description ?? undefined}>{p.key}</span>
                    </label>
                  ))}
                </fieldset>
              ))}
            </div>
            <div className="modal-actions">
              <button onClick={() => setSelected(null)}>Закрыть</button>
              {can('roles.permissions.manage') && !selected.is_system && (
                <button onClick={save} disabled={saving}>
                  {saving ? 'Сохраняем…' : 'Сохранить права'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
