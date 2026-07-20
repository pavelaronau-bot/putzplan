import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from '../shared/auth'
import { LoginPage } from '../pages/LoginPage'
import { UsersPage } from '../pages/UsersPage'
import { RolesPage } from '../pages/RolesPage'
import { ProfilePage } from '../pages/ProfilePage'
import { Spinner } from '../shared/ui'

export function App() {
  const { me, loading, logout, can } = useAuth()

  if (loading) return <Spinner label="Проверяем сессию…" />
  if (!me) return <LoginPage />

  return (
    <div className="shell">
      <aside>
        <div className="brand">PUTZPLAN</div>
        <nav>
          {can('users.read') && <NavLink to="/users">Пользователи</NavLink>}
          {can('roles.read') && <NavLink to="/roles">Роли и права</NavLink>}
          <NavLink to="/profile">Мой профиль</NavLink>
        </nav>
        <div className="user-box">
          <div>{me.full_name ?? me.email}</div>
          <small>{me.role}</small>
          <button onClick={() => void logout()}>Выйти</button>
        </div>
      </aside>
      <main>
        <Routes>
          <Route path="/users" element={can('users.read') ? <UsersPage /> : <Navigate to="/profile" />} />
          <Route path="/roles" element={can('roles.read') ? <RolesPage /> : <Navigate to="/profile" />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to={can('users.read') ? '/users' : '/profile'} />} />
        </Routes>
      </main>
    </div>
  )
}
