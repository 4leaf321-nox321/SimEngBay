/**
 * 작업 스펙 만들기 — 새 작업 창과 DOE 가져오기 창이 **같은 함수**로 만든다.
 *
 * 서버의 스펙(`backend/app/core/spec.py`)은 레시피마다 받는 칸이 다르고 **모르는 칸은 통째로
 * 거절한다**(정적에 `modes` 를 실으면 400). 두 창이 각자 조립하면 한쪽만 고쳐지고, 그때 한 창은
 * 400 을 받는다. 그래서 여기 한 곳에서 레시피별로 칸을 고른다.
 *
 * **물성은 싣지 않는다** — CompCore 가 점 파일에 파트마다 정해 보낸다(서버 `material_from` 기본
 * `cad`). 화면에서 한 벌을 받아 모든 파트에 붙이는 길은 없앴다: 조립품에서는 뜻이 없고,
 * 결과가 CompCore 의 정의로 거슬러 올라가지 않는다.
 */

import type { Solver } from '@/modules/simulations/SolverSelect'

export type RecipeName = 'modal' | 'static' | 'harmonic'

export const RECIPE_NAMES: RecipeName[] = ['modal', 'static', 'harmonic']

export function isRecipe(value: string | null | undefined): value is RecipeName {
  return RECIPE_NAMES.includes(value as RecipeName)
}

/** 조화 응답의 설정. **CAD 가 적은 값이 있으면 그것이 먼저다**(서버의 `harmonic_plan`). */
export interface HarmonicInput {
  low: string
  high: string
  intervals: string
  /** 감쇠비(%) — 사람은 2% 로 말한다. 서버에는 0.02 로 간다. */
  dampingPercent: string
}

/** 서버 스펙의 기본값과 같다(`HarmonicSpec`). */
export const HARMONIC_DEFAULTS: HarmonicInput = {
  low: '0',
  high: '2000',
  intervals: '10',
  dampingPercent: '2',
}

export type MeshOrder = 'quadratic' | 'linear'

export function isOrder(value: string | null | undefined): value is MeshOrder {
  return value === 'quadratic' || value === 'linear'
}

export interface SpecInput {
  recipe: RecipeName
  solver: Solver
  conditionsFrom: 'cad' | 'spec'
  /** 비우면 CAD 의 「전체」 크기 → 없으면 Ansys 기본(CalculiX 는 멈춘다). */
  elementSize: string
  order: MeshOrder
  /** 탄성 모드 수(모달) · 모드 중첩에 쓸 모드 수(조화). */
  modes: string
  /** 완전 고정할 영역 이름 — CAD 조건이 있으면 그것이 먼저다. */
  constraints: string[]
  largeDeflection: boolean
  harmonic: HarmonicInput
}

/** 화면의 입력 → 서버 스펙. 레시피가 받지 않는 칸은 싣지 않는다. */
export function buildSpec(input: SpecInput): Record<string, unknown> {
  const size = input.elementSize.trim()
  const spec: Record<string, unknown> = {
    recipe: input.recipe,
    solver: input.solver,
    conditions_from: input.conditionsFrom,
    mesh: { ...(size ? { element_size_mm: Number(size) } : {}), order: input.order },
    constraints: input.constraints.map((region) => ({ region, kind: 'fixed' })),
  }
  if (input.recipe === 'modal') spec.modes = Number(input.modes)
  if (input.recipe === 'static') spec.large_deflection = input.largeDeflection
  if (input.recipe === 'harmonic') {
    spec.modes = Number(input.modes)
    spec.frequency_range_hz = [Number(input.harmonic.low), Number(input.harmonic.high)]
    spec.intervals = Number(input.harmonic.intervals)
    spec.damping_ratio = Number(input.harmonic.dampingPercent) / 100
  }
  return spec
}

/** 보내기 전에 막을 것 — 서버가 400 으로 답할 것을 미리 말한다. 없으면 `null`. */
export function specProblem(input: SpecInput): string | null {
  if (input.recipe !== 'static' && !(Number(input.modes) >= 1)) return '모드 수는 1 이상입니다.'
  if (input.elementSize.trim() && !(Number(input.elementSize) > 0))
    return '요소 크기는 0 보다 커야 합니다.'
  if (input.recipe === 'harmonic') {
    const { low, high, intervals, dampingPercent } = input.harmonic
    if (!(Number(high) > Number(low) && Number(low) >= 0)) return '주파수 범위가 올바르지 않습니다.'
    if (!(Number(intervals) >= 1)) return '점 수는 1 이상입니다.'
    if (!(Number(dampingPercent) > 0 && Number(dampingPercent) < 100))
      return '감쇠비는 0 보다 크고 100% 보다 작아야 합니다.'
  }
  return null
}
