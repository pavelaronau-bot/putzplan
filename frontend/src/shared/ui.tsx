import type { ReactNode } from 'react'
import { RequestFailed } from '../api/client'

export function Spinner({ label = 'Загрузка…' }: { label?: string }) {
  return <div className="state" role="status" aria-live="polite">{label}</div>
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="state empty">
      <b>{title}</b>
      {hint && <p>{hint}</p>}
      {action}
    </div>
  )
}

/** Ошибка всегда показывает request_id — по нему поддержка находит запрос в логах. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const failed = error instanceof RequestFailed ? error : null
  return (
    <div className="state error" role="alert">
      <b>{failed?.error.message ?? 'Не удалось выполнить запрос'}</b>
      {failed?.error.details?.length ? (
        <ul>{failed.error.details.map((d, i) => (
          <li key={i}>{d.field ? `${d.field}: ` : ''}{d.message}</li>))}
        </ul>
      ) : null}
      <p className="tech">
        код: {failed?.error.code ?? 'network_error'} · request_id: {failed?.error.request_id ?? '—'}
      </p>
      {onRetry && <button onClick={onRetry}>Повторить</button>}
    </div>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    active: 'активен', invited: 'приглашён', terminated: 'уволен',
    temporarily_blocked: 'заблокирован', on_leave: 'в отпуске', sick: 'на больничном',
    password_reset: 'смена пароля', archived: 'архив',
  }
  return <span className={`badge badge-${status}`}>{label[status] ?? status}</span>
}
