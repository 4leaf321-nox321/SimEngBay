/** 결과 화면이 함께 쓰는 수 표기 — 크기에 맞춰 자릿수를 고른다(1 이상 네 자리, 그 아래 여섯 자리). */

export function shownValue(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const digits = Math.abs(value) >= 1 ? 4 : 6
  return `${Number(value.toPrecision(digits))}${unit ? ` ${unit}` : ''}`
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
