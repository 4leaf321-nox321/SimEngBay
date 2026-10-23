/** 결과 화면이 함께 쓰는 수 표기 — 크기에 맞춰 자릿수를 고른다(1 이상 네 자리, 그 아래 여섯 자리). */

import type { SimulationSummary } from '@/modules/simulations/api'

export function shownValue(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const digits = Math.abs(value) >= 1 ? 4 : 6
  return `${Number(value.toPrecision(digits))}${unit ? ` ${unit}` : ''}`
}

/** 질량을 적는 단위 — 표의 열 · 그래프 축처럼 **여러 값을 한 단위로** 적을 때 쓴다. */
export interface MassScale {
  unit: 'kg' | 'g' | 'mg'
  /** kg 에 곱하는 수. */
  factor: number
}

/** 여러 질량에 맞는 단위 — 가장 큰 값이 1 이상이 되는 단위(kg · g · mg). */
export function massScale(values: readonly (number | null | undefined)[]): MassScale {
  const sizes = values.filter((one): one is number => one != null && Number.isFinite(one) && one > 0)
  const top = sizes.length ? Math.max(...sizes) : 1
  if (top >= 1) return { unit: 'kg', factor: 1 }
  if (top >= 1e-3) return { unit: 'g', factor: 1e3 }
  return { unit: 'mg', factor: 1e6 }
}

/**
 * 질량 — **크기에 맞는 단위로, 유효숫자 네 자리.** kg 소수 둘째 자리로 적으면 작은 부품(0.029 g)이
 * 「0.00 kg」 이 되어 없는 것처럼 보였다(2026-10-23 운영). 0 이하는 없는 값이다(옛 작업은 kg 을
 * 소수 넷째 자리로 잘라 0 으로 남았다).
 */
export function shownMass(kg: number | null | undefined, scale?: MassScale): string {
  if (kg == null || !Number.isFinite(kg) || kg <= 0) return '—'
  const { unit, factor } = scale ?? massScale([kg])
  return `${Number((kg * factor).toPrecision(4))} ${unit}`
}

/**
 * 힘 — **다섯 자리에 자릿점.** 네 자리로 줄이면 1,499.6 N 이 1500 N 이 되어, 손셈(μN = 1,500 N)과
 * 맞춰 본 그 차이가 화면에서 사라진다.
 */
export function shownForce(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${Number(value.toPrecision(5)).toLocaleString()}${unit ? ` ${unit}` : ''}`
}

/** 벡터의 크기. */
export function magnitudeOf(vector: readonly number[]): number {
  return Math.sqrt(vector.reduce((sum, one) => sum + one * one, 0))
}

/** 가장 크게 움직인 축(X · Y · Z). 셋이 다 0 이면 없다. */
export function axisOf(vector: readonly number[] | undefined): string | null {
  if (!vector || vector.length < 3) return null
  const sizes = vector.slice(0, 3).map((one) => Math.abs(one))
  const top = Math.max(...sizes)
  if (top <= 0) return null
  return ['X', 'Y', 'Z'][sizes.indexOf(top)]
}

/**
 * 결과 한 칸 — **해석 종류마다 보는 값이 다르다.** 요약(`summary`)에는 단위가 없어서, 모델링이
 * 적은 솔버 단위계로 길이 단위를 정한다(CalculiX 는 늘 mm · Ansys 는 MKS 면 m).
 */
export function shownOutcome(row: SimulationSummary): string | null {
  const summary = (row.summary ?? {}) as Record<string, unknown>
  const number = (key: string) => (typeof summary[key] === 'number' ? (summary[key] as number) : null)
  const length = String(summary.solver_unit_system ?? '').includes('MKS') ? 'm' : 'mm'
  if (row.recipe === 'static') {
    const largest = number('max_displacement')
    return largest === null ? null : `최대 변형 ${shownValue(largest, length)}`
  }
  if (row.recipe === 'harmonic') {
    const peak = number('peak_hz')
    return peak === null ? null : `봉우리 ${peak.toFixed(1)} Hz`
  }
  const first = number('first_elastic_hz')
  return first === null ? null : `1차 ${first.toFixed(1)} Hz`
}
