/**
 * **한눈에 보기 줄** — 해석 작업 화면 맨 위, 탭 위에 늘 있다.
 *
 * 화면이 단계 · 요약 · 조건 · 결과 · 실측 · 수렴 · 산출물 순으로 아래로만 쌓여 있어서, 사람이 제일
 * 먼저 보려는 숫자가 화면 중간 아래에 있었다(2026-10-05). 그래서 위에 둔다:
 *
 * - **왼쪽 — 대표 숫자.** 해석 종류마다 다르다: 모달은 1차 고유진동수 · 탄성 모드 수 · 질량 · 절점,
 *   정적은 최대 변형 · 최대 상당응력 · 반력 · 측정점, 조화는 봉우리 주파수 · 봉우리 변위 · 감쇠비 ·
 *   측정점. 끝나기 전에는 단계 넷이 어디까지 왔는지를 보인다.
 * - **오른쪽 — 이 숫자를 믿어도 되나.** 메시 수렴 판정 · 실측과의 차이 · CAD 조건(반영 · 넘김 · 막음).
 *   누르면 그 탭으로 간다.
 */

import { useEffect, useState } from 'react'

import { simulationApi } from '@/modules/simulations/api'
import type { Convergence, Measurement, Simulation, Stage } from '@/modules/simulations/api'
import { shownForce, shownValue } from '@/modules/simulations/format'
import { STAGE_LABELS, shownDuration } from '@/modules/simulations/labels'
import { isHarmonic, isStatic } from '@/modules/simulations/ResultPanel'
import type { AnyResult } from '@/modules/simulations/ResultPanel'
import { StatusBadge } from '@/shared/components/StatusBadge'

export type DetailTab = 'result' | 'progress' | 'checks' | 'files'

interface Stat {
  label: string
  value: string
  /** 숫자 밑의 작은 글 — 무엇의 값인지(방향 · 자리). */
  hint?: string
}

interface Props {
  simulation: Simulation
  result: AnyResult | null
  onJump: (tab: DetailTab) => void
  /** 검증 탭이 더 나중에 읽은 값 — 있으면 처음 읽은 것 대신 이것을 쓴다(점검을 걸고 돌아왔다). */
  convergence?: Convergence
  measurements?: Measurement[]
}

function summaryNumber(simulation: Simulation, key: string): number | null {
  const value = (simulation.summary ?? {})[key]
  return typeof value === 'number' ? value : null
}

const DIRECTION_LABELS: Record<string, string> = {
  X: 'X 이동',
  Y: 'Y 이동',
  Z: 'Z 이동',
  ROTX: 'X 회전',
  ROTY: 'Y 회전',
  ROTZ: 'Z 회전',
}

/** 해석 종류마다 대표 숫자 — 결과가 아직 없으면 요약에서. */
export function headline(simulation: Simulation, result: AnyResult | null): Stat[] {
  const nodes = result?.mesh?.nodes ?? summaryNumber(simulation, 'nodes')
  const mass = summaryNumber(simulation, 'mass_kg')
  const common: Stat[] = [
    ...(mass !== null ? [{ label: '질량', value: `${shownValue(mass)} kg` }] : []),
    ...(nodes !== null ? [{ label: '절점', value: nodes.toLocaleString() }] : []),
  ]
  if (result && isStatic(result)) {
    const reactions = Object.entries(result.reactions ?? {}).map(([name, [x, y, z]]) => ({
      name,
      size: Math.hypot(x, y, z),
    }))
    const largest = reactions.sort((a, b) => b.size - a.size)[0]
    const probe = result.probes?.[0]
    return [
      { label: '최대 변형', value: shownValue(result.max_displacement, result.units.displacement ?? 'mm') },
      {
        label: '최대 상당응력',
        value: shownValue(result.max_von_mises, result.units.stress ?? 'MPa'),
      },
      ...(largest
        ? [{ label: '반력', value: shownForce(largest.size, result.units.force ?? 'N'), hint: largest.name }]
        : []),
      ...(probe ? [{ label: '측정점', value: shownValue(probe.value, probe.unit), hint: probe.name }] : []),
      ...common,
    ].slice(0, 4)
  }
  if (result && isHarmonic(result)) {
    const probe = result.probes?.[0]
    return [
      { label: '봉우리 주파수', value: `${result.peak.frequency_hz.toLocaleString()} Hz` },
      {
        label: '봉우리 변위',
        value: shownValue(result.peak.max_displacement, result.units.displacement ?? 'mm'),
        hint: '모델 전체 최대',
      },
      { label: '감쇠비', value: `${(result.damping_ratio * 100).toFixed(1)}%` },
      ...(probe
        ? [{ label: '측정점 봉우리', value: shownValue(probe.value, probe.unit), hint: probe.name }]
        : []),
      ...common,
    ].slice(0, 4)
  }
  if (result && 'modes' in result) {
    const elastic = result.modes.filter((one) => !one.rigid_body)
    const first = elastic[0]
    const direction = first?.dominant_direction
      ? `${DIRECTION_LABELS[first.dominant_direction] ?? first.dominant_direction}${
          first.effective_mass_ratio != null ? ` ${(first.effective_mass_ratio * 100).toFixed(0)}%` : ''
        }`
      : undefined
    return [
      ...(first
        ? [{ label: '1차 고유진동수', value: `${first.frequency_hz.toLocaleString()} Hz`, hint: direction }]
        : []),
      {
        label: '탄성 모드',
        value: `${elastic.length}개`,
        hint: result.rigid_body_modes ? `강체 ${result.rigid_body_modes}개` : undefined,
      },
      ...common,
    ].slice(0, 4)
  }
  // 결과를 아직 못 받았다 — 요약에 있는 것만.
  const first = summaryNumber(simulation, 'first_elastic_hz')
  return [...(first !== null ? [{ label: '1차 고유진동수', value: `${first.toFixed(1)} Hz` }] : []), ...common]
}

type Tone = 'good' | 'warn' | 'bad' | 'none'

// 수렴 점검이 도는 동안 다시 묻는 간격 — 검증 탭(`ConvergencePanel`)과 같다.
const POLL_MS = 5000

const TONES: Record<Tone, string> = {
  good: 'text-emerald-700 dark:text-emerald-400',
  warn: 'text-amber-700 dark:text-amber-400',
  bad: 'text-destructive',
  none: 'text-muted-foreground',
}

/** 메시 수렴 판정 한 마디 — 값마다의 판정을 묶는다. */
export function convergenceWord(found: Convergence | null): { text: string; tone: Tone } {
  if (!found || found.levels.length <= 1) return { text: '점검 안 함', tone: 'none' }
  if (found.levels.some((one) => !['done', 'failed', 'canceled'].includes(one.status))) {
    return { text: '도는 중', tone: 'none' }
  }
  const statuses = found.metrics.map((one) => one.status)
  if (statuses.length > 0 && statuses.every((one) => one === 'converged')) return { text: '수렴', tone: 'good' }
  if (statuses.includes('diverging')) return { text: '발산 있음', tone: 'warn' }
  if (statuses.includes('not_converged')) return { text: '미수렴', tone: 'warn' }
  return { text: '판정 보류', tone: 'none' }
}

/** 실측과의 차이 한 마디 — 가장 가까운 실측의 평균 차이. */
export function measurementWord(found: Measurement[] | null): { text: string; tone: Tone } {
  if (!found || found.length === 0) return { text: '없음', tone: 'none' }
  const scores = found
    .map((one) => one.comparison?.score_pct)
    .filter((one): one is number => typeof one === 'number')
  if (scores.length === 0) return { text: `${found.length}건 · 견줄 값 없음`, tone: 'none' }
  const best = Math.min(...scores)
  return { text: `차이 ${best.toFixed(1)}%`, tone: best <= 5 ? 'good' : 'warn' }
}

function Stage4({ stages }: { stages: Stage[] }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="단계">
      {stages.map((stage) => (
        <li key={stage.name} className="space-y-1">
          <StatusBadge kind="stage" value={stage.status} />
          <p className="text-sm font-medium">{STAGE_LABELS[stage.name] ?? stage.name}</p>
          {stage.started_at && (
            <p className="text-muted-foreground text-xs">{shownDuration(stage.started_at, stage.finished_at)}</p>
          )}
        </li>
      ))}
    </ol>
  )
}

export function ResultGlance({ simulation, result, onJump, ...reported }: Props) {
  const done = simulation.status === 'done'
  const [convergence, setConvergence] = useState<Convergence | null>(null)
  const [measurements, setMeasurements] = useState<Measurement[] | null>(null)

  useEffect(() => {
    setConvergence(null)
    setMeasurements(null)
    if (!done) return
    let disposed = false
    // **믿음 배지는 덤이다** — 못 받으면 「점검 안 함」 · 「없음」 으로 둔다(탭에서 까닭을 본다).
    simulationApi
      .convergence(simulation.id)
      .then((next) => !disposed && setConvergence(next))
      .catch(() => {})
    simulationApi
      .measurements(simulation.id)
      .then((next) => !disposed && setMeasurements(next))
      .catch(() => {})
    return () => {
      disposed = true
    }
  }, [simulation.id, done])

  // **나중에 읽은 것이 이긴다** — 검증 탭이 알려 온 값이든 여기서 다시 물은 값이든.
  useEffect(() => {
    if (reported.convergence) setConvergence(reported.convergence)
  }, [reported.convergence])
  useEffect(() => {
    if (reported.measurements) setMeasurements(reported.measurements)
  }, [reported.measurements])

  // **점검이 도는 동안은 다시 묻는다** — 검증 탭을 닫아도(탭은 안 보이면 내려간다) 배지가
  // 「도는 중」 에 멈춰 있지 않게.
  const running = convergence?.levels.some((one) => !['done', 'failed', 'canceled'].includes(one.status)) ?? false
  useEffect(() => {
    if (!running) return
    let disposed = false
    const timer = setInterval(() => {
      simulationApi
        .convergence(simulation.id)
        .then((next) => !disposed && setConvergence(next))
        .catch(() => {})
    }, POLL_MS)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [simulation.id, running])

  const lines = simulation.conditions?.lines ?? []
  const count = (status: string) => lines.filter((one) => one.status === status).length
  const refused = count('refused')
  const converged = convergenceWord(convergence)
  const measured = measurementWord(measurements)
  const stats = headline(simulation, result)

  return (
    <section
      aria-label="한눈에 보기"
      className="grid gap-4 rounded-md border p-4 lg:grid-cols-[minmax(0,1fr)_auto]"
    >
      {done ? (
        stats.length > 0 ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
            {stats.map((one) => (
              <div key={one.label} className="min-w-0">
                <dt className="text-muted-foreground text-xs">{one.label}</dt>
                <dd className="truncate font-mono text-lg font-semibold tabular-nums">{one.value}</dd>
                {one.hint && <dd className="text-muted-foreground truncate text-xs">{one.hint}</dd>}
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-muted-foreground text-sm">결과를 불러오는 중…</p>
        )
      ) : (
        <Stage4 stages={simulation.stages} />
      )}

      <div className="grid grid-cols-3 gap-x-6 gap-y-1 text-sm lg:border-l lg:pl-6">
        <button
          type="button"
          className="text-left disabled:cursor-default"
          disabled={!done}
          onClick={() => onJump('checks')}
        >
          <span className="text-muted-foreground block text-xs">메시 수렴</span>
          <span className={TONES[done ? converged.tone : 'none']}>{done ? converged.text : '—'}</span>
        </button>
        <button
          type="button"
          className="text-left disabled:cursor-default"
          disabled={!done}
          onClick={() => onJump('checks')}
        >
          <span className="text-muted-foreground block text-xs">실측</span>
          <span className={TONES[done ? measured.tone : 'none']}>{done ? measured.text : '—'}</span>
        </button>
        <button type="button" className="text-left" onClick={() => onJump('progress')}>
          <span className="text-muted-foreground block text-xs">CAD 조건</span>
          {lines.length === 0 ? (
            <span className={TONES.none}>없음</span>
          ) : (
            <span className={refused > 0 ? TONES.bad : TONES.none}>
              반영 {count('applied')} · 넘김 {count('skipped')}
              {refused > 0 && ` · 막음 ${refused}`}
            </span>
          )}
        </button>
      </div>
    </section>
  )
}
