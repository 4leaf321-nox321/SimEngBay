/**
 * 주파수 요구 — 입력 칸(글자)과 요구 조건(숫자) 사이, 판정의 이름, 설계점의 차례.
 *
 * **판정은 서버가 셈한다**(`backend/app/modules/simulations/frequency.py`). 화면은 입력을 고칠 때마다
 * 저장하지 않은 요구로 서버의 셈을 다시 부른다(미리보기) — 같은 규칙을 두 벌로 두지 않는다. 여기는
 * 사람이 친 글자를 요구 조건으로 읽고, 서버가 준 판정을 보여 줄 말을 고른다.
 */

import type {
  FrequencyCheck,
  FrequencyMode,
  FrequencyPoint,
  FrequencyRequirementInput,
} from '@/modules/simulations/api'

export type Verdict = FrequencyPoint['verdict']

type Filled<T> = NonNullable<T>
type Target = Filled<FrequencyPoint['targets']>[number]
type Band = Filled<FrequencyPoint['bands']>[number]

/** 서버가 늘 채워 보내는 칸을 채운 꼴 — 생성 타입은 기본값이 있는 칸을 선택 칸으로 적는다. */
export type Mode = Omit<FrequencyMode, 'track' | 'mass_pct' | 'probe_pct' | 'bands' | 'in_band' | 'reason'> & {
  track: number | null
  mass_pct: Record<string, number>
  probe_pct: Record<string, number>
  /** 이 모드를 판정 대상으로 삼는 회피 대역(요구 조건의 차례). */
  bands: number[]
  in_band: boolean
  reason: string
}
export type TargetResult = Target & { ok: boolean }
export type BandResult = Band & { ok: boolean; inside: boolean }
export type Point = Omit<FrequencyPoint, 'targets' | 'bands' | 'modes' | 'sensitivity' | 'mass_kg'> & {
  targets: TargetResult[]
  bands: BandResult[]
  modes: Mode[]
  sensitivity: Filled<FrequencyPoint['sensitivity']>
  mass_kg: number | null
}
export type Requirement = Filled<FrequencyCheck['requirements']>[number]
export type Crossing = Filled<FrequencyCheck['crossings']>[number]
export type Check = Omit<
  FrequencyCheck,
  'requirements' | 'factors' | 'probes' | 'tracks' | 'counts' | 'points' | 'crossings' | 'notes' | 'tracked' | 'saved'
> & {
  requirements: Requirement[]
  factors: string[]
  probes: string[]
  tracks: number[]
  counts: Record<string, number>
  points: Point[]
  crossings: Crossing[]
  notes: string[]
  tracked: boolean
  saved: boolean
}

/** 서버의 판정 → 빈 칸을 채운 꼴. */
export function filled(check: FrequencyCheck): Check {
  return {
    ...check,
    requirements: check.requirements ?? [],
    factors: check.factors ?? [],
    probes: check.probes ?? [],
    tracks: check.tracks ?? [],
    counts: check.counts ?? {},
    crossings: check.crossings ?? [],
    notes: check.notes ?? [],
    tracked: check.tracked ?? true,
    saved: check.saved ?? false,
    points: (check.points ?? []).map((point) => ({
      ...point,
      mass_kg: point.mass_kg ?? null,
      targets: (point.targets ?? []).map((one) => ({ ...one, ok: one.ok ?? false })),
      bands: (point.bands ?? []).map((one) => ({ ...one, ok: one.ok ?? true, inside: one.inside ?? false })),
      sensitivity: point.sensitivity ?? [],
      modes: (point.modes ?? []).map((mode) => ({
        ...mode,
        track: mode.track ?? null,
        mass_pct: mode.mass_pct ?? {},
        probe_pct: mode.probe_pct ?? {},
        bands: mode.bands ?? [],
        in_band: mode.in_band ?? false,
        reason: mode.reason ?? '',
      })),
    })),
  }
}

/** 판정의 차례 — 후보 표가 이 차례로 선다. */
export const VERDICTS: Verdict[] = ['conform', 'band_violation', 'target_deviation', 'nonconform', 'pending']

export const VERDICT_LABELS: Record<Verdict, string> = {
  conform: '적합',
  band_violation: '대역 침범',
  target_deviation: '목표 이탈',
  nonconform: '부적합',
  pending: '판정 보류',
}

export const VERDICT_HINTS: Record<Verdict, string> = {
  conform: '모든 요구 충족',
  band_violation: '목표 충족 · 회피 대역 침범',
  target_deviation: '대역 회피 · 목표 이탈',
  nonconform: '목표 이탈 · 대역 침범',
  pending: '미완료 · 모드 미추적',
}

/** 상태 배지와 같은 색조(`StatusBadge`) — 색만으로 말하지 않고 아이콘 · 이름과 함께 쓴다. */
export const VERDICT_TONES: Record<Verdict, string> = {
  conform: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  band_violation: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
  target_deviation: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
  nonconform: 'bg-destructive/10 text-destructive',
  pending: 'bg-muted text-muted-foreground',
}

/**
 * VERDICT_TONES 의 옅은 바탕을 화면 바탕에 얹은 것과 **같은 색의 불투명 바탕** — 판정도 칸의 글자 줄에
 * 깔아, 칸 뒤를 지나는 경계선이 글자를 가르지 않고 그 뒤로 숨게 한다. 10 % 를 sRGB 로 섞어야
 * 반투명 겹침과 색이 같다.
 */
export const VERDICT_BACKING: Record<Verdict, string> = {
  conform: 'bg-[color-mix(in_srgb,var(--color-emerald-500)_10%,var(--background))]',
  band_violation: 'bg-[color-mix(in_srgb,var(--color-amber-500)_10%,var(--background))]',
  target_deviation: 'bg-[color-mix(in_srgb,var(--color-amber-500)_10%,var(--background))]',
  nonconform: 'bg-[color-mix(in_srgb,var(--destructive)_10%,var(--background))]',
  pending: 'bg-muted',
}

/** 아이콘만 그릴 때의 글자 색 — 판정 칸의 색조와 같은 계열. */
export const VERDICT_INK: Record<Verdict, string> = {
  conform: 'text-emerald-700 dark:text-emerald-400',
  band_violation: 'text-amber-700 dark:text-amber-400',
  target_deviation: 'text-amber-700 dark:text-amber-400',
  nonconform: 'text-destructive',
  pending: 'text-muted-foreground',
}

export type Direction = 'X' | 'Y' | 'Z'

export interface TargetDraft {
  key: string
  kind: 'target'
  label: string
  mode: string
  target: string
  tolerance: string
}

export interface BandDraft {
  key: string
  kind: 'band'
  label: string
  low: string
  high: string
  margin: string
  massOn: boolean
  direction: Direction
  massMin: string
  probeOn: boolean
  /** 빈 글자 = 측정점 가운데 가장 크게 움직인 값. */
  probe: string
  probeMin: string
}

export type Draft = TargetDraft | BandDraft

type Saved = Requirement

/** 저장된 요구 → 입력 칸. */
export function draftOf(requirement: Saved, key: string): Draft {
  if (requirement.kind === 'target') {
    return {
      key,
      kind: 'target',
      label: requirement.label ?? '',
      mode: String(requirement.mode),
      target: String(requirement.target_hz),
      tolerance: String(requirement.tolerance_pct),
    }
  }
  return {
    key,
    kind: 'band',
    label: requirement.label ?? '',
    low: String(requirement.low_hz),
    high: String(requirement.high_hz),
    margin: String(requirement.margin_pct ?? 0),
    massOn: requirement.mass_filter ?? true,
    direction: (requirement.mass_direction ?? 'Z') as Direction,
    massMin: String(requirement.mass_min_pct ?? 5),
    probeOn: requirement.probe_filter ?? false,
    probe: requirement.probe ?? '',
    probeMin: String(requirement.probe_min_pct ?? 20),
  }
}

export function newTarget(key: string, mode = 1): TargetDraft {
  return { key, kind: 'target', label: '', mode: String(mode), target: '', tolerance: '3' }
}

export function newBand(key: string, probeOn = false): BandDraft {
  return {
    key,
    kind: 'band',
    label: '',
    low: '',
    high: '',
    margin: '10',
    massOn: true,
    direction: 'Z',
    massMin: '5',
    probeOn,
    probe: '',
    probeMin: '20',
  }
}

function numberOf(text: string): number | null {
  const cleaned = text.replace(/,/g, '').trim()
  if (!cleaned) return null
  const value = Number(cleaned)
  return Number.isFinite(value) ? value : null
}

/** 입력 칸 → 요구 조건. 못 읽으면 그 까닭. */
export function parseDraft(draft: Draft): { requirement?: FrequencyRequirementInput; problem?: string } {
  if (draft.kind === 'target') {
    const target = numberOf(draft.target)
    const tolerance = numberOf(draft.tolerance)
    const mode = numberOf(draft.mode)
    if (target == null || target <= 0) return { problem: '목표 주파수를 0 보다 큰 수로 넣으세요.' }
    if (tolerance == null || tolerance < 0 || tolerance > 100) return { problem: '허용 범위는 0–100 % 입니다.' }
    if (mode == null || !Number.isInteger(mode) || mode < 1) return { problem: '대상 모드를 고르세요.' }
    return {
      requirement: { kind: 'target', label: draft.label.trim(), mode, target_hz: target, tolerance_pct: tolerance },
    }
  }
  const low = numberOf(draft.low)
  const high = numberOf(draft.high)
  const margin = numberOf(draft.margin) ?? 0
  const massMin = numberOf(draft.massMin) ?? 0
  const probeMin = numberOf(draft.probeMin) ?? 0
  if (low == null || high == null || low <= 0) return { problem: '회피 대역의 하한과 상한을 넣으세요.' }
  if (high <= low) return { problem: '회피 대역의 상한이 하한보다 커야 합니다.' }
  if (margin < 0 || margin > 100) return { problem: '이격 여유는 0–100 % 입니다.' }
  if (massMin < 0 || massMin > 100 || probeMin < 0 || probeMin > 100)
    return { problem: '판정 대상 모드의 문턱은 0–100 % 입니다.' }
  return {
    requirement: {
      kind: 'band',
      label: draft.label.trim(),
      low_hz: low,
      high_hz: high,
      margin_pct: margin,
      mass_filter: draft.massOn,
      mass_direction: draft.direction,
      mass_min_pct: massMin,
      probe_filter: draft.probeOn,
      probe: draft.probe || null,
      probe_min_pct: probeMin,
    },
  }
}

export function hz(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? '—' : Math.round(value).toLocaleString('ko-KR')
}

/**
 * 기울기(Hz / 단위) — 「+791」 · 「−82」 · 「+0.15」. 정수로 반올림하면 작은 기울기가 「+0」 이 되어
 * 그 옆의 환산 공차(± 50)와 어긋나 보이므로, 100 보다 작으면 유효숫자 둘로 적는다.
 */
export function signedSlope(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const size = Math.abs(value)
  const text = size >= 100 ? hz(size) : size === 0 ? '0' : Number(size.toPrecision(2)).toLocaleString('ko-KR')
  return `${value > 0 ? '+' : value < 0 ? '−' : '±'}${text}`
}

/** 「+1.0 %」 · 「−3.5 %」 — 부호를 늘 적는다(목표보다 높은지 낮은지가 답의 절반이다). */
export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const sign = value > 0.00001 ? '+' : value < -0.00001 ? '−' : '±'
  return `${sign}${Math.abs(value).toFixed(digits)} %`
}

/** 입력 줄 아래에 적는 충족 범위. */
export function ruleOf(draft: Draft): string | null {
  const parsed = parseDraft(draft).requirement
  if (!parsed) return null
  if (parsed.kind === 'target') {
    const width = (parsed.target_hz * parsed.tolerance_pct) / 100
    return `${hz(parsed.target_hz - width)} – ${hz(parsed.target_hz + width)} Hz 안이면 충족`
  }
  const margin = (parsed.margin_pct ?? 0) / 100
  return `${hz(parsed.low_hz * (1 - margin))} Hz 이하 또는 ${hz(parsed.high_hz * (1 + margin))} Hz 이상이면 충족 (이격 여유 포함)`
}

export function modeName(mode: { track?: number | null; index: number }): string {
  return mode.track != null ? `${mode.track}차 모드` : `미추적 모드 (${mode.index}번째)`
}

function compareValues(a: number | string | undefined, b: number | string | undefined): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a ?? '').localeCompare(String(b ?? ''), 'ko')
}

/** 설계 변수 차례로 — 첫 변수로 묶이고 그 안에서 둘째 변수가 오른다. */
export function orderedPoints(points: Point[], factors: string[]): Point[] {
  return points.slice().sort((a, b) => {
    for (const name of factors) {
      const order = compareValues(a.params[name], b.params[name])
      if (order !== 0) return order
    }
    return a.number - b.number
  })
}

/** 값이 모두 숫자이고 두 수준 이상인 설계 변수. */
export function numericFactors(points: Point[], factors: string[]): string[] {
  return factors.filter((name) => {
    const values = points.map((one) => one.params[name])
    return values.length > 0 && values.every((value) => typeof value === 'number') && new Set(values).size > 1
  })
}

export function levelsOf(points: Point[], factor: string): (number | string)[] {
  const values = Array.from(new Set(points.map((one) => one.params[factor]).filter((one) => one !== undefined)))
  return values.sort(compareValues)
}

export function pointName(point: Pick<Point, 'number'>): string {
  return `p${String(point.number).padStart(4, '0')}`
}

export function paramsText(params: Record<string, number | string>): string {
  return Object.entries(params)
    .map(([name, value]) => `${name} ${typeof value === 'number' ? Number(value.toPrecision(4)) : value}`)
    .join(' · ')
}
