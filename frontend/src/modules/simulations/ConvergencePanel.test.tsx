/**
 * 메시 수렴 — **판정과 그 근거를 같이 보여 주는가, 첨두응력의 발산을 고장으로 읽히지 않게 하는가.**
 */

import { cloneElement } from 'react'
import type { ReactElement } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 400, height: 300 } as Record<string, unknown>),
  }
})

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return {
    ...actual,
    simulationApi: {
      ...actual.simulationApi,
      convergence: vi.fn(),
      requestConvergence: vi.fn(),
      solvers: vi.fn().mockResolvedValue([]),
    },
  }
})

import { simulationApi } from '@/modules/simulations/api'
import type { Convergence } from '@/modules/simulations/api'
import { ConvergencePanel, suggestedSizes } from '@/modules/simulations/ConvergencePanel'

const LEVEL = { status: 'done', solver: 'calculix' }

const CHECKED: Convergence = {
  original_id: 'a',
  recipe: 'static',
  base_size_mm: 5,
  levels: [
    { ...LEVEL, simulation_id: 'a', element_size_mm: 5, nodes: 12345, is_original: true },
    { ...LEVEL, simulation_id: 'b', element_size_mm: 3.5, nodes: 35991, is_original: false },
    { ...LEVEL, simulation_id: 'c', element_size_mm: 2.5, nodes: 98760, is_original: false },
  ],
  metrics: [
    {
      key: 'max_mm',
      label: '최대 변형',
      unit: 'mm',
      values: [0.0392, 0.0396, 0.0398],
      status: 'converged',
      tolerance_pct: 2,
      change_pct: 0.5,
      order: 2.01,
      gci_pct: 0.31,
      extrapolated: 0.0399,
      note: '',
    },
    {
      key: 'max_mpa',
      label: '최대 상당응력',
      unit: 'MPa',
      values: [126, 128.6, 132],
      status: 'diverging',
      tolerance_pct: 2,
      change_pct: 2.6,
      order: null,
      gci_pct: null,
      extrapolated: null,
      note: '첨두응력은 구속 모서리 · 날카로운 모서리의 특이점에 있으면 메시를 줄일수록 커집니다 — 이 값으로 판단하지 말고 측정점 · 변형을 봅니다.',
    },
  ],
  notes: [],
}

function show(status = 'done') {
  return render(
    <MemoryRouter>
      <ConvergencePanel simulationId="a" status={status} solver="calculix" />
    </MemoryRouter>,
  )
}

describe('메시 수렴', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.convergence).mockReset().mockResolvedValue(CHECKED)
    vi.mocked(simulationApi.requestConvergence).mockReset().mockResolvedValue(CHECKED)
  })

  it('값마다 판정과 근거(변화 · 차수 · GCI)를 보여 준다', async () => {
    show()
    await waitFor(() => expect(screen.getByText('수렴')).toBeDefined())
    expect(screen.getByText('발산')).toBeDefined()
    expect(screen.getByText(/0\.5% · 2\.01 · 0\.31%/)).toBeDefined()
    expect(screen.getByText('원래 작업')).toBeDefined()
  })

  it('첨두응력의 발산을 고장으로 읽히지 않게 까닭을 적는다', async () => {
    show()
    await waitFor(() => expect(screen.getByText(/측정점 · 변형을 봅니다/)).toBeDefined())
  })

  it('점검하지 않은 작업은 무엇을 하는 것인지 말한다', async () => {
    vi.mocked(simulationApi.convergence).mockResolvedValue({ ...CHECKED, levels: CHECKED.levels.slice(0, 1), metrics: [] })
    show()
    await waitFor(() => expect(screen.getByText(/아직 점검하지 않았습니다/)).toBeDefined())
  })

  it('끝나지 않은 작업에는 나타나지 않는다', () => {
    show('solving')
    expect(screen.queryByText('메시 수렴')).toBeNull()
    expect(simulationApi.convergence).not.toHaveBeenCalled()
  })

  it('기준 크기에서 고르게 줄인 두 크기를 제안하고 그대로 보낸다', async () => {
    expect(suggestedSizes(5)).toEqual(['3.5', '2.5'])
    expect(suggestedSizes(null)).toEqual(['', ''])
    show()
    await waitFor(() => expect(screen.getByText('수렴')).toBeDefined())
    await userEvent.click(screen.getByRole('button', { name: /메시 수렴 점검/ }))
    expect((screen.getByLabelText('요소 크기 1 (mm)') as HTMLInputElement).value).toBe('3.5')
    await userEvent.click(screen.getByRole('button', { name: /2건 실행/ }))
    await waitFor(() => expect(simulationApi.requestConvergence).toHaveBeenCalled())
    expect(vi.mocked(simulationApi.requestConvergence).mock.calls[0][1]).toEqual({
      sizes_mm: [3.5, 2.5],
      solver: 'calculix',
    })
  })
})
