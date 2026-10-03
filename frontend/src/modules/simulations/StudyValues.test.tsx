/**
 * 정적 · 조화 DOE — **모드 대신 값을 견주는가.**
 *
 * 값은 CompCore 전단 이음 DOE(마찰계수 0.15 · 0.3 · 0.6)의 실측 모양을 따랐다: μ 가 오르면 당기는
 * 끝의 반력이 μN 을 따라 오르고(1,500 → 3,000 N), 이음 입구 두 판의 상대 변위(미끄럼)는 준다.
 */

import { cloneElement } from 'react'
import type { ReactElement } from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('recharts', async () => {
  const actual = await vi.importActual<typeof import('recharts')>('recharts')
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 400, height: 300 } as Record<string, unknown>),
  }
})

import type { Study, StudyPoint } from '@/modules/simulations/api'
import { metricsOf, StudyValues } from '@/modules/simulations/StudyValues'

function point(number: number, friction: number, force: number, slip: number): StudyPoint {
  return {
    simulation_id: `s${number}`,
    number,
    params: { 마찰계수: friction },
    status: 'done',
    recipe: 'static',
    solver: 'calculix',
    frequencies: [],
    mass_kg: 0.31,
    max_displacement_mm: 0.04,
    max_von_mises_mpa: 120,
    reactions_n: { '당기는 끝': [force, 0.3, -12.1] },
    probes_mm: { '이음 입구 위판': 0.04, '이음 입구 아래판': 0.04 - slip },
    probe_vectors_mm: {},
    probe_peaks_hz: {},
    relative_mm: { '이음 입구 위판 - 이음 입구 아래판': [slip, 0, 0] },
  }
}

const SHEAR: Study = {
  study_id: 'bdb89e7',
  name: '전단이음',
  factors: ['마찰계수'],
  recipe: 'static',
  solvers: ['calculix'],
  tracks: [],
  points: [point(1, 0.15, 1499.6, 0.0217), point(2, 0.3, 2999.1, 0.0108), point(3, 0.6, 3610, 0)],
}

describe('정적 · 조화 DOE', () => {
  it('정적이면 변형 · 응력 · 반력 · 측정점 · 상대 변위를 견줄 값으로 낸다', () => {
    const labels = metricsOf('static', SHEAR.points).map((one) => one.label)
    expect(labels).toEqual([
      '최대 변형',
      '최대 상당응력',
      '반력 당기는 끝',
      '측정점 이음 입구 위판 변위',
      '측정점 이음 입구 아래판 변위',
      '상대 변위 이음 입구 위판 - 이음 입구 아래판',
    ])
  })

  it('조화면 봉우리 주파수를 잇지 않는 값으로 표시한다', () => {
    // **봉우리가 다른 공진으로 옮겨 탈 수 있다** — 선으로 이으면 순번으로 이은 모드와 같다.
    const metrics = metricsOf('harmonic', [
      { ...point(1, 0.15, 0, 0), recipe: 'harmonic', probes_mm: { 측정점: 0.4 }, probe_peaks_hz: { 측정점: 1263.5 } },
    ])
    const peak = metrics.find((one) => one.key === 'peak_hz')
    expect(peak?.scatterOnly).toBe(true)
    expect(metrics.find((one) => one.key === 'probe-hz:측정점')?.scatterOnly).toBe(true)
    expect(metrics.find((one) => one.key === 'probe:측정점')?.scatterOnly).toBeUndefined()
  })

  it('표에 설계점마다 모든 값을 단위와 함께 보여 준다', () => {
    render(
      <MemoryRouter>
        <StudyValues study={SHEAR} />
      </MemoryRouter>,
    )
    expect(screen.getByText('반력 당기는 끝 (N)')).toBeDefined()
    expect(screen.getByText('상대 변위 이음 입구 위판 - 이음 입구 아래판 (mm)')).toBeDefined()
    // 힘은 다섯 자리 — 손셈 1,500 N 과 견준 차이가 사라지지 않게.
    expect(screen.getAllByText('1,499.6').length).toBeGreaterThan(0)
    expect(screen.getByRole('img', { name: /마찰계수 대 최대 변형/ })).toBeDefined()
  })
})
