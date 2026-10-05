/**
 * 해석 작업 화면 — **한눈에 보기 줄 + 탭 넷.** 어느 탭을 여나는 상태가 정하고, 주소의 `?tab=` 이
 * 있으면 그것을 따른다(못 여는 탭이면 무시).
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    simulationApi: {
      ...actual.simulationApi,
      get: vi.fn(),
      status: vi.fn(),
      result: vi.fn(),
      convergence: vi.fn(),
      measurements: vi.fn(),
      solvers: vi.fn().mockResolvedValue([]),
    },
  }
})

import { simulationApi } from '@/modules/simulations/api'
import type { Simulation } from '@/modules/simulations/api'
import SimulationDetailPage from '@/modules/simulations/SimulationDetailPage'

const STAGES = ['fetching', 'modeling', 'solving', 'extracting']

function job(status: string): Simulation {
  return {
    id: 'sim',
    name: '측면가진',
    recipe: 'modal',
    status,
    spec: { recipe: 'modal', solver: 'ansys' },
    summary: { nodes: 29890, mass_kg: 0.502 },
    source_kind: 'upload',
    source_ref: '',
    source_meta: {},
    attempts: 1,
    artifacts: [],
    conditions: {
      lines: [{ kind: 'constraint', label: '바닥 고정', detail: '', status: 'applied', why: '' }],
      unit_system: 'mm_n_tonne',
      prestressed: false,
    },
    stages: STAGES.map((name, index) => ({
      name,
      status: status === 'done' || index < 1 ? 'done' : index === 1 ? 'running' : 'pending',
      detail: '',
      started_at: null,
      finished_at: null,
      error_message: null,
    })),
    created_at: '2026-10-05T03:00:00Z',
    started_at: null,
    finished_at: null,
  } as unknown as Simulation
}

const RESULT = {
  recipe: 'modal',
  boundary: 'constrained',
  units: { frequency: 'Hz' },
  normalization: 'mass',
  rigid_body_modes: 0,
  modes: [{ number: 1, elastic_number: 1, frequency_hz: 1263.5, rigid_body: false }],
}

function show(path = '/simulations/sim') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/simulations/:id" element={<SimulationDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('해석 작업 화면', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.get).mockReset().mockResolvedValue(job('done'))
    vi.mocked(simulationApi.status).mockReset().mockResolvedValue(job('done'))
    vi.mocked(simulationApi.result).mockReset().mockResolvedValue(RESULT as never)
    vi.mocked(simulationApi.convergence)
      .mockReset()
      .mockResolvedValue({ levels: [], metrics: [], notes: [] } as never)
    vi.mocked(simulationApi.measurements).mockReset().mockResolvedValue([])
  })

  it('끝난 작업은 결과 탭을 열고, 위에 대표 숫자와 믿음 배지를 둔다', async () => {
    show()
    const glance = await screen.findByRole('region', { name: '한눈에 보기' })
    await waitFor(() => expect(glance.textContent).toContain('1,263.5 Hz'))
    expect(glance.textContent).toContain('점검 안 함')
    expect(glance.textContent).toContain('반영 1 · 넘김 0')
    expect(screen.getByRole('tab', { name: '결과' }).getAttribute('aria-selected')).toBe('true')
    expect(simulationApi.result).toHaveBeenCalledTimes(1)
  })

  it('도는 작업은 진행 · 모델 탭을 열고 결과 · 검증 탭을 막는다', async () => {
    vi.mocked(simulationApi.get).mockResolvedValue(job('modeling'))
    show()
    await screen.findByRole('tab', { name: '진행 · 모델' })
    expect(screen.getByRole('tab', { name: '진행 · 모델' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tab', { name: '결과' })).toBeDisabled()
    expect(screen.getByRole('tab', { name: '검증' })).toBeDisabled()
    expect(simulationApi.result).not.toHaveBeenCalled()
  })

  it('주소의 탭을 연다 — 못 여는 탭이면 상태가 정한 탭', async () => {
    show('/simulations/sim?tab=checks')
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: '검증' }).getAttribute('aria-selected')).toBe('true'),
    )
    expect(screen.getByRole('heading', { name: '메시 수렴' })).toBeDefined()
  })

  it('배지를 누르면 그 탭으로 간다', async () => {
    show()
    const glance = await screen.findByRole('region', { name: '한눈에 보기' })
    await userEvent.click(within(glance).getByRole('button', { name: /CAD 조건/ }))
    expect(screen.getByRole('tab', { name: '진행 · 모델' }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getByText('바닥 고정')).toBeDefined()
  })

  it('검증 탭이 새로 읽은 수렴 상태를 배지가 따른다', async () => {
    // 배지는 처음 한 번 읽는다 — 그 뒤 점검을 걸면 검증 탭이 읽은 것을 따라야 옛 판정이 안 남는다.
    const level = { status: 'done', solver: 'ansys', local_scale: 1, ratio: 1, nodes: 9000 }
    vi.mocked(simulationApi.convergence)
      .mockResolvedValueOnce({ levels: [], metrics: [], notes: [] } as never)
      .mockResolvedValue({
        original_id: 'sim',
        recipe: 'modal',
        base_size_mm: 4,
        levels: [
          { ...level, simulation_id: 'sim', element_size_mm: 4, is_original: true },
          { ...level, simulation_id: 'b', element_size_mm: 2.8, is_original: false, ratio: 0.7, status: 'solving' },
        ],
        metrics: [],
        notes: [],
        local_sizes: [],
      } as never)
    show()
    const glance = await screen.findByRole('region', { name: '한눈에 보기' })
    await waitFor(() => expect(glance.textContent).toContain('점검 안 함'))
    await userEvent.click(screen.getByRole('tab', { name: '검증' }))
    await waitFor(() => expect(glance.textContent).toContain('도는 중'))
  })

  it('다른 작업으로 넘어가면 앞 작업을 남기지 않는다 — 못 받으면 그 오류를 보인다', async () => {
    // 같은 주소 꼴이라 화면이 그대로 남는다 — 새 작업을 못 받으면 앞 작업이 오류 없이 보였다.
    vi.mocked(simulationApi.get).mockImplementation((id: string) =>
      id === 'sim' ? Promise.resolve(job('done')) : Promise.reject(new Error('작업을 찾을 수 없습니다')),
    )
    function Go() {
      const navigate = useNavigate()
      return (
        <button type="button" onClick={() => navigate('/simulations/other')}>
          다른 작업
        </button>
      )
    }
    render(
      <MemoryRouter initialEntries={['/simulations/sim']}>
        <Go />
        <Routes>
          <Route path="/simulations/:id" element={<SimulationDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )
    await screen.findByRole('region', { name: '한눈에 보기' })
    expect(screen.getAllByText('측면가진').length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: '다른 작업' }))
    await waitFor(() => expect(screen.getByText(/작업을 찾을 수 없습니다/)).toBeDefined())
    expect(screen.queryByText('측면가진')).toBeNull()
  })
})
