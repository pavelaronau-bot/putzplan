import { useAuth } from '../shared/auth'
import { StatusBadge } from '../shared/ui'

export function ProfilePage() {
  const { me } = useAuth()
  if (!me) return null
  const modules = [...new Set(me.permissions.map((p) => p.key.split('.')[0]))].sort()
  return (
    <section>
      <header className="page-head"><h2>Мой профиль</h2></header>
      <dl className="kv">
        <dt>Имя</dt><dd>{me.full_name ?? '—'}</dd>
        <dt>E-Mail</dt><dd>{me.email ?? '—'}</dd>
        <dt>Должность</dt><dd>{me.position ?? '—'}</dd>
        <dt>Роль</dt><dd><code>{me.role}</code></dd>
        <dt>Статус</dt><dd><StatusBadge status={me.status} /></dd>
        <dt>Последний вход</dt>
        <dd>{me.last_login_at ? new Date(me.last_login_at).toLocaleString('ru-RU') : '—'}</dd>
      </dl>
      <h3>Мои права ({me.permissions.length})</h3>
      <div className="perm-grid">
        {modules.map((module) => (
          <fieldset key={module}>
            <legend>{module}</legend>
            {me.permissions.filter((p) => p.key.startsWith(`${module}.`)).map((p) => (
              <div key={p.key} className="perm"><code>{p.key}</code> <small>{p.scope}</small></div>
            ))}
          </fieldset>
        ))}
      </div>
    </section>
  )
}
