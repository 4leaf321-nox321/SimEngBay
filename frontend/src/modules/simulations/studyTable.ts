/**
 * DOE 를 **표 한 장**으로 — 설계 변수와 결과를 같은 줄에 놓고 여러 그림이 같은 표를 본다.
 *
 * 「다변수」 탭의 그림들(3D 산점도 · 2변수 영향 · 주효과 · 산점도 행렬 · 평행 좌표 · 상관)은 모두 이
 * 표의 열을 고른다. 열을 그림마다 따로 만들면 같은 「1차 모드」 가 그림마다 다른 값이 된다.
 *
 * ## 모달은 추적한 모드로 센다
 *
 * 「k차 주파수」 를 순번으로 꺼내면 치수가 바뀌어 모드 순서가 뒤바뀐 점에서 **다른 모드**를 집는다
 * (mode crossing). 그래서 모달의 결과 열은 서버가 MAC 으로 이은 추적(`study.tracks`)이다 — 비교
 * 탭의 모드 지도와 같은 값이다.
 *
 * 값은 서버가 **mm · MPa · N · Hz 로 맞춰** 보낸다(`app/core/values.py`) — 여기서 다시 옮기지 않는다.
 */

import type { ModeTrack, Study, StudyPoint } from '@/modules/simulations/api'
import { massScale } from '@/modules/simulations/format'
import { metricsOf } from '@/modules/simulations/StudyValues'

/** 그림이 고를 수 있는 열 하나. */
export interface Column {
  key: string
  label: string
  unit: string
  kind: 'factor' | 'result'
  /** 숫자 열인가 — 재료 같은 고르는 값은 축에 좌표를 못 매긴다(평행 좌표에서만 순번으로 놓는다). */
  numeric: boolean
  value: (point: StudyPoint) => number | string | null
}

/** 모달에서 추적한 모드 몇 개까지 열로 둘지 — 비교 탭의 모드 지도와 같다. */
const MAX_TRACKS = 6

function frequency(point: StudyPoint, track: ModeTrack): number | null {
  const number = (track.numbers as Record<string, number>)[String(point.number)]
  if (number == null) return null
  return point.frequencies?.[number - 1] ?? null
}

/** 끝난 설계점만 — 실패 · 대기 점의 빈 값이 그림에 0 으로 섞이지 않게. */
export function rowsOf(study: Study): StudyPoint[] {
  return study.points.filter((one) => one.status === 'done')
}

export function columnsOf(study: Study): Column[] {
  const rows = rowsOf(study)
  const factors: Column[] = study.factors.map((name) => ({
    key: `factor:${name}`,
    label: name,
    unit: '',
    kind: 'factor',
    // **하나라도 글자면 범주로 본다** — 섞여 있으면 좌표를 못 매긴다(비교 탭과 같은 규칙).
    numeric: rows.every((one) => typeof one.params[name] !== 'string'),
    value: (point) => point.params[name] ?? null,
  }))

  const results: Column[] =
    study.recipe === 'modal'
      ? (study.tracks ?? []).slice(0, MAX_TRACKS).map((track) => ({
          key: `mode:${track.reference}`,
          label: `${track.reference}차 모드`,
          unit: 'Hz',
          kind: 'result',
          numeric: true,
          value: (point) => frequency(point, track),
        }))
      : metricsOf(study.recipe, rows).map((metric) => ({
          key: metric.key,
          label: metric.label,
          unit: metric.unit,
          kind: 'result',
          numeric: true,
          value: metric.pick,
        }))

  // 모드를 추적하지 못한 모달(설계점 하나 · 기준이 없음)도 1차는 견준다.
  if (study.recipe === 'modal' && results.length === 0) {
    results.push({
      key: 'first_elastic_hz',
      label: '1차 고유진동수',
      unit: 'Hz',
      kind: 'result',
      numeric: true,
      value: (point) => point.first_elastic_hz ?? null,
    })
  }
  // **질량은 그 DOE 에 맞는 한 단위로**(kg · g · mg) — 작은 부품을 kg 으로 그리면 축이 모두 0
  // 근처다. 0 이하는 없는 값이다(옛 작업은 반올림으로 0 이 남았다).
  const mass = massScale(rows.map((one) => one.mass_kg))
  // **바디마다의 질량** — 지그와 부품은 같은 바디라 전체 질량에 강체 지그까지 든다(서버
  // `materials.mass_summary`). 시편만 견주려면 그 바디의 열을 고른다(「질량 · 시편」).
  const bodies = [...new Set(rows.flatMap((one) => Object.keys(one.mass_by_body ?? {})))]
  for (const body of bodies) {
    results.push({
      key: `mass:${body}`,
      label: `질량 · ${body}`,
      unit: mass.unit,
      kind: 'result',
      numeric: true,
      value: (point) => {
        const kg = point.mass_by_body?.[body]
        return kg != null && kg > 0 ? kg * mass.factor : null
      },
    })
  }
  if (rows.some((one) => one.mass_kg != null && one.mass_kg > 0)) {
    results.push({
      key: 'mass_kg',
      label: '질량',
      unit: mass.unit,
      kind: 'result',
      numeric: true,
      value: (point) => (point.mass_kg != null && point.mass_kg > 0 ? point.mass_kg * mass.factor : null),
    })
  }
  // 값이 하나도 없는 열은 뺀다 — 고를 수 있으면 사람은 빈 그림을 「영향 없음」 으로 읽는다.
  return [...factors, ...results].filter((column) =>
    rows.some((one) => column.value(one) != null),
  )
}

export function labelOf(column: Column): string {
  return column.unit ? `${column.label} [${column.unit}]` : column.label
}

/** 숫자 값만 — 없거나 글자면 null. */
export function numberOf(column: Column, point: StudyPoint): number | null {
  const value = column.value(point)
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * 피어슨 상관계수. 짝이 셋 미만이거나 한쪽이 변하지 않으면 **null** — 0 으로 적으면 「상관없다」 로
 * 읽힌다(값이 하나뿐인 변수는 상관을 말할 수 없다).
 */
export function pearson(pairs: [number, number][]): number | null {
  if (pairs.length < 3) return null
  const n = pairs.length
  const mx = pairs.reduce((sum, [x]) => sum + x, 0) / n
  const my = pairs.reduce((sum, [, y]) => sum + y, 0) / n
  let sxy = 0
  let sxx = 0
  let syy = 0
  for (const [x, y] of pairs) {
    sxy += (x - mx) * (y - my)
    sxx += (x - mx) ** 2
    syy += (y - my) ** 2
  }
  if (sxx === 0 || syy === 0) return null
  return sxy / Math.sqrt(sxx * syy)
}

export function correlation(rows: StudyPoint[], a: Column, b: Column): number | null {
  const pairs: [number, number][] = []
  for (const row of rows) {
    const x = numberOf(a, row)
    const y = numberOf(b, row)
    if (x != null && y != null) pairs.push([x, y])
  }
  return pearson(pairs)
}

/** 주효과 — 변수의 수준마다 결과의 평균 · 최소 · 최대(다른 변수는 섞인 채로). */
export interface Effect {
  level: number | string
  mean: number
  min: number
  max: number
  count: number
}

/** 이보다 수준이 많은 숫자 변수는 같은 수의 점으로 `BINS` 구간에 묶는다(서버 `analysis.py` 와 같다). */
const MAX_LEVELS = 10
const BINS = 5

export function mainEffect(rows: StudyPoint[], factor: Column, result: Column): Effect[] {
  const groups = new Map<string, { level: number | string; values: number[] }>()
  for (const row of rows) {
    const level = factor.value(row)
    const value = numberOf(result, row)
    if (level == null || value == null) continue
    const key = String(level)
    const group = groups.get(key) ?? { level, values: [] }
    group.values.push(value)
    groups.set(key, group)
  }
  if (factor.numeric && groups.size > MAX_LEVELS) return binnedEffect(rows, factor, result)
  const effects = [...groups.values()].map(({ level, values }) => ({
    level,
    mean: values.reduce((sum, one) => sum + one, 0) / values.length,
    min: Math.min(...values),
    max: Math.max(...values),
    count: values.length,
  }))
  return effects.sort((a, b) =>
    typeof a.level === 'number' && typeof b.level === 'number'
      ? a.level - b.level
      : String(a.level).localeCompare(String(b.level)),
  )
}

/**
 * **수준이 많은 변수**(LHS 처럼 점마다 값이 다른 것) — 점 하나짜리 수준 200개의 평균은 효과가 아니라
 * 잡음이다. 변수 값 순서로 같은 수의 점씩 다섯 구간에 묶고, 구간을 「아래~위」 로 적는다.
 */
function binnedEffect(rows: StudyPoint[], factor: Column, result: Column): Effect[] {
  const ordered = rows
    .filter((row) => numberOf(factor, row) != null)
    .sort((a, b) => (numberOf(factor, a) ?? 0) - (numberOf(factor, b) ?? 0))
  const effects: Effect[] = []
  for (let index = 0; index < BINS; index += 1) {
    const part = ordered.slice(
      Math.floor((index * ordered.length) / BINS),
      Math.floor(((index + 1) * ordered.length) / BINS),
    )
    const values = part.map((row) => numberOf(result, row)).filter((one): one is number => one != null)
    if (!part.length || !values.length) continue
    const low = Number((numberOf(factor, part[0]) ?? 0).toPrecision(4))
    const high = Number((numberOf(factor, part[part.length - 1]) ?? 0).toPrecision(4))
    effects.push({
      level: `${low}~${high}`,
      mean: values.reduce((sum, one) => sum + one, 0) / values.length,
      min: Math.min(...values),
      max: Math.max(...values),
      count: values.length,
    })
  }
  return effects
}

/**
 * 두 변수의 격자 — 수준의 모든 조합에 값이 있으면 등고선을 그릴 수 있다(전 조합 설계). 같은
 * 조합이 여럿이면(다른 변수가 따로 움직였다) 평균이다. 빈 칸이 있으면 **null** — 빈 칸을 메워
 * 그린 등고선은 없는 값을 지어낸다(그때는 산점도로).
 */
export interface Grid {
  xs: number[]
  ys: number[]
  /** z[j][i] — ys[j] 행, xs[i] 열(plotly 의 모양). */
  z: number[][]
}

export function gridOf(rows: StudyPoint[], x: Column, y: Column, z: Column): Grid | null {
  const cells = new Map<string, number[]>()
  const xs = new Set<number>()
  const ys = new Set<number>()
  for (const row of rows) {
    const a = numberOf(x, row)
    const b = numberOf(y, row)
    const c = numberOf(z, row)
    if (a == null || b == null || c == null) continue
    xs.add(a)
    ys.add(b)
    const key = `${a}|${b}`
    cells.set(key, [...(cells.get(key) ?? []), c])
  }
  const sortedX = [...xs].sort((p, q) => p - q)
  const sortedY = [...ys].sort((p, q) => p - q)
  if (sortedX.length < 2 || sortedY.length < 2) return null
  const grid: number[][] = []
  for (const b of sortedY) {
    const line: number[] = []
    for (const a of sortedX) {
      const values = cells.get(`${a}|${b}`)
      if (!values) return null
      line.push(values.reduce((sum, one) => sum + one, 0) / values.length)
    }
    grid.push(line)
  }
  return { xs: sortedX, ys: sortedY, z: grid }
}
