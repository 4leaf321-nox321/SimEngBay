/**
 * **랜덤 진동 결과를 읽을 수 있게 보여 주는가**(CompCore 2026-11-17 「조건_랜덤진동」 의 값).
 *
 * ① 측정점 가속도 1σ · 최대 1σ 변위가 **3σ 와 함께** 뜬다 — 설계는 흔히 3σ 로 본다. ② 입력 Grms ·
 * 감쇠비 · 범위가 같이 뜬다. ③ 랜덤 결과가 모달 화면으로 새지 않는다 — 랜덤에도 `modes` 가 있다.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return { ...actual, simulationApi: { ...actual.simulationApi, mesh: vi.fn(), result: vi.fn() } }
})

import { simulationApi } from '@/modules/simulations/api'
import type { RandomResult as RandomResultData } from '@/modules/simulations/api'
import { RandomResult } from '@/modules/simulations/RandomResult'
import { ResultPanel } from '@/modules/simulations/ResultPanel'

const shaken: RandomResultData = {
  recipe: 'random',
  solver: 'calculix',
  units: { frequency: 'Hz', displacement: 'mm', acceleration: 'g', psd: 'g^2/Hz', system: 'ConsistentNMM' },
  mesh: { nodes: 6436, elements: 5451 },
  sigma: 1,
  damping_ratio: 0.02,
  frequency_range_hz: [20, 2000],
  range_from: 'psd',
  inputs: [
    {
      name: 'X 랜덤',
      direction: [1, 0, 0],
      grms: 6.05818,
      grms_in_range: 6.05818,
      declared_grms: 6.05818,
      table: [
        [20, 0.01],
        [80, 0.04],
        [350, 0.04],
        [2000, 0.007],
      ],
    },
  ],
  modes: [
    { number: 1, frequency_hz: 1263.423, participation: { 'X 랜덤': -0.00357753 }, mass_share: { 'X 랜덤': 0.0271 } },
    { number: 2, frequency_hz: 7417.362, participation: { 'X 랜덤': -0.00206838 }, mass_share: { 'X 랜덤': 0.0091 } },
  ],
  acceleration: 'absolute',
  displacement: 'relative',
  frequency_points: 4,
  curves: {
    frequency_hz: [20, 350, 1263, 2000],
    input_psd: { 'X 랜덤': [0.01, 0.04, 0.0111, 0.007] },
    probes: { 측정점: [0.01, 0.05, 16.9, 0.01] },
  },
  max_displacement: { value_mm: 0.00580426, node: 358, point: [-5, 0, 90] },
  probes: [
    {
      name: '측정점',
      point: [5, 5, 90],
      node: 20,
      distance_mm: 0,
      value: 36.7217,
      unit: 'g',
      vector: [36.5935, 0.155167, 3.06233],
      displacement_1sigma_mm: 0.0058042,
      psd_peak_hz: 1263.0063,
      psd_peak: 16.8981,
    },
  ],
  material: 'SECC · AL5052',
}

describe('랜덤 진동 결과', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.result).mockReset()
  })

  it('측정점 가속도 1σ · 최대 1σ 변위를 3σ 와 함께, 입력 · 감쇠비 · 범위를 같이 보여 준다', () => {
    render(<RandomResult simulationId="s1" result={shaken} artifacts={[]} />)
    expect(screen.getByText('36.72 g · 3σ 110.2 g')).toBeDefined()
    expect(screen.getByText('0.00580426 mm · 3σ 0.0174128 mm')).toBeDefined()
    expect(screen.getByText('X 랜덤 6.058 Grms')).toBeDefined()
    expect(screen.getByText('2.0% · 20~2000 Hz')).toBeDefined()
    expect(screen.getByText(/PSD 표의 범위/)).toBeDefined()
    // 축 성분 · 응답 봉우리 · 모드의 유효질량 몫.
    expect(screen.getByText('36.59 · 0.155167 · 3.062')).toBeDefined()
    // 응답 봉우리(1,263.0 Hz)와 1차 모드(1,263.4 Hz)가 같은 자리다.
    expect(screen.getAllByText('1263')).toHaveLength(2)
    expect(screen.getByText('2.7%')).toBeDefined()
    expect(screen.getByRole('img', { name: /로그-로그/ })).toBeDefined()
    expect(screen.getByText('이 작업은 1σ 그림을 만들지 않았습니다.')).toBeDefined()
  })

  it('경고를 맨 위에 보인다', () => {
    render(
      <RandomResult
        simulationId="s1"
        result={{ ...shaken, warning: '가장 높은 모드가 1,264 Hz 입니다 — 모드 수를 늘리세요.' }}
        artifacts={[]}
      />,
    )
    expect(screen.getByText(/모드 수를 늘리세요/)).toBeDefined()
  })

  it('결과 패널이 랜덤 결과를 모달 화면으로 보내지 않는다', async () => {
    vi.mocked(simulationApi.result).mockResolvedValue(shaken)
    render(<ResultPanel simulationId="s1" status="done" artifacts={[]} />)
    await waitFor(() => expect(screen.getByText('랜덤 진동 결과')).toBeDefined())
  })
})
