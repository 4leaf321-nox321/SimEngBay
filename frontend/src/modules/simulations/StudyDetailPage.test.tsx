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
import type { Study } from '@/modules/simulations/api'
import StudyDetailPage from '@/modules/simulations/StudyDetailPage'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return { ...actual, simulationApi: { ...actual.simulationApi, study: vi.fn() } }
})

const STUDY: Study = {
  study_id: '3f9a21',
  name: '브래킷_두께훑기',
  factors: ['두께'],
  reference_point: 1,
  // 두께가 커지며 2차와 3차가 자리를 바꾼 경우 — **순번으로 이으면 다른 모드를 잇는다.**
  tracks: [
    // 1차는 p0002 에서 닮은 모드를 못 찾았다 — **억지로 잇지 않는다.**
    { reference: 1, numbers: { 1: 1 }, confidence: { 2: 0.41 } },
    { reference: 2, numbers: { 1: 2, 2: 1 }, confidence: { 2: 0.96 } },
  ],
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

describe('모드 추적', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.study).mockReset().mockResolvedValue(STUDY)
  })

  it('형상으로 이어 견준다고 말한다', async () => {
    show()
    await waitFor(() => expect(screen.getByText(/모드 형상으로 이어 견줍니다/)).toBeDefined())
  })

  it('못 이은 설계점이 있으면 몇 개인지 말한다', async () => {
    // **억지로 잇지 않는다** — 대신 빠졌다는 사실이 보여야 그래프를 믿을지 정할 수 있다.
    show()
    await waitFor(() =>
      expect(screen.getByText(/1개 설계점에서는 같은 모드를 찾지 못해/)).toBeDefined(),
    )
  })

  it('지문이 없으면 순번으로 견준다고 밝힌다', async () => {
    vi.mocked(simulationApi.study).mockResolvedValue({
      ...STUDY,
      reference_point: null,
      tracks: [],
    })
    show()
    await waitFor(() => expect(screen.getByText(/순번으로/)).toBeDefined())
  })
})
