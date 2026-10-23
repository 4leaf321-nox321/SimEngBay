/**
 * 해석 화면의 틀 — **두 번째 사이드바가 없다**(2026-10-23, ADR 0014). 작업공간은 「해석」 목록 위의
 * 탭이고(`SimulationsPage.test`), 상세 화면은 넓게 쓴다. 어느 작업공간인지는 주소(`?scope=`)가 정본이다.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'me', is_system_admin: false, memberships: [] } }),
}))

import SimulationsLayout, { listPath, workScope } from '@/modules/simulations/SimulationsLayout'

describe('해석 화면의 틀', () => {
  it('안의 화면만 그린다 — 작업공간 사이드바가 없다', () => {
    render(
      <MemoryRouter initialEntries={['/simulations/abc']}>
        <Routes>
          <Route path="/simulations" element={<SimulationsLayout />}>
            <Route path=":id" element={<p>작업 화면</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByText('작업 화면')).toBeDefined()
    expect(screen.queryByRole('complementary', { name: '작업공간' })).toBeNull()
  })

  it('작업공간은 주소가 정본 — 기본(개인 작업 · 종류 전체)은 주소에 안 적는다', () => {
    expect(workScope(new URLSearchParams('scope=published'))).toBe('published')
    expect(workScope(new URLSearchParams('scope=이상한값'))).toBe('mine')
    expect(listPath('mine')).toBe('/simulations')
    expect(listPath('published', 'doe')).toBe('/simulations?scope=published&kind=doe')
  })
})
