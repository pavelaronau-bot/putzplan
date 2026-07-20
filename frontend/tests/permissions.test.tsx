import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ErrorState, StatusBadge } from '../src/shared/ui'
import { RequestFailed } from '../src/api/client'

describe('Обработка ошибок и статусов', () => {
  it('показывает request_id в технической информации', () => {
    const failure = new RequestFailed(403, {
      code: 'forbidden', message: 'Нет права users.read',
      request_id: 'req_abc123', details: [{ field: 'permission', message: 'users.read' }],
    })
    render(<ErrorState error={failure} />)
    expect(screen.getByRole('alert').textContent).toContain('req_abc123')
    expect(screen.getByRole('alert').textContent).toContain('Нет права users.read')
    expect(screen.getByRole('alert').textContent).toContain('permission: users.read')
  })

  it('показывает понятный текст при сетевой ошибке', () => {
    render(<ErrorState error={new Error('boom')} />)
    expect(screen.getByRole('alert').textContent).toContain('Не удалось выполнить запрос')
  })

  it('переводит статусы пользователя на русский', () => {
    const { rerender } = render(<StatusBadge status="active" />)
    expect(screen.getByText('активен')).toBeDefined()
    rerender(<StatusBadge status="terminated" />)
    expect(screen.getByText('уволен')).toBeDefined()
  })
})
