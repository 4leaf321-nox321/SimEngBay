/**
 * 스터디 상세 — **200점짜리 DOE 에서 점마다 누르게 하지 않는다.** 실패한 점을 한 번에 다시
 * 실행하고, 중간 파일을 스터디째 정리한다(서버의 `studies/{id}/tidy`).
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { simulationApi } from '@/modules/simulations/api'
import type { Study, StudyPoint } from '@/modules/simulations/api'
import StudyDetailPage from '@/modules/simulations/StudyDetailPage'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    simulationApi: {
      ...actual.simulationApi,
      study: vi.fn(),
      retry: vi.fn(),
      tidyStudy: vi.fn(),
      studyMeasurements: vi.fn(),
    },
  }
})

function point(number: number, status: string): StudyPoint {
  return {
    simulation_id: `s${number}`,
    number,
    params: { 두께: number * 2 },
    status,
    recipe: 'modal',
    solver: 'calculix',
    frequencies: [],
  }
}

const STUDY: Study = {
  study_id: 'st',
  name: '브래킷',
  factors: ['두께'],
  recipe: 'modal',
  solvers: ['calculix'],
  tracks: [],
  points: [point(1, 'failed'), point(2, 'canceled'), point(3, 'failed')],
}

function show() {
  return render(
    <MemoryRouter initialEntries={['/simulations/studies/st']}>
      <Routes>
        <Route path="/simulations/studies/:id" element={<StudyDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('스터디 상세', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.study).mockReset().mockResolvedValue(STUDY)
    vi.mocked(simulationApi.retry).mockReset().mockResolvedValue({} as never)
    vi.mocked(simulationApi.tidyStudy).mockReset().mockResolvedValue({ bytes_freed: 3 * 1024 * 1024, files: 12, points: 3 })
    vi.mocked(simulationApi.studyMeasurements).mockReset().mockResolvedValue([])
  })

  it('실패 · 취소된 점을 한 번에 다시 실행한다', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: /실패한 점 다시 실행 \(3\)/ }))
    await waitFor(() => expect(simulationApi.retry).toHaveBeenCalledTimes(3))
    expect(screen.getByText(/3개를 다시 실행했습니다/)).toBeDefined()
  })

  it('다시 실행하지 못한 점은 그 까닭을 모아 보여 준다', async () => {
    vi.mocked(simulationApi.retry).mockRejectedValueOnce(new Error('권한이 없습니다'))
    show()
    await userEvent.click(await screen.findByRole('button', { name: /실패한 점 다시 실행/ }))
    await waitFor(() => expect(screen.getByText(/p0001: 권한이 없습니다/)).toBeDefined())
  })

  it('중간 파일을 스터디째 정리하기 전에 무엇이 사라지는지 말한다', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: /중간 파일 정리/ }))
    expect(screen.getByText(/결과 요약 · 그림 · 입력은 남습니다/)).toBeDefined()
    await userEvent.click(screen.getByRole('button', { name: '정리' }))
    await waitFor(() => expect(simulationApi.tidyStudy).toHaveBeenCalledWith('st'))
    await waitFor(() => expect(screen.getByText(/중간 파일 12개 · 3.0MB/)).toBeDefined())
  })
})
