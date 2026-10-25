/**
 * DOE 표 — 여러 그림이 같은 표를 본다. 모달은 **추적한 모드**로, 정적 · 조화는 견줄 값으로, 끝난 점만.
 */
import { describe, expect, it } from 'vitest'

import type { Study, StudyPoint } from '@/modules/simulations/api'
import {
  caseTicks,
  chooseFrom,
  columnsOf,
  correlation,
  gridOf,
  leadingFactor,
  mainEffect,
  pearson,
  rowsOf,
  sensitivityOf,
  slicesOf,
  spanOf,
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

  it('바디마다의 질량을 열로 — 지그와 부품은 같은 바디라 전체 질량에 지그까지 든다', () => {
    const one = study([
      point(1, { 두께: 3, 폭: 10 }, { mass_kg: 0.0398, mass_by_body: { 시편: 0.00288, 롤러: 0.0369 } }),
      point(2, { 두께: 4, 폭: 10 }, { mass_kg: 0.0408, mass_by_body: { 시편: 0.00384, 롤러: 0.0369 } }),
    ])
    const body = columnsOf(one).find((column) => column.key === 'mass:시편')
    expect(body?.label).toBe('질량 · 시편')
    // 그 DOE 의 질량 단위(g)로 — 전체 질량과 같은 단위다.
    expect(body?.unit).toBe('g')
    const [thin, thick] = rowsOf(one).map((row) => Number(body?.value(row)))
    expect(thin).toBeCloseTo(2.88)
    expect(thick).toBeCloseTo(3.84)
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

/**
 * 전 조합 2 x 2 — 두께가 변형을 크게, 폭은 작게 움직인다. 질량은 둘 다에 비례.
 *   p1 두께 2 폭 10 → 4.0 mm · 20 g      p2 두께 3 폭 10 → 2.0 mm · 30 g
 *   p3 두께 2 폭 20 → 3.6 mm · 40 g      p4 두께 3 폭 20 → 1.6 mm · 60 g
 */
const GRID = study([
  point(1, { 두께: 2, 폭: 10 }, { max_displacement_mm: 4.0, mass_kg: 0.02 }),
  point(2, { 두께: 3, 폭: 10 }, { max_displacement_mm: 2.0, mass_kg: 0.03 }),
  point(3, { 두께: 2, 폭: 20 }, { max_displacement_mm: 3.6, mass_kg: 0.04 }),
  point(4, { 두께: 3, 폭: 20 }, { max_displacement_mm: 1.6, mass_kg: 0.06 }),
])
const COLUMNS = columnsOf(GRID)
const column = (key: string) => COLUMNS.find((one) => one.key === key)!

describe('sensitivityOf — 변수가 여럿일 때 요약의 영향 순위', () => {
  it('주효과의 폭 ÷ 평균(%) 이 큰 차례 — 서버 analysis.effect 와 같은 셈', () => {
    const factors = COLUMNS.filter((one) => one.kind === 'factor')
    const ranked = sensitivityOf(rowsOf(GRID), factors, column('max_mm'))
    expect(ranked.map((one) => one.factor.label)).toEqual(['두께', '폭'])
    // 두께: 수준 평균 3.8 · 1.8 → 폭 2.0, 전체 평균 2.8 → 71.4%. 폭: 3.0 · 2.6 → 14.3%.
    expect(ranked[0].spreadPct).toBeCloseTo(71.43, 1)
    expect(ranked[1].spreadPct).toBeCloseTo(14.29, 1)
    expect(ranked[0].correlation).toBeLessThan(-0.9) // 두꺼우면 덜 휜다
  })

  it('수준이 하나뿐인 변수는 말할 수 없다(0 이 아니다)', () => {
    const one = study([point(1, { 두께: 2, 폭: 10 }), point(2, { 두께: 2, 폭: 20 })], {
      factors: ['두께', '폭'],
    })
    const columns = columnsOf(one)
    const ranked = sensitivityOf(
      rowsOf(one),
      columns.filter((c) => c.kind === 'factor'),
      columns.find((c) => c.key === 'mass_kg')!,
    )
    expect(ranked.find((r) => r.factor.label === '두께')?.spreadPct).toBeNull()
  })
})

describe('spanOf · caseTicks', () => {
  it('최소 · 최대와 그 점', () => {
    expect(spanOf(rowsOf(GRID), column('max_mm'))).toEqual({ min: 1.6, max: 4, minPoint: 4, maxPoint: 1 })
  })

  it('눈금 아래의 설계점 — 같은 값에 점이 여럿이면 「외 n」', () => {
    expect(caseTicks(GRID.points, '두께')).toEqual([
      { value: 2, label: 'p0001 외 1' },
      { value: 3, label: 'p0002 외 1' },
    ])
    expect(caseTicks([GRID.points[0]], '두께')).toEqual([{ value: 2, label: 'p0001' }])
  })
})

describe('chooseFrom — 최적점 찾기', () => {
  const rows = rowsOf(GRID)

  it('목표 하나 — 조건을 만족한 점 중 목표가 가장 좋은 점이 「최적」', () => {
    // 질량(g) 50 이하에서 변형이 가장 작은 점 — p4(60 g)는 빠지고 p2.
    const found = chooseFrom(rows, COLUMNS, [{ column: 'max_mm', goal: 'min' }], [
      { column: 'mass_kg', op: '<=', value: '50' },
    ])
    expect(found.feasible.map((one) => one.number)).toEqual([1, 2, 3])
    expect(found.ranked.map((one) => one.number)).toEqual([2, 3, 1])
    expect([...found.marks]).toEqual([[2, 'best']])
  })

  it('목표 둘 — 서로 맞바꾸는 점(파레토)이 「후보」, 앞서는 점이 있으면 빠진다', () => {
    // 변형 작게 · 질량 작게: p3(3.6 mm · 40 g)은 p2(2.0 mm · 30 g)에 진다.
    const found = chooseFrom(
      rows,
      COLUMNS,
      [
        { column: 'max_mm', goal: 'min' },
        { column: 'mass_kg', goal: 'min' },
      ],
      [],
    )
    expect(found.ranked.map((one) => one.number)).toEqual([4, 2, 1])
    expect(found.marks.get(3)).toBeUndefined()
    expect(found.marks.get(4)).toBe('pareto')
  })

  it('값이 빈 조건은 아직 걸지 않는다 — 그 수를 따로 말한다', () => {
    const found = chooseFrom(rows, COLUMNS, [], [{ column: 'max_mm', op: '>=', value: ' ' }])
    expect(found.feasible).toHaveLength(4)
    expect(found.idle).toBe(1)
    expect(found.marks.size).toBe(0)
  })

  it('「=」 는 숫자면 숫자로, 글자면 글자 그대로(재료)', () => {
    expect(
      chooseFrom(rows, COLUMNS, [], [{ column: 'factor:두께', op: '=', value: '3.0' }]).feasible.map(
        (one) => one.number,
      ),
    ).toEqual([2, 4])
    const byMaterial = study([point(1, { 재료: 'SS400' }), point(2, { 재료: 'AL6061' })], { factors: ['재료'] })
    expect(
      chooseFrom(rowsOf(byMaterial), columnsOf(byMaterial), [], [
        { column: 'factor:재료', op: '=', value: 'AL6061' },
      ]).feasible.map((one) => one.number),
    ).toEqual([2])
  })
})

describe('slicesOf · leadingFactor — 변수가 여럿일 때 어디까지 잇나', () => {
  it('나머지 변수가 같은 점끼리만 묶는다 — 그 안에서만 가로축을 따라 잇는다', () => {
    const found = slicesOf(GRID.points, GRID.factors, '두께')
    expect(found.map((one) => [one.label, [...one.numbers]])).toEqual([
      ['폭 = 10', [1, 2]],
      ['폭 = 20', [3, 4]],
    ])
  })

  it('묶이지 않으면(무작위 · LHS — 점마다 값이 다르다) 단면이 없다 · 변수가 하나면 단면도 없다', () => {
    const scattered = [point(1, { 두께: 2, 폭: 11 }), point(2, { 두께: 3, 폭: 17 }), point(3, { 두께: 4, 폭: 13 })]
    expect(slicesOf(scattered, ['두께', '폭'], '두께')).toEqual([])
    expect(slicesOf(GRID.points, ['두께'], '두께')).toEqual([])
  })

  it('처음 가로축은 그 결과를 가장 크게 움직이는 변수 — 변수 차례가 아니다', () => {
    // 변형은 두께가 71%, 폭이 14% 를 움직인다. 질량은 폭(20 → 50 g 평균)이 두께보다 크다.
    const widthFirst = { ...GRID, factors: ['폭', '두께'] }
    expect(leadingFactor(widthFirst, 'max_mm')).toBe('두께')
    expect(leadingFactor(widthFirst, 'mass_kg')).toBe('폭')
    expect(leadingFactor(study([point(1, { 두께: 2 })], { factors: ['두께'] }), 'max_mm')).toBeNull()
  })
})
