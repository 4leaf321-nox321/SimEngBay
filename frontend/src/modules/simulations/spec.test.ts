/**
 * 스펙 만들기 — **레시피가 받지 않는 칸은 싣지 않는다**(서버는 모르는 칸을 통째로 거절한다).
 */

import { describe, expect, it } from 'vitest'

import type { SimulationSummary } from '@/modules/simulations/api'
import { shownOutcome } from '@/modules/simulations/format'
import { buildSpec, HARMONIC_DEFAULTS, NO_RANGE, RANDOM_DEFAULTS, specProblem } from '@/modules/simulations/spec'
import type { SpecInput } from '@/modules/simulations/spec'

const BASE: SpecInput = {
  recipe: 'modal',
  solver: 'ansys',
  conditionsFrom: 'cad',
  elementSize: '',
  order: 'quadratic',
  modes: '10',
  constraints: [],
  largeDeflection: false,
  harmonic: HARMONIC_DEFAULTS,
  modalRange: NO_RANGE,
}

describe('스펙 만들기', () => {
  it('모달은 모드 수를, 정적은 큰 변형을, 조화는 범위 · 점 수 · 감쇠비를 싣는다', () => {
    expect(buildSpec(BASE).modes).toBe(10)
    const statics = buildSpec({ ...BASE, recipe: 'static', largeDeflection: true })
    expect('modes' in statics).toBe(false)
    expect(statics.large_deflection).toBe(true)
    const shake = buildSpec({
      ...BASE,
      recipe: 'harmonic',
      harmonic: { low: '200', high: '2000', intervals: '90', dampingPercent: '2' },
    })
    expect(shake.frequency_range_hz).toEqual([200, 2000])
    expect(shake.intervals).toBe(90)
    expect(shake.damping_ratio).toBeCloseTo(0.02)
    expect('large_deflection' in shake).toBe(false)
  })

  it('모달의 찾을 주파수 범위 — 비우면 싣지 않고, 하한을 비우면 0, 틀리면 까닭을 말한다', () => {
    expect('frequency_range_hz' in buildSpec(BASE)).toBe(false)
    expect(buildSpec({ ...BASE, modalRange: { low: '200', high: '3000' } }).frequency_range_hz).toEqual([200, 3000])
    expect(buildSpec({ ...BASE, modalRange: { low: '', high: '3000' } }).frequency_range_hz).toEqual([0, 3000])
    // 조화에는 모달 범위를 싣지 않는다 — 조화의 범위는 훑을 범위다.
    const shake = buildSpec({ ...BASE, recipe: 'harmonic', modalRange: { low: '1', high: '9' } })
    expect(shake.frequency_range_hz).toEqual([0, 2000])
    expect(specProblem({ ...BASE, modalRange: { low: '200', high: '' } })).toMatch('찾을 주파수 범위')
    expect(specProblem({ ...BASE, modalRange: { low: '3000', high: '200' } })).toMatch('하한 < 상한')
    expect(specProblem({ ...BASE, modalRange: { low: '200', high: '3000' } })).toBeNull()
  })

  it('요소 크기를 비우면 싣지 않는다 — CAD 의 「전체」 크기가 쓰인다', () => {
    expect(buildSpec(BASE).mesh).toEqual({ order: 'quadratic' })
    expect(buildSpec({ ...BASE, elementSize: '2.5', order: 'linear' }).mesh).toEqual({
      element_size_mm: 2.5,
      order: 'linear',
    })
  })

  it('물성은 싣지 않는다 — CompCore 가 점 파일에 파트마다 정해 보낸다', () => {
    const spec = buildSpec(BASE)
    expect('material' in spec).toBe(false)
    expect('material_from' in spec).toBe(false)
  })

  it('구속 영역은 완전 고정으로 싣는다', () => {
    expect(buildSpec({ ...BASE, constraints: ['bolt_holes'] }).constraints).toEqual([
      { region: 'bolt_holes', kind: 'fixed' },
    ])
  })

  it('서버가 거절할 값을 미리 말한다', () => {
    expect(specProblem(BASE)).toBeNull()
    expect(
      specProblem({ ...BASE, recipe: 'harmonic', harmonic: { ...HARMONIC_DEFAULTS, high: '0' } }),
    ).toMatch(/주파수 범위/)
    // 정적에는 모드 수가 없다 — 비어 있어도 문제가 아니다.
    expect(specProblem({ ...BASE, recipe: 'static', modes: '' })).toBeNull()
  })
})

describe('랜덤 진동 스펙', () => {
  const random: SpecInput = { ...BASE, recipe: 'random', solver: 'calculix' }

  it('모드 수 · 감쇠비를 싣고 범위는 비우면 PSD 표의 범위다', () => {
    const spec = buildSpec(random)
    expect(spec).toMatchObject({ recipe: 'random', modes: 10, damping_ratio: 0.02 })
    expect('frequency_range_hz' in spec).toBe(false)
    expect('intervals' in spec).toBe(false)
    const ranged = buildSpec({ ...random, random: { ...RANDOM_DEFAULTS, low: '20', high: '1000' } })
    expect(ranged.frequency_range_hz).toEqual([20, 1000])
    expect(specProblem(random)).toBeNull()
  })

  it('Ansys · 틀린 범위 · 감쇠비는 보내기 전에 막는다', () => {
    expect(specProblem({ ...random, solver: 'ansys' })).toContain('CalculiX 로만')
    expect(specProblem({ ...random, random: { ...RANDOM_DEFAULTS, low: '500', high: '100' } })).toContain(
      '셈할 주파수 범위',
    )
    expect(specProblem({ ...random, random: { ...RANDOM_DEFAULTS, dampingPercent: '0' } })).toContain('감쇠비')
  })
})

function row(recipe: string, summary: Record<string, unknown>): SimulationSummary {
  return { recipe, summary } as unknown as SimulationSummary
}

describe('목록의 결과 칸', () => {
  it('해석 종류마다 보는 값이 다르다', () => {
    expect(shownOutcome(row('modal', { first_elastic_hz: 1266.42 }))).toBe('1차 1266.4 Hz')
    expect(shownOutcome(row('harmonic', { peak_hz: 1263.5 }))).toBe('봉우리 1263.5 Hz')
    expect(
      shownOutcome(row('static', { max_displacement: 0.0401, solver_unit_system: 'ConsistentNMM' })),
    ).toBe('최대 변형 0.0401 mm')
    // Ansys 를 SI 로 돌리면 길이가 m 다 — mm 로 박으면 1000배 틀린다.
    expect(
      shownOutcome(row('static', { max_displacement: 4e-5, solver_unit_system: 'ConsistentMKS' })),
    ).toBe('최대 변형 0.00004 m')
    expect(shownOutcome(row('static', {}))).toBeNull()
    // 랜덤 — 측정점이 있으면 그 자리의 가속도 1σ, 없으면 최대 1σ 변위.
    expect(shownOutcome(row('random', { probe_grms: '측정점 36.72 g' }))).toBe('측정점 36.72 g (1σ)')
    expect(shownOutcome(row('random', { max_displacement_1sigma_mm: 0.0058 }))).toBe('최대 1σ 변위 0.0058 mm')
  })
})
