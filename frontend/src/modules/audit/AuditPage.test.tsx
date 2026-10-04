/**
 * 감사 — **서버가 거르는 칸을 쓰고, 접근 로그는 시스템 관리자에게만 보인다.**
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AuditPage from '@/modules/audit/AuditPage'
import { api } from '@/shared/api/client'

const auth = vi.hoisted(() => ({ admin: true }))

vi.mock('@/shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/client')>()
  return { ...actual, api: { ...actual.api, get: vi.fn() } }
})

vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { is_system_admin: auth.admin, memberships: [] } }),
}))

const EMPTY = { items: [], total: 0, limit: 50, offset: 0 }

describe('감사', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset().mockResolvedValue(EMPTY)
  })

  it('한 일 · 대상 표로 서버가 거른다', async () => {
    auth.admin = false
    render(<AuditPage />)
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    await userEvent.type(screen.getByLabelText('대상 표'), 'users')
    await waitFor(() =>
      expect(vi.mocked(api.get).mock.calls.some(([path]) => String(path).includes('target_table=users'))).toBe(
        true,
      ),
    )
    // 시스템 관리자가 아니면 접근 로그가 없다 — 남의 활동 이력이다.
    expect(screen.queryByRole('tab', { name: '접근 로그' })).toBeNull()
  })

  it('시스템 관리자는 접근 로그를 본다', async () => {
    auth.admin = true
    vi.mocked(api.get).mockImplementation(async (path: string) =>
      path.startsWith('/audit/access')
        ? {
            ...EMPTY,
            total: 1,
            items: [
              {
                id: 'x',
                user_label: '관리자',
                action: 'LOGIN',
                path: '/api/auth/login',
                method: 'POST',
                status_code: 200,
                request_id: 'r1',
                client_ip: '10.0.0.1',
                created_at: '2026-10-04T09:00:00Z',
              },
            ],
          }
        : EMPTY,
    )
    render(<AuditPage />)
    await userEvent.click(screen.getByRole('tab', { name: '접근 로그' }))
    await waitFor(() => expect(screen.getByText('10.0.0.1')).toBeDefined())
    expect(screen.getByText(/POST \/api\/auth\/login/)).toBeDefined()
  })
})
