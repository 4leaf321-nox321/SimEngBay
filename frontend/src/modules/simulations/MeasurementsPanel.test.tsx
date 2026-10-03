/**
 * 실측과 맞추기 — **같은 자리에서 견준 것과 그 설명을 보여 주는가, 틀린 표는 줄마다 말하는가.**
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
      measurements: vi.fn(),
      addMeasurement: vi.fn(),
      removeMeasurement: vi.fn(),
      studyMeasurements: vi.fn(),
      addStudyMeasurement: vi.fn(),
    },
  }
})

import { simulationApi } from '@/modules/simulations/api'
import type { Measurement, StudyMeasurement } from '@/modules/simulations/api'
import { MeasurementsPanel } from '@/modules/simulations/MeasurementsPanel'
import { StudyMeasurements } from '@/modules/simulations/StudyMeasurements'
import { ApiError } from '@/shared/api/client'

const MEASURED: Measurement = {
  id: 'm1',
  label: '시편 1',
  original_name: '실측.csv',
  simulation_id: 'sim',
  study_id: null,
  kinds: ['frequency', 'frf', 'displacement'],
  probes: ['측정점'],
  rows: 6,
  created_at: '2026-10-03T09:00:00Z',
  created_by_name: '홍길동',
  comparison: {
    recipe: 'modal',
    frequency: {
      matches: [
        {
          probe: '측정점',
          measured_hz: 1250,
          mode: 7,
          elastic_number: 1,
          analysis_hz: 1266.4,
          diff_pct: 1.31,
          visibility: 1,
          ambiguous: false,
        },
        {
          probe: null,
          measured_hz: 3450,
          mode: 9,
          elastic_number: 3,
          analysis_hz: 3500,
          diff_pct: 1.45,
          visibility: null,
          ambiguous: true,
        },
      ],
      mean_abs_pct: 1.38,
      max_abs_pct: 1.45,
      explanation: '모든 짝이 같은 비율로 어긋났습니다 — 영률을 200 → 194.8 GPa 로 두면 맞습니다.',
      suggested_modulus_gpa: 194.8,
    },
    frf: [
      {
        probe: '측정점',
        quantity: 'acceleration',
        unit: 'mm/s²',
        measured: [
          [1200, 1],
          [1250, 9],
          [1300, 1],
        ],
        analysis: [
          [1200, 1],
          [1266, 12],
          [1300, 1],
        ],
        measured_peak_hz: 1250,
        analysis_peak_hz: 1266,
        peak_diff_pct: 1.28,
        amplitude_ratio: 1.33,
        measured_damping: 0.026,
        analysis_damping: 0.02,
        suggested_damping: 0.0266,
        note: '봉우리 높이가 1.33 배입니다 — 감쇠비를 2.00% → 2.66% 로 두면 맞습니다.',
      },
    ],
    static: null,
    skipped: ['변위 · 변형률은 정적 결과와 견줍니다 — 이 작업은 정적이 아닙니다.'],
    score_pct: 1.35,
  },
}

describe('실측과 맞추기', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.measurements).mockReset().mockResolvedValue([MEASURED])
    vi.mocked(simulationApi.addMeasurement).mockReset().mockResolvedValue(MEASURED)
  })

  it('공진의 짝과 영률 설명을 보여 주고 불확실한 짝을 짚는다', async () => {
    render(<MeasurementsPanel simulationId="sim" status="done" />)
    await waitFor(() => expect(screen.getByText('시편 1')).toBeDefined())
    expect(screen.getByText('1차')).toBeDefined()
    expect(screen.getByText(/짝 불확실/)).toBeDefined()
    expect(screen.getByText(/194\.8 GPa 로 두면 맞습니다/)).toBeDefined()
  })

  it('FRF 의 봉우리 · 감쇠를 견주고 감쇠비를 제안한다', async () => {
    render(<MeasurementsPanel simulationId="sim" status="done" />)
    await waitFor(() => expect(screen.getByText(/FRF — 측정점/)).toBeDefined())
    expect(screen.getByText('1.33배')).toBeDefined()
    expect(screen.getByText('2.60% · 2.00%')).toBeDefined()
    expect(screen.getByRole('img', { name: /측정점 실측 대 해석 FRF/ })).toBeDefined()
  })

  it('레시피가 달라 못 견준 종류는 그 까닭을 적는다', async () => {
    render(<MeasurementsPanel simulationId="sim" status="done" />)
    await waitFor(() => expect(screen.getByText(/이 작업은 정적이 아닙니다/)).toBeDefined())
  })

  it('표를 업로드하면 다시 읽는다', async () => {
    render(<MeasurementsPanel simulationId="sim" status="done" />)
    await waitFor(() => expect(screen.getByText('시편 1')).toBeDefined())
    const file = new File(['종류,주파수\n공진,1250\n'], '실측.csv', { type: 'text/csv' })
    await userEvent.upload(screen.getByLabelText('실측 표 (CSV · 탭 · JSON)'), file)
    await userEvent.type(screen.getByLabelText('이름'), '시편 2')
    await userEvent.click(screen.getByRole('button', { name: /업로드/ }))
    await waitFor(() => expect(simulationApi.addMeasurement).toHaveBeenCalled())
    expect(vi.mocked(simulationApi.addMeasurement).mock.calls[0][2]).toBe('시편 2')
    await waitFor(() => expect(simulationApi.measurements).toHaveBeenCalledTimes(2))
  })

  it('틀린 표는 고칠 줄을 전부 보여 준다', async () => {
    vi.mocked(simulationApi.addMeasurement).mockRejectedValue(
      new ApiError(400, {
        error: {
          code: 'SEB-SIMULATIONS-0025',
          message: '실측 표에 고칠 곳이 2개 있습니다: 2줄: 모르는 종류',
          request_id: 'r',
          details: { errors: ['2줄: 모르는 종류 「가속」', '3줄: 변위에는 측정점 · 값이 있어야 합니다.'] },
        },
      }),
    )
    render(<MeasurementsPanel simulationId="sim" status="done" />)
    await waitFor(() => expect(screen.getByText('시편 1')).toBeDefined())
    await userEvent.upload(
      screen.getByLabelText('실측 표 (CSV · 탭 · JSON)'),
      new File(['x'], 'bad.csv', { type: 'text/csv' }),
    )
    await userEvent.click(screen.getByRole('button', { name: /업로드/ }))
    await waitFor(() => expect(screen.getByText(/3줄: 변위에는/)).toBeDefined())
  })

  it('끝나지 않은 작업에는 나타나지 않는다', () => {
    render(<MeasurementsPanel simulationId="sim" status="solving" />)
    expect(screen.queryByText('실측과 맞추기')).toBeNull()
  })
})

const STUDY_MEASURED: StudyMeasurement = {
  ...MEASURED,
  simulation_id: null,
  study_id: 'st',
  comparison: null,
  points: [
    { simulation_id: 'a', number: 1, params: { 영률: 190 }, status: 'done', score_pct: 1.9 },
    { simulation_id: 'b', number: 2, params: { 영률: 195 }, status: 'done', score_pct: 0.2 },
    { simulation_id: 'c', number: 3, params: { 영률: 200 }, status: 'done', score_pct: 1.3 },
  ],
  best_point: 2,
  explanation: '실측에 가장 가까운 설계점은 p0002(영률 195) — 평균 차이 0.20% 입니다.',
}

describe('스터디의 실측', () => {
  it('설계점마다 점수를 매기고 가장 가까운 점을 짚는다', async () => {
    vi.mocked(simulationApi.studyMeasurements).mockReset().mockResolvedValue([STUDY_MEASURED])
    render(
      <MemoryRouter>
        <StudyMeasurements studyId="st" factors={['영률']} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText(/p0002\(영률 195\)/)).toBeDefined())
    expect(screen.getByText('가장 가까움')).toBeDefined()
    expect(screen.getByText('0.20%')).toBeDefined()
  })
})
