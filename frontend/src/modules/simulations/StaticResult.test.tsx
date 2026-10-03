/**
 * 정적 결과 — **센서 자리의 값과 버틴 힘을 보여 주는가.**
 *
 * 값은 CompCore 의 전단 이음(μ 0.15 · 클램프 10 kN)을 CalculiX 로 푼 실측에서 추렸다: 당기는
 * 끝의 반력 1,499.6 N(손셈 μN = 1,500 N), 이음 입구의 두 판 측정점은 **같은 좌표 · 다른 바디**
 * 다. 두 판의 X 성분 차가 미끄럼(0.0217 mm)이다 — 크기만 보면 두 판이 함께 밀린 것과 서로
 * 미끄러진 것이 구별되지 않는다.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { StaticResult as StaticResultData } from '@/modules/simulations/api'
import { StaticResult } from '@/modules/simulations/StaticResult'

const SHEAR: StaticResultData = {
  recipe: 'static',
  solver: 'calculix',
  units: { system: 'ConsistentNMM', displacement: 'mm', stress: 'MPa', force: 'N' },
  mesh: { nodes: 1328, elements: 179 },
  max_displacement: 0.0401,
  max_von_mises: 123.4,
  material: 'SS400',
  probes: [
    {
      name: '이음 입구 위판',
      point: [60, 12.5, 5],
      node: 812,
      distance_mm: 0,
      value: 0.0401,
      unit: 'mm',
      vector: [0.0401, -0.0002, 0.0013],
      body: '위판',
    },
    {
      name: '이음 입구 아래판',
      point: [60, 12.5, 5],
      node: 377,
      distance_mm: 0,
      value: 0.0184,
      unit: 'mm',
      vector: [0.0184, 0.0001, 0.0002],
      body: '아래판',
    },
  ],
  reactions: { '당기는 끝': [1499.6, 0.3, -12.1] },
}

describe('정적 결과', () => {
  it('측정점의 변위를 크기와 성분으로 보여 준다', () => {
    render(<StaticResult simulationId="sim" result={SHEAR} artifacts={[]} />)
    expect(screen.getByText('측정점 변위')).toBeDefined()
    expect(screen.getByText('이음 입구 위판')).toBeDefined()
    expect(screen.getByText('위판')).toBeDefined()
    expect(screen.getAllByText('0.0401 mm').length).toBeGreaterThan(0)
  })

  it('같은 자리 두 바디의 차를 미끄럼으로 읽을 수 있게 적는다', () => {
    render(<StaticResult simulationId="sim" result={SHEAR} artifacts={[]} />)
    // 0.0401 − 0.0184 = 0.0217 mm — 손셈과 해석이 맞춰 본 그 값이다.
    expect(screen.getByText(/상대 변위\(위판 − 아래판\): X 0\.0217/)).toBeDefined()
  })

  it('반력을 영역마다 성분과 크기로 보여 준다', () => {
    render(<StaticResult simulationId="sim" result={SHEAR} artifacts={[]} />)
    expect(screen.getByText('반력')).toBeDefined()
    expect(screen.getByText('당기는 끝')).toBeDefined()
    // **다섯 자리로** — 네 자리면 1,499.6 이 1500 이 되어 손셈과 견준 차이가 사라진다.
    // Fx 와 크기가 같은 값이다(옆 성분이 작다).
    expect(screen.getAllByText('1,499.6 N')).toHaveLength(2)
    expect(screen.getByText('-12.1 N')).toBeDefined()
  })

  it('멀리 떨어진 절점이면 백엔드의 경고를 그대로 보여 준다', () => {
    const far: StaticResultData = {
      ...SHEAR,
      probes: [
        {
          ...SHEAR.probes![0],
          distance_mm: 1.37,
          warning: '가장 가까운 절점이 1.37 mm 떨어져 있습니다 — 메시를 그 자리에서 촘촘하게 하거나 측정점을 절점에 맞추세요.',
        },
      ],
    }
    render(<StaticResult simulationId="sim" result={far} artifacts={[]} />)
    expect(screen.getByText(/1\.37 mm 떨어져 있습니다/)).toBeDefined()
  })

  it('측정점 · 반력이 없는 결과는 그 표를 그리지 않는다', () => {
    // 점 그룹이 없는 작업 · 모의 실행기 작업이 그렇다 — 빈 표는 「0 이 여럿」 으로 읽힌다.
    const bare: StaticResultData = { ...SHEAR, probes: undefined, reactions: undefined }
    render(<StaticResult simulationId="sim" result={bare} artifacts={[]} />)
    expect(screen.queryByText('측정점 변위')).toBeNull()
    expect(screen.queryByText('반력')).toBeNull()
    expect(screen.getByText('최대 변형')).toBeDefined()
  })
})
