/**
 * 계정 — **여러 계정에 메일 한 통을 쓰도록 고른 계정의 주소를 복사한다.**
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AccountsAdminPage from '@/modules/accounts/AccountsAdminPage'
import { api } from '@/shared/api/client'

vi.mock('@/shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/client')>()
  return { ...actual, api: { ...actual.api, get: vi.fn() } }
})

function account(id: string, email: string, status = 'active') {
  return {
    id,
    email,
    display_name: `이름 ${id}`,
    status,
    is_system_admin: false,
    must_change_password: false,
    home_workspace_slug: null,
    requested_workspace_slug: 'mat-lab',
    memberships: [],
    created_at: '2026-11-01T00:00:00Z',
    decided_at: null,
    decision_note: null,
  }
}

const ACCOUNTS = [
  account('1', 'kim@corp.co.kr', 'pending'),
  account('2', 'hong@corp.co.kr'),
  account('3', 'admin'),
]

describe('계정', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset().mockImplementation(async (path: string) => {
      if (path === '/accounts/summary') return { active_system_admins: 2 }
      if (path.startsWith('/accounts')) return ACCOUNTS
      return []
    })
  })

  it('하나씩 고르거나 모두 골라 메일 주소를 복사한다', async () => {
    render(<AccountsAdminPage />)
    fireEvent.click(await screen.findByRole('checkbox', { name: '이름 2 고르기' }))
    expect(screen.getByRole('button', { name: '메일 주소 복사 (1명)' })).toBeEnabled()

    // 하나만 골랐으면 「모두」 는 반쯤 찬 칸이다.
    const all = screen.getByRole('checkbox', { name: '모든 계정 고르기' })
    expect(all).toHaveProperty('indeterminate', true)
    fireEvent.click(all)
    expect(screen.getByRole('button', { name: '메일 주소 복사 (2명)' })).toBeEnabled()
    // 설치 때 만든 짧은 아이디는 메일 주소가 아니다.
    expect(screen.getByText(/메일 주소가 아닌 아이디 1개는 뺐습니다: admin/)).toBeInTheDocument()

    fireEvent.click(all)
    expect(screen.getByRole('button', { name: '메일 주소 복사' })).toBeDisabled()
  })
})
