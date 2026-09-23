/**
 * 설계점 비교 — **이것이 DOE 를 돌린 이유다.**
 *
 * 여기서 지키는 것은 읽는 방식이다: 아직 안 끝난 점을 감추지 않는가, 축을 고를 수 있는가,
 * 결과가 없는 점을 0 으로 그리지 않는가.
 */

import { cloneElement } from 'react'
import type { ReactElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 400, height: 300 } as Record<string, unknown>),
  }
})

import { simulationApi } from '@/modules/simulations/api'
import StudyDetailPage from '@/modules/simulations/StudyDetailPage'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return { ...actual, simulationApi: { ...actual.simulationApi, study: vi.fn() } }
})

const STUDY = {
  study_id: '3f9a21',
  name: '브래킷_두께훑기',
  factors: ['두께'],
  points: [
    {
      simulation_id: '11111111-1111-1111-1111-111111111111',
      number: 1,
      params: { 두께: 6 },
      status: 'done',
      error_code: null,
      first_elastic_hz: 1336.4,
      mass_kg: 1.42,
      nodes: 3901,
      frequencies: [1336.4, 2210.5],
    },
    {
      simulation_id: '22222222-2222-2222-2222-222222222222',
      number: 2,
      params: { 두께: 12 },
      status: 'done',
      error_code: null,
      first_elastic_hz: 1650.5,
      mass_kg: 2.13,
      nodes: 4102,
      frequencies: [1650.5, 2604.1],
    },
    {
      simulation_id: '33333333-3333-3333-3333-333333333333',
      number: 3,
      params: { 두께: 20 },
      status: 'solving',
      error_code: null,
      first_elastic_hz: null,
      mass_kg: null,
      nodes: null,
      frequencies: [],
    },
  ],
}

function show() {
  return render(
    <MemoryRouter initialEntries={['/simulations/studies/3f9a21']}>
      <Routes>
        <Route path="/simulations/studies/:id" element={<StudyDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('설계점 비교', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.study).mockReset().mockResolvedValue(STUDY)
  })

  it('바꾼 값과 결과를 한 줄에 놓는다', async () => {
    show()
    await waitFor(() => expect(screen.getByText('브래킷_두께훑기')).toBeDefined())
    expect(screen.getByText('1,336.4')).toBeDefined()
    expect(screen.getByText('1.420')).toBeDefined()
  })

  it('아직 안 끝난 점도 표에 남는다', async () => {
    // **다 끝나야 보여 주면 그동안 아무것도 못 본다** — 한 건에 1~2분씩 걸린다.
    show()
    await waitFor(() => expect(screen.getByText('p0003')).toBeDefined())
    expect(screen.getByText('솔버')).toBeDefined()
  })

  it('결과가 없는 점은 그림에서 빠진다', async () => {
    // 0 으로 그리면 「두꺼울수록 0 에 가까워진다」 는 거짓말이 된다.
    show()
    await waitFor(() => expect(screen.getByRole('img', { name: /두께 대/ })).toBeDefined())
    expect(screen.getByRole('img', { name: /1차 모드/ })).toBeDefined()
  })
})
