/**
 * 해석 작업 화면 — **한눈에 보기 줄 + 탭 넷.** 어느 탭을 여나는 상태가 정하고, 주소의 `?tab=` 이
 * 있으면 그것을 따른다(못 여는 탭이면 무시).
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ id: 'me' }))

// 화면이 「건 사람인가」 를 본다(`ownsWork`) — 기본은 건 사람, 남으로 바꿔 읽기 전용을 본다.
vi.mock('@/shared/auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: auth.id, is_system_admin: false, memberships: [] } }),
}))

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
      publish: vi.fn(),
      unpublish: vi.fn(),
      downloadAll: vi.fn(),
      remove: vi.fn(),
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
    requested_by_id: 'me',
    requested_by_name: '나',
    published_at: null,
    attempts: 1,
    artifacts: [],
    conditions: {
      lines: [{ kind: 'constraint', label: '바닥 고정', detail: '', status: 'applied', why: '' }],
      unit_system: 'mm_n_tonne',
      prestressed: false,
      drives: false,
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
        <Route path="/simulations/studies/:id" element={<p>DOE 화면</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('해석 작업 화면', () => {
  beforeEach(() => {
    auth.id = 'me'
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

  it('내 끝난 작업은 확인을 받고 게시한다 — 게시되면 표시와 단추가 바뀐다', async () => {
    const published = {
      ...job('done'),
      published_at: '2026-10-20T01:00:00Z',
      published_by_name: '나',
    } as Simulation
    vi.mocked(simulationApi.publish).mockReset().mockResolvedValue(published)
    show()
    await userEvent.click(await screen.findByRole('button', { name: '게시' }))
    // **누구나 본다** — 누르기 전에 무엇이 바뀌는지 말한다.
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('조직의 누구나')
    await userEvent.click(within(dialog).getByRole('button', { name: '게시' }))
    await waitFor(() => expect(simulationApi.publish).toHaveBeenCalledWith('sim'))
    expect(await screen.findByRole('button', { name: '게시 해제' })).toBeDefined()
    expect(screen.getAllByText('게시됨').length).toBeGreaterThan(0)
  })

  it('남의 게시 결과는 읽기만 한다 — 바꾸는 단추가 없다', async () => {
    auth.id = 'someone-else'
    vi.mocked(simulationApi.get).mockResolvedValue({
      ...job('done'),
      published_at: '2026-10-20T01:00:00Z',
      published_by_name: '나',
    } as Simulation)
    show()
    await screen.findByRole('region', { name: '한눈에 보기' })
    expect(screen.getByText(/다른 사람의 결과라 읽기만 합니다/)).toBeDefined()
    for (const name of ['게시', '게시 해제', '중간 파일 정리', '다시 실행', '취소', '삭제']) {
      expect(screen.queryByRole('button', { name })).toBeNull()
    }
  })

  it('지우기 전에 무엇이 사라지는지 말하고, DOE 설계점이면 지운 뒤 그 DOE 로 간다', async () => {
    vi.mocked(simulationApi.get).mockResolvedValue({
      ...job('failed'),
      source_kind: 'doe_point',
      source_meta: { study_id: 'st', study_name: '브래킷', point: 1 },
      published_at: '2026-10-20T01:00:00Z',
    } as Simulation)
    vi.mocked(simulationApi.remove).mockReset().mockResolvedValue({ jobs: 2, bytes_freed: 10 })
    show()
    await userEvent.click(await screen.findByRole('button', { name: '삭제' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog.textContent).toContain('되돌릴 수 없습니다')
    expect(dialog.textContent).toContain('다른 사람의 화면에서도 사라집니다')
    expect(dialog.textContent).toContain('앞선 시도')
    await userEvent.click(within(dialog).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(simulationApi.remove).toHaveBeenCalledWith('sim'))
    expect(await screen.findByText('DOE 화면')).toBeDefined()
  })

  it('모드 수만 바꿔 다시 건 작업은 「다시 가져옴」 이 아니라 그렇게 말한다 — 옛 작업도 새 작업도', async () => {
    const point = { study_id: 'st', study_name: '브래킷', point: 1 }
    vi.mocked(simulationApi.get).mockResolvedValue({
      ...job('done'),
      source_kind: 'doe_point',
      source_meta: { ...point, previous: ['old'], rerun: { modes: 10, from_modes: 6 } },
    } as Simulation)
    const { unmount } = show()
    expect(await screen.findByText(/모드 6 → 10개로 다시 걸음/)).toBeDefined()
    unmount()

    vi.mocked(simulationApi.get).mockResolvedValue({
      ...job('done'),
      source_kind: 'doe_point',
      source_meta: { ...point, superseded_by: 'new', rerun_to: 10 },
    } as Simulation)
    show()
    expect(await screen.findByText(/모드 10개로 다시 걸음/)).toBeDefined()
    expect(screen.getByRole('link', { name: '새 작업 보기' }).getAttribute('href')).toBe('/simulations/new')
  })

  it('도는 작업은 지우지 않는다 — 먼저 멈춘다', async () => {
    vi.mocked(simulationApi.get).mockResolvedValue(job('solving'))
    vi.mocked(simulationApi.status).mockResolvedValue(job('solving'))
    show()
    expect(await screen.findByRole('button', { name: '취소' })).toBeDefined()
    expect(screen.queryByRole('button', { name: '삭제' })).toBeNull()
  })

  it('파일 탭에서 산출물 전부를 한 번에 받는다', async () => {
    vi.mocked(simulationApi.downloadAll).mockReset().mockResolvedValue(undefined)
    vi.mocked(simulationApi.get).mockResolvedValue({
      ...job('done'),
      artifacts: [
        { id: 'a1', kind: 'result_json', filename: 'result.json', stage: 'extracting', size_bytes: 2048 },
        { id: 'a2', kind: 'rst', filename: 'file.rst', stage: 'solving', size_bytes: 3 * 1024 * 1024 },
      ],
    } as Simulation)
    show('/simulations/sim?tab=files')
    await userEvent.click(await screen.findByRole('button', { name: /전체 다운로드/ }))
    expect(simulationApi.downloadAll).toHaveBeenCalledWith('sim', '측면가진_파일.zip')
  })
})
