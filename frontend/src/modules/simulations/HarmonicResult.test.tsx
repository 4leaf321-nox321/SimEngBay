/**
 * **조화 곡선을 읽을 수 있게 보여 주는가.**
 *
 * 세 가지를 본다. ① 봉우리(주파수 · 변위)와 **감쇠비**가 같이 뜬다 — 봉우리 높이를 거의 감쇠가
 * 정하므로(1/2ζ) 그 값이 없으면 큰 수를 읽을 수 없다. ② 봉우리가 **창 끝**에 붙으면 공진을
 * 지나지 않았다고 말한다 — 29~31 kHz 를 훑고 「봉우리 31 kHz」 를 읽었다가 실제 공진이 60 kHz
 * 였던 일을 겪었다. ③ 조화 결과가 모달 화면으로 새지 않는다 — 모달은 `modes` 를 바로 훑어서
 * 그 칸이 없는 결과를 주면 화면이 통째로 깨진다.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { HarmonicResult as HarmonicResultData } from '@/modules/simulations/api'
import { simulationApi } from '@/modules/simulations/api'
import { HarmonicResult } from '@/modules/simulations/HarmonicResult'
import { ResultPanel } from '@/modules/simulations/ResultPanel'

vi.mock('@/modules/simulations/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/modules/simulations/api')>()
  return { ...actual, simulationApi: { ...actual.simulationApi, result: vi.fn() } }
})

/** 실측 곡선(56~64 kHz · 감쇠 2%)에서 네 점만 추렸다 — 봉우리가 60 kHz 안쪽에 있다. */
const measured: HarmonicResultData = {
  recipe: 'harmonic',
  units: { frequency: 'Hz', displacement: 'mm', system: 'ConsistentNMM' },
  mesh: { nodes: 1328, elements: 179 },
  damping_ratio: 0.02,
  points: [
    { frequency_hz: 56500, max_displacement: 3.1018e-3 },
    { frequency_hz: 59000, max_displacement: 6.8952e-3 },
    { frequency_hz: 60000, max_displacement: 9.6706e-3 },
    { frequency_hz: 64000, max_displacement: 2.928e-3 },
  ],
  peak: { frequency_hz: 60000, max_displacement: 9.6706e-3 },
  material: 'SS400',
}

describe('조화 응답 결과', () => {
  beforeEach(() => {
    vi.mocked(simulationApi.result).mockReset()
  })

  it('봉우리와 감쇠비를 같이 보여 준다', () => {
    render(<HarmonicResult result={measured} />)
    expect(screen.getByText('60000 Hz')).toBeDefined()
    expect(screen.getByText('0.0096706 mm')).toBeDefined()
    // 감쇠비가 없으면 큰 수가 물리인지 가정인지 알 수 없다.
    expect(screen.getByText('2.0%')).toBeDefined()
    // 창의 가장 작은 점 대비 몇 배인가 — 공진이 솟았다는 것을 한눈에 본다.
    expect(screen.getByText('3.3배')).toBeDefined()
  })

  it('봉우리가 창 끝에 있으면 범위를 넓히라고 말한다', () => {
    const flank: HarmonicResultData = {
      ...measured,
      points: [
        { frequency_hz: 29200, max_displacement: 5.1318e-4 },
        { frequency_hz: 31000, max_displacement: 5.3395e-4 },
      ],
      peak: { frequency_hz: 31000, max_displacement: 5.3395e-4 },
    }
    render(<HarmonicResult result={flank} />)
    expect(screen.getByText(/범위를 넓혀/)).toBeDefined()
  })

  it('결과 패널이 조화를 모달 화면으로 보내지 않는다', async () => {
    vi.mocked(simulationApi.result).mockResolvedValue(measured)
    render(<ResultPanel simulationId="sim" status="done" artifacts={[]} />)
    await waitFor(() => expect(screen.getByText('조화 응답 결과')).toBeDefined())
  })
  it('측정점의 곡선 봉우리를 절점 거리와 함께 보여 준다', () => {
    // **센서 자리의 봉우리는 전체 봉우리와 다를 수 있다** — 실측 FRF 와 견줄 값은 이쪽이다.
    const withProbes: HarmonicResultData = {
      ...measured,
      points: measured.points.map((one, index) => ({
        ...one,
        probes: { '측정점 A': [1e-3, 4e-3, 2e-3, 1e-3][index] },
      })),
      probes: [
        {
          name: '측정점 A',
          point: [5, 5, 90],
          node: 3,
          distance_mm: 0,
          value: 4e-3,
          unit: 'mm',
          frequency_hz: 59000,
        },
      ],
    }
    render(<HarmonicResult result={withProbes} />)
    expect(screen.getByText('측정점 봉우리')).toBeDefined()
    expect(screen.getByText(/59000 Hz/)).toBeDefined()
    expect(screen.getByText(/절점 거리 0 mm/)).toBeDefined()
  })
})
