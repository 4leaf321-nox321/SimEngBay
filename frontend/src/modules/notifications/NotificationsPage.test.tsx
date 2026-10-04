/**
 * 알림 — **하나씩 읽는다.** 「모두 읽음」 밖에 없으면 하나를 확인하려다 나머지까지 읽은 것이
 * 된다.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import NotificationsPage from '@/modules/notifications/NotificationsPage'
import { api } from '@/shared/api/client'

vi.mock('@/shared/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/api/client')>()
  return { ...actual, api: { ...actual.api, get: vi.fn(), post: vi.fn() } }
})

const NOW = '2026-10-04T09:00:00Z'

describe('알림', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset().mockResolvedValue([
      { id: 'a', kind: 'account', title: '가입 승인', body: null, link: '/profile', read_at: null, created_at: NOW },
      { id: 'b', kind: 'account', title: '지난 알림', body: null, link: null, read_at: NOW, created_at: NOW },
    ])
    vi.mocked(api.post).mockReset().mockResolvedValue({})
  })

  it('읽지 않은 알림 하나만 읽음으로 바꾼다', async () => {
    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('가입 승인')).toBeDefined())
    // 읽은 알림에는 「읽음」 단추가 없다.
    expect(screen.getAllByRole('button', { name: '읽음' })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: '읽음' }))
    expect(api.post).toHaveBeenCalledWith('/notifications/a/read')
  })

  it('다른 플랫폼의 말(교정 만료)을 쓰지 않는다', async () => {
    render(
      <MemoryRouter>
        <NotificationsPage />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('가입 승인')).toBeDefined())
    expect(screen.queryByText(/교정 만료/)).toBeNull()
  })
})
