/**
 * DOE 표 — 여러 그림이 같은 표를 본다. 모달은 **추적한 모드**로, 정적 · 조화는 견줄 값으로, 끝난 점만.
 */
import { describe, expect, it } from 'vitest'

import type { Study, StudyPoint } from '@/modules/simulations/api'
import {
  columnsOf,
  correlation,
  gridOf,
  mainEffect,
  pearson,
  rowsOf,
} from '@/modules/simulations/studyTable'

function point(number: number, params: Record<string, number | string>, extra: Partial<StudyPoint> = {}): StudyPoint {
  return {
    simulation_id: `s${number}`,
    number,
    params,
    status: 'done',
    published: false,
    recipe: 'static',
    solver: 'calculix',
    frequencies: [],
    mass_kg: 0.3,
    reactions_n: {},
    probes_mm: {},
    probe_vectors_mm: {},
    probe_peaks_hz: {},
    relative_mm: {},
    ...extra,
  } as StudyPoint
}

function study(points: StudyPoint[], extra: Partial<Study> = {}): Study {
  return {
    study_id: 's',
    name: '브래킷',
    factors: ['두께', '폭'],
    recipe: 'static',
    solvers: ['calculix'],
    points,
    published: 0,
    tracks: [],
    ...extra,
  } as Study
}

describe('columnsOf', () => {
  it('설계 변수 다음에 결과 — 값이 하나도 없는 열은 뺀다', () => {
    const one = study([
      point(1, { 두께: 2, 폭: 10 }, { max_displacement_mm: 0.4, max_von_mises_mpa: 120 }),
      point(2, { 두께: 3, 폭: 10 }, { max_displacement_mm: 0.2, max_von_mises_mpa: 90 }),
    ])
    const keys = columnsOf(one).map((column) => column.key)
    expect(keys.slice(0, 2)).toEqual(['factor:두께', 'factor:폭'])
    expect(keys).toContain('max_mm')
    expect(keys).toContain('mass_kg')
  })

  it('글자 값이 하나라도 있으면 범주(숫자 축에 못 놓는다)', () => {
    const one = study([point(1, { 두께: 2, 폭: 'SS400' }), point(2, { 두께: 3, 폭: 'AL6061' })])
    const 폭 = columnsOf(one).find((column) => column.key === 'factor:폭')
    expect(폭?.numeric).toBe(false)
  })

  it('모달은 순번이 아니라 추적한 모드로 센다(mode crossing)', () => {
    // 2번 점에서는 기준의 1차 모드가 2번째로 내려앉았다.
    const one = study(
      [
        point(1, { 두께: 2, 폭: 10 }, { recipe: 'modal', frequencies: [100, 200] }),
        point(2, { 두께: 3, 폭: 10 }, { recipe: 'modal', frequencies: [150, 180] }),
      ],
      {
        recipe: 'modal',
        tracks: [{ reference: 1, numbers: { 1: 1, 2: 2 }, confidence: { 1: 1, 2: 0.9 } }],
      } as Partial<Study>,
    )
    const mode = columnsOf(one).find((column) => column.key === 'mode:1')
    expect(rowsOf(one).map((row) => mode?.value(row))).toEqual([100, 180])
  })

  it('끝난 점만 — 실패 · 대기 점은 표에 없다', () => {
    const one = study([point(1, { 두께: 2, 폭: 1 }), point(2, { 두께: 3, 폭: 1 }, { status: 'failed' })])
    expect(rowsOf(one).map((row) => row.number)).toEqual([1])
  })
})

describe('pearson · correlation', () => {
  it('함께 오르면 1, 반대면 −1', () => {
    expect(pearson([[1, 2], [2, 4], [3, 6]])).toBeCloseTo(1)
    expect(pearson([[1, 6], [2, 4], [3, 2]])).toBeCloseTo(-1)
  })

  it('변하지 않거나 셋 미만이면 말하지 않는다(0 이 아니다)', () => {
    expect(pearson([[1, 5], [2, 5], [3, 5]])).toBeNull()
    expect(pearson([[1, 2], [2, 3]])).toBeNull()
  })

  it('열 둘 사이 — 값이 없는 점은 뺀다', () => {
    const one = study([
      point(1, { 두께: 1, 폭: 1 }, { max_displacement_mm: 3 }),
      point(2, { 두께: 2, 폭: 1 }, { max_displacement_mm: 2 }),
      point(3, { 두께: 3, 폭: 1 }, { max_displacement_mm: 1 }),
      point(4, { 두께: 4, 폭: 1 }, { max_displacement_mm: null }),
    ])
    const [두께] = columnsOf(one)
    const 변형 = columnsOf(one).find((column) => column.key === 'max_mm')!
    expect(correlation(rowsOf(one), 두께, 변형)).toBeCloseTo(-1)
  })
})

describe('mainEffect', () => {
  it('수준마다 평균 · 최소 · 최대(다른 변수는 섞인 채로)', () => {
    const one = study([
      point(1, { 두께: 2, 폭: 10 }, { max_von_mises_mpa: 100 }),
      point(2, { 두께: 2, 폭: 20 }, { max_von_mises_mpa: 80 }),
      point(3, { 두께: 3, 폭: 10 }, { max_von_mises_mpa: 60 }),
    ])
    const columns = columnsOf(one)
    const effects = mainEffect(rowsOf(one), columns[0], columns.find((c) => c.key === 'max_mpa')!)
    expect(effects).toEqual([
      { level: 2, mean: 90, min: 80, max: 100, count: 2 },
      { level: 3, mean: 60, min: 60, max: 60, count: 1 },
    ])
  })
})

describe('mainEffect(수준이 많을 때)', () => {
  it('수준이 열을 넘으면 같은 수의 점으로 다섯 구간 — 서버의 분석과 같다', () => {
    const points = Array.from({ length: 20 }, (_, index) =>
      point(index + 1, { 두께: 1 + (index + 1) * 0.1, 폭: 1 }, { max_displacement_mm: 10 - index * 0.3 }),
    )
    const one = study(points)
    const columns = columnsOf(one)
    const effects = mainEffect(rowsOf(one), columns[0], columns.find((c) => c.key === 'max_mm')!)
    expect(effects).toHaveLength(5)
    expect(effects.every((each) => each.count === 4)).toBe(true)
    expect(effects[0].level).toBe('1.1~1.4')
  })
})

describe('gridOf', () => {
  const full = [
    point(1, { 두께: 2, 폭: 10 }, { max_displacement_mm: 4 }),
    point(2, { 두께: 3, 폭: 10 }, { max_displacement_mm: 3 }),
    point(3, { 두께: 2, 폭: 20 }, { max_displacement_mm: 2 }),
    point(4, { 두께: 3, 폭: 20 }, { max_displacement_mm: 1 }),
  ]

  it('전 조합이면 등고선 격자(z[행=y][열=x])', () => {
    const one = study(full)
    const columns = columnsOf(one)
    const grid = gridOf(rowsOf(one), columns[0], columns[1], columns.find((c) => c.key === 'max_mm')!)
    expect(grid).toEqual({ xs: [2, 3], ys: [10, 20], z: [[4, 3], [2, 1]] })
  })

  it('빈 조합이 있으면 그리지 않는다 — 메우면 없는 값을 지어낸다', () => {
    const one = study(full.slice(0, 3))
    const columns = columnsOf(one)
    expect(gridOf(rowsOf(one), columns[0], columns[1], columns.find((c) => c.key === 'max_mm')!)).toBeNull()
  })
})
