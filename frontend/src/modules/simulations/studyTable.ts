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

/** 모달에서 추적한 모드 몇 개까지 열로 둘지 — 비교 탭의 모드 지도와 같다(서버 `analysis.MAX_TRACKS`). */
export const MAX_TRACKS = 6

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

/**
 * 변수 하나가 결과를 얼마나 움직이나 — **주효과의 폭**(수준별 평균의 최대 - 최소)을 결과의 평균에
 * 견준 %. 서버 `analysis.effect` 와 같은 셈이다(MCP `study_analyze` 가 같은 순위를 말한다).
 *
 * 다른 변수는 섞인 채로 평균한다 — 전 조합 설계가 아니면(무작위 · LHS) 다른 변수의 효과가 섞일 수
 * 있어 상관계수를 함께 낸다.
 */
export interface Sensitivity {
  factor: Column
  /** 수준이 하나뿐이거나 평균이 0 이면 null — 「영향 없음」 과 「말할 수 없음」 은 다르다. */
  spreadPct: number | null
  correlation: number | null
}

export function sensitivityOf(rows: StudyPoint[], factors: Column[], result: Column): Sensitivity[] {
  const every = rows.map((row) => numberOf(result, row)).filter((one): one is number => one != null)
  const middle = every.length ? every.reduce((sum, one) => sum + one, 0) / every.length : 0
  const found = factors.map((factor) => {
    const means = mainEffect(rows, factor, result).map((one) => one.mean)
    const spread = means.length > 1 ? Math.max(...means) - Math.min(...means) : null
    return {
      factor,
      spreadPct: spread != null && middle ? (spread / Math.abs(middle)) * 100 : null,
      correlation: factor.numeric ? correlation(rows, factor, result) : null,
    }
  })
  // 폭이 큰 차례 — 말할 수 없는 변수는 뒤로(서버와 같은 차례).
  return found.sort((a, b) => Math.abs(b.spreadPct ?? -1) - Math.abs(a.spreadPct ?? -1))
}

/** 결과 하나의 최소 · 최대와 **그 점** — 「얼마에서 얼마」 만으로는 어느 설계가 그랬는지 모른다. */
export interface Span {
  min: number
  max: number
  minPoint: number
  maxPoint: number
}

export function spanOf(rows: StudyPoint[], column: Column): Span | null {
  let span: Span | null = null
  for (const row of rows) {
    const value = numberOf(column, row)
    if (value == null) continue
    if (span === null) {
      span = { min: value, max: value, minPoint: row.number, maxPoint: row.number }
      continue
    }
    // 같으면 앞의 점 — 서버의 min · max 와 같다.
    if (value < span.min) span = { ...span, min: value, minPoint: row.number }
    if (value > span.max) span = { ...span, max: value, maxPoint: row.number }
  }
  return span
}

// --- 최적점 찾기 ---------------------------------------------------------------------------

export type Goal = 'min' | 'max'
export type Op = '>=' | '<=' | '='

/** 목표 하나 — 어느 결과를 작게(`min`) · 크게(`max`). */
export interface Objective {
  column: string
  goal: Goal
}

/** 조건 한 줄 — 「1차 모드 ≥ 300」. 값이 비었으면 아직 걸지 않은 것이다. */
export interface Condition {
  column: string
  op: Op
  value: string
}

export interface Choice {
  /** 조건을 모두 만족한 끝난 점. */
  feasible: StudyPoint[]
  /** 목표 하나면 목표 차례(좋은 것 먼저), 둘이면 파레토 점을 첫 목표 차례로. */
  ranked: StudyPoint[]
  /** 표에 붙일 표시 — 목표 하나의 맨 앞은 「최적」, 목표 둘의 파레토는 「후보」. */
  marks: Map<number, 'best' | 'pareto'>
  /** 값이 비어 아직 걸지 않은 조건 수 — 「왜 안 걸러지지」 에 답한다. */
  idle: number
}

function holds(condition: Condition, column: Column, row: StudyPoint): boolean {
  const found = column.value(row)
  const raw = condition.value.trim()
  const target = Number(raw)
  if (condition.op === '=') {
    // 숫자면 숫자로(「3」 과 「3.0」 은 같다), 아니면 글자 그대로(재료 이름).
    return typeof found === 'number' && raw !== '' && Number.isFinite(target)
      ? found === target
      : String(found ?? '') === raw
  }
  if (typeof found !== 'number' || !Number.isFinite(target)) return false
  return condition.op === '>=' ? found >= target : found <= target
}

/** `a` 가 `b` 를 앞서나 — 모든 목표에서 같거나 낫고, 하나라도 낫다. */
function dominates(a: number[], b: number[], goals: Goal[]): boolean {
  let better = false
  for (let index = 0; index < goals.length; index += 1) {
    const [x, y] = goals[index] === 'max' ? [a[index], b[index]] : [b[index], a[index]]
    if (x < y) return false
    if (x > y) better = true
  }
  return better
}

/**
 * **조건을 만족한 점 중에서 고른다.** 서버 `analysis.analyze` 의 `choice` 와 같은 규칙이고(MCP 가
 * 같은 답을 낸다), 목표를 둘 주면 **파레토** — 두 목표 모두에서 더 나은 점이 없는 점들 — 를 낸다.
 * 무게와 강성처럼 서로 맞바꾸는 두 값은 「가장 좋은 하나」 가 없고, 그 사이에서 고르는 것은 사람의
 * 몫이다.
 */
export function chooseFrom(
  rows: StudyPoint[],
  columns: Column[],
  objectives: Objective[],
  where: Condition[],
): Choice {
  const byKey = new Map(columns.map((one) => [one.key, one]))
  const active = where.filter((one) => one.value.trim() !== '' && byKey.has(one.column))
  const feasible = rows.filter((row) =>
    active.every((one) => holds(one, byKey.get(one.column) as Column, row)),
  )
  const aims = objectives
    .map((one) => ({ ...one, found: byKey.get(one.column) }))
    .filter((one): one is Objective & { found: Column } => one.found != null)
  const marks = new Map<number, 'best' | 'pareto'>()
  const scored = feasible
    .map((row) => ({ row, values: aims.map((one) => numberOf(one.found, row)) }))
    .filter((one): one is { row: StudyPoint; values: number[] } => one.values.every((v) => v != null))
  const first = (a: { values: number[] }, b: { values: number[] }) =>
    aims[0].goal === 'max' ? b.values[0] - a.values[0] : a.values[0] - b.values[0]

  let ranked: StudyPoint[] = feasible
  if (aims.length === 1) {
    ranked = [...scored].sort(first).map((one) => one.row)
    if (ranked.length) marks.set(ranked[0].number, 'best')
  } else if (aims.length >= 2) {
    const goals = aims.map((one) => one.goal)
    const front = scored.filter(
      (one) => !scored.some((other) => other !== one && dominates(other.values, one.values, goals)),
    )
    ranked = [...front].sort(first).map((one) => one.row)
    for (const one of ranked) marks.set(one.number, 'pareto')
  }
  return { feasible, ranked, marks, idle: where.length - active.length }
}

/** 설계점의 이름 — 「p0002」. */
export function caseName(number: number): string {
  return `p${String(number).padStart(4, '0')}`
}

/**
 * 가로축이 설계 변수일 때 **눈금 아래에 적을 설계점** — 값마다 「p0002」, 같은 값에 점이 여럿이면
 * (다른 변수가 따로 움직였다) 「p0002 외 3」. 숫자 값만 — 재료 같은 고르는 값은 축이 아니다.
 */
export function caseTicks(points: StudyPoint[], factor: string): { value: number; label: string }[] {
  const byValue = new Map<number, number[]>()
  for (const point of points) {
    const value = point.params[factor]
    if (typeof value !== 'number') continue
    byValue.set(value, [...(byValue.get(value) ?? []), point.number])
  }
  return [...byValue.entries()]
    .sort(([a], [b]) => a - b)
    .map(([value, numbers]) => {
      const sorted = [...numbers].sort((a, b) => a - b)
      return {
        value,
        label: caseName(sorted[0]) + (sorted.length > 1 ? ` 외 ${sorted.length - 1}` : ''),
      }
    })
}

// --- 가로축과 단면 -------------------------------------------------------------------------

/**
 * 가로축 말고 **나머지 변수의 값이 같은 점들**(단면) — 그 안에서만 가로축을 따라 이을 수 있다.
 *
 * 변수가 여럿인 DOE 에서 가로축 값 순서로 점을 다 이으면, 같은 가로축 값에 다른 설계(폭 10 · 20 ·
 * 30 …)가 세로로 쌓여 선이 지그재그로 서로 다른 설계를 잇는다 — 없는 그림보다 나쁘다. 가로축 값이
 * 둘 이상인 묶음만 낸다(점 하나짜리 단면은 이을 것이 없다 — 무작위 · LHS 설계는 대개 이렇다).
 */
export interface Slice {
  key: string
  /** 「폭 = 20」 · 「폭 = 20 · 높이 = 5」 */
  label: string
  numbers: Set<number>
}

export function slicesOf(points: StudyPoint[], factors: string[], x: string): Slice[] {
  const others = factors.filter((one) => one !== x)
  if (others.length === 0) return []
  const groups = new Map<string, { values: (number | string | null)[]; numbers: number[]; xs: Set<number> }>()
  for (const point of points) {
    const across = point.params[x]
    if (typeof across !== 'number') continue
    const values = others.map((name) => point.params[name] ?? null)
    const key = JSON.stringify(values)
    const group = groups.get(key) ?? { values, numbers: [], xs: new Set<number>() }
    group.numbers.push(point.number)
    group.xs.add(across)
    groups.set(key, group)
  }
  const order = (a: number | string | null, b: number | string | null) =>
    typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b))
  return [...groups.entries()]
    .filter(([, group]) => group.xs.size >= 2)
    .sort(([, a], [, b]) => {
      for (let index = 0; index < a.values.length; index += 1) {
        const found = order(a.values[index], b.values[index])
        if (found !== 0) return found
      }
      return 0
    })
    .map(([key, group]) => ({
      key,
      label: others.map((name, index) => `${name} = ${group.values[index] ?? '—'}`).join(' · '),
      numbers: new Set(group.numbers),
    }))
}

/**
 * 처음 가로축 — **그 결과를 가장 크게 움직이는 변수.** 변수 순서(CompCore 가 보낸 차례)대로 고르면
 * 1차를 거의 안 움직이는 변수가 먼저 보이고, 그 그림은 「변화가 없다」 로 읽힌다. 말할 수 없으면 null.
 */
export function leadingFactor(study: Study, result: string): string | null {
  const columns = columnsOf(study)
  const factors = columns.filter((one) => one.kind === 'factor')
  const target = columns.find((one) => one.key === result) ?? columns.find((one) => one.kind === 'result')
  if (!target || factors.length < 2) return null
  const top = sensitivityOf(rowsOf(study), factors, target)[0]
  return top?.spreadPct != null ? top.factor.label : null
}
