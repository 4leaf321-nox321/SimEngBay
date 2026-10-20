/**
 * 해석 화면의 두 번째 사이드바 — **개인 작업과 공용 작업공간을 자리로 가른다**(ADR 0008).
 * 어느 쪽인지는 주소(`?scope=`)가 정본이고, 「전체」 는 시스템 관리자에게만 있다.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SimulationsLayout from '@/modules/simulations/SimulationsLayout'

const auth = vi.hoisted(() => ({ admin: false }))

vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'me', is_system_admin: auth.admin, memberships: [] } }),
}))

function Where() {
  const { pathname, search } = useLocation()
  return <p>지금 {pathname + search}</p>
}

function show(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/simulations" element={<SimulationsLayout />}>
          <Route index element={<Where />} />
          <Route path="studies" element={<Where />} />
          <Route path=":id" element={<Where />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

function sidebar() {
  return within(screen.getByRole('complementary', { name: '작업공간' }))
}

describe('해석 작업공간', () => {
  beforeEach(() => {
    auth.admin = false
  })

  it('개인 작업과 공용 작업공간을 가르고, 주소가 고른 칸을 켠다', () => {
    show('/simulations?scope=published')
    expect(sidebar().getByText('개인 작업')).toBeDefined()
    expect(sidebar().getByText('공용 작업공간')).toBeDefined()
    // 「전체」 는 시스템 관리자에게만.
    expect(sidebar().queryByText('전체')).toBeNull()
    const active = sidebar().getByRole('link', { current: 'page' })
    expect(active.getAttribute('href')).toBe('/simulations?scope=published')
    expect(active.textContent).toContain('해석 작업')
  })

  it('주소에 작업공간이 없으면 개인 작업이다 — 상세 화면은 어느 칸도 켜지 않는다', () => {
    const { unmount } = show('/simulations')
    expect(sidebar().getByRole('link', { current: 'page' }).getAttribute('href')).toBe('/simulations')
    unmount()
    show('/simulations/abc')
    expect(sidebar().queryByRole('link', { current: 'page' })).toBeNull()
  })

  it('칸을 누르면 그 작업공간의 화면으로 간다', async () => {
    show('/simulations')
    const links = sidebar().getAllByRole('link', { name: /DOE 비교/ })
    // 개인 · 공용 차례다.
    await userEvent.click(links[1])
    expect(screen.getByText('지금 /simulations/studies?scope=published')).toBeDefined()
  })

  it('시스템 관리자는 모두의 작업(전체)도 본다', () => {
    auth.admin = true
    show('/simulations?scope=all')
    expect(sidebar().getByText('전체')).toBeDefined()
    expect(sidebar().getByRole('link', { current: 'page' }).getAttribute('href')).toBe(
      '/simulations?scope=all',
    )
  })
})
