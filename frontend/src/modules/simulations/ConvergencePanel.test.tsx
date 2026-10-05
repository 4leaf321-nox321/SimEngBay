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
import { ConvergencePanel, SUGGESTED_RATIOS } from '@/modules/simulations/ConvergencePanel'

const LEVEL = { status: 'done', solver: 'calculix', local_scale: 1, ratio: null }

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

  it('원래 대비 비율(×0.7 · ×0.5)을 제안하고 비율로 보낸다', async () => {
    // **mm 를 맞춰 치게 하지 않는다** — 전체와 파트 · 면이 모두 원래 대비 같은 비율로 줄어든다.
    expect(SUGGESTED_RATIOS).toEqual(['0.7', '0.5'])
    show()
    await waitFor(() => expect(screen.getByText('수렴')).toBeDefined())
    await userEvent.click(screen.getByRole('button', { name: /메시 수렴 점검/ }))
    expect((screen.getByLabelText('정련 비율 1 (원래 대비)') as HTMLInputElement).value).toBe('0.7')
    // 원래 5 mm → ×0.7 · ×0.5 = 3.5 · 2.5 mm.
    const whole = screen.getByRole('row', { name: /^전체/ })
    expect(whole.textContent).toContain('3.5')
    expect(whole.textContent).toContain('2.5')
    await userEvent.click(screen.getByRole('button', { name: /2건 실행/ }))
    await waitFor(() => expect(simulationApi.requestConvergence).toHaveBeenCalled())
    expect(vi.mocked(simulationApi.requestConvergence).mock.calls[0][1]).toEqual({
      ratios: [0.7, 0.5],
      solver: 'calculix',
    })
  })

  it('전체와 파트 · 면별 요소 크기를 창과 결과 표에 보인다', async () => {
    vi.mocked(simulationApi.convergence).mockResolvedValue({
      ...CHECKED,
      base_size_mm: 4,
      levels: [
        { ...LEVEL, simulation_id: 'a', element_size_mm: 4, nodes: 9000, is_original: true, ratio: 1 },
        { ...LEVEL, simulation_id: 'b', element_size_mm: 2, nodes: 60000, is_original: false, ratio: 0.5, local_scale: 0.5 },
      ],
      local_sizes: [
        { name: '기둥', kind: 'part', size_mm: 1.5 },
        { name: '기둥 끝', kind: 'face', size_mm: 0.8 },
      ],
    })
    show()
    // 결과 표 — 비율 · 전체 · 파트 · 면 열.
    await waitFor(() => expect(screen.getByRole('columnheader', { name: /기둥 파트/ })).toBeDefined())
    expect(screen.getByRole('columnheader', { name: /기둥 끝 면/ })).toBeDefined()
    const level = screen.getByRole('row', { name: /^×0\.5/ })
    expect(level.textContent).toContain('0.75')
    expect(level.textContent).toContain('0.4')

    await userEvent.click(screen.getByRole('button', { name: /메시 수렴 점검/ }))
    const row = (name: string) => screen.getByRole('row', { name: new RegExp(`^${name}`) })
    // ×0.7 · ×0.5 → 전체 2.8 · 2, 기둥 1.05 · 0.75, 기둥 끝 0.56 · 0.4.
    expect(row('전체').textContent).toContain('2.8')
    expect(row('기둥 파트').textContent).toContain('1.05')
    expect(row('기둥 끝 면').textContent).toContain('0.56')
    // 비율을 고치면 따라 바뀐다.
    await userEvent.clear(screen.getByLabelText('정련 비율 2 (원래 대비)'))
    await userEvent.type(screen.getByLabelText('정련 비율 2 (원래 대비)'), '0.25')
    expect(row('기둥 파트').textContent).toContain('0.375')
    expect(row('전체').textContent).toContain('1')
  })

  it('원래 전체 크기를 모르면 비율을 곱할 기준이 없다고 말하고 실행하지 않는다', async () => {
    vi.mocked(simulationApi.convergence).mockResolvedValue({ ...CHECKED, base_size_mm: null })
    show()
    await waitFor(() => expect(screen.getByText('수렴')).toBeDefined())
    await userEvent.click(screen.getByRole('button', { name: /메시 수렴 점검/ }))
    expect(screen.getByText(/비율을 곱할 기준이 없습니다/)).toBeDefined()
    expect(screen.getByRole('button', { name: /건 실행/ })).toBeDisabled()
  })
})
