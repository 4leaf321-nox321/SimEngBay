/**
 * 해석 작업 상세 — **한눈에 보기 줄 + 탭 넷**(결과 · 진행 · 모델 · 검증 · 파일).
 *
 * 전에는 단계 · 요약 · 조건 · 결과 · 실측 · 수렴 · 산출물이 아래로만 쌓여, 사람이 먼저 보려는 결과가
 * 화면 중간 아래에 있었다(2026-10-05). 이제 대표 숫자와 「믿어도 되나」 배지를 위에 두고, 나머지는
 * 탭으로 가른다. **어느 탭을 여나는 상태가 정한다** — 끝났으면 결과, 아니면 진행 · 모델(실패도 그렇다
 * — 어디서 왜 멈췄나가 거기 있다). 사람이 고른 탭은 주소(`?tab=`)에 남아, 스터디 · 수렴 표에서 오는
 * 링크가 그 탭을 바로 연다.
 *
 * 끝나지 않은 작업은 2초마다 `/status` 를 폴링한다. 그 경로만 접근 로그를 비껴간다
 * (`shared/access_log.py`) — 상세 경로를 그대로 폴링하면 로그가 그 한 줄로 찬다.
 */

import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Download, Eraser, RotateCcw, Square, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { FINAL_STATUSES, simulationApi } from '@/modules/simulations/api'
import type { Artifact, Convergence, Measurement, Simulation, Stage } from '@/modules/simulations/api'
import { ConditionList } from '@/modules/simulations/ConditionList'
import { ConvergencePanel } from '@/modules/simulations/ConvergencePanel'
import { shownMass } from '@/modules/simulations/format'
import { MeasurementsPanel } from '@/modules/simulations/MeasurementsPanel'
import { PublishControl, PublishedBadge } from '@/modules/simulations/Publishing'
import { QueueNotice } from '@/modules/simulations/QueueNotice'
import { ResultGlance } from '@/modules/simulations/ResultGlance'
import { listPath } from '@/modules/simulations/SimulationsLayout'
import type { DetailTab } from '@/modules/simulations/ResultGlance'
import { ResultPanel, useSimulationResult } from '@/modules/simulations/ResultPanel'
import {
  ARTIFACT_LABELS,
  FAILURE_LABELS,
  RECIPE_LABELS,
  SOLVER_LABELS,
  SOLVE_ON_LABELS,
  STAGE_LABELS,
  STE_FAILURES,
  shownDuration,
  shownSize,
  solveOnOf,
  solverOf,
} from '@/modules/simulations/labels'
import type { SolveOn } from '@/modules/simulations/labels'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { ownsWork } from '@/shared/auth/roles'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/components/ui/tabs'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

const POLL_MS = 2000

/** 요약 칸의 이름표. 실행기가 주는 열쇠를 사람의 말로 — 모르는 열쇠는 그대로 보여 준다. */
const SUMMARY_LABELS: Record<string, string> = {
  input_bytes: '입력 크기',
  bodies: '바디',
  nodes: '절점',
  elements: '요소',
  modes: '모드 수',
  modes_requested: '요청 모드 수',
  // **자유-자유는 6개여야 한다.** 다르면 바디가 붙어 있지 않은 것이고, 결과 요약의 경고가
  // 같은 말을 한다.
  rigid_body_modes: '강체 모드',
  first_elastic_hz: '1차 탄성 모드',
  solver_seconds: '솔버 시간',
  // **어느 솔버로 풀었나.** 두 솔버의 수가 몇 % 갈리므로, 이것이 안 보이면 「왜 어제와 값이
  // 다르냐」 를 아무도 설명할 수 없다(실측: 1차 굽힘 Ansys 1,266.4 · CalculiX 1,263.5 Hz).
  solver: '솔버',
  mesh_order: '요소 차수',
  settings_from: '해석 설정 출처',
  damping_ratio: '감쇠비',
  // 모달 · 랜덤의 **찾을 주파수 범위**와 그 출처 — 랜덤의 가진 대역(PSD 표)과는 다른 칸이다.
  frequency_range_hz: '찾을 주파수 범위',
  range_from: '범위 출처',
  mode_search: '범위 찾기',
  psd_band_hz: '가진 대역 (PSD 표)',
  psd_inputs: '입력 PSD',
  input_grms: '입력 Grms',
  probe_grms: '측정점 가속도 1σ',
  max_displacement_1sigma_mm: '최대 1σ 변위',
  ansys_version: 'Ansys 버전',
  // **CAD 가 선언한 계**로 세션을 세운다(2026-09-24). 숫자가 어느 계로 들어갔는지는 값을
  // 보고 알 수 없어서 — 틀리면 그럴듯한 값이 나온다 — 여기에 적어 둔다.
  unit_system: '단위계',
  solver_unit_system: '솔버 단위계',
  // **무슨 물성으로 돌았나.** 재료를 훑는 DOE 에서는 이것이 결과의 절반이다 — 「CAD 가 보낸
  // 값으로 돈 것인지」 를 값만 보고는 알 수 없다.
  material: '물성',
  material_from: '물성 출처',
  // 탄성계수를 어느 온도의 값으로 썼나 — 온도 표에서 22 °C 에 가장 가까운 점(CompCore v0.29.0 부터 온도가 실린다).
  material_temperature: '물성 온도',
  // 소성(CompCore ②) — 이선형 · 다선형, 표가 MatNexus 카드에서 왔으면 그 출처와 두 E(풀이는 물성 E).
  material_model: '재료 모델',
  material_card: '소성 카드',
  material_warning: '물성 경고',
  load_steps: '하중 단계',
  // **단위가 어긋났나** — 덱에 실제로 쓴 물성, 솔버가 셈한 질량(`.dat`), 형상 부피를 CAD 와 견준 경고.
  // 고유진동수가 오류 없이 10³ 배 틀리는 사고를 숫자로 가린다(운영 2026-11-17).
  deck_materials: '덱 물성',
  solver_mass_kg: '솔버 질량',
  size_warning: '형상 크기 경고',
  mass_warning: '질량 경고',
  youngs_modulus_gpa: '탄성계수',
  density_kg_m3: '밀도',
  // 정적 · 조화는 모드가 아니라 **크기**를 낸다. 단위는 결과 카드가 붙여 준다.
  max_displacement: '최대 변형',
  max_von_mises: '최대 상당응력',
  frequency_points: '주파수 점',
  peak_hz: '봉우리 주파수',
  peak_displacement: '봉우리 변위',
  // 메시 수렴 점검이 줄일 기준 — 비면 Mechanical 기본 크기로 돌았다.
  element_size_mm: '전역 요소 크기',
  contact_pairs: '비선형 접촉',
  large_deflection: '큰 변형',
  large_deflection_from: '큰 변형 출처',
  // CompCore 의 파트별 설정 — 무엇을 빼고 무엇을 굳혀 풀었나. 안 보이면 「질량이 왜 줄었지」 ·
  // 「주파수가 왜 올랐지」 를 설명할 길이 없다.
  rigid_bodies: '강체 파트',
  suppressed_bodies: '해석 제외 파트',
  shell_bodies: '쉘 파트',
  mass_kg: '질량',
  // 지그와 부품은 같은 바디다 — 전체 질량에 강체 지그까지 든다. 바디마다 보여야 시편이 몇 g 인지 안다.
  mass_by_body: '바디별 질량',
  constrained_regions: '구속 영역',
  shape_reused: '형상 캐시',
  recipe: '해석 종류',
  mode_shapes: '모드 그림',
  tidied_bytes: '정리한 중간 파일',
  // **메시를 사람이 준 것과 다르게 만든 것** — 겹침 · 틈을 붙였다 · 곡률 크기로 다시 만들었다 ·
  // 뒤집힌 2차 요소를 폈다(CalculiX 경로). 안 보이면 「요소 수가 왜 늘었지」 를 설명할 길이 없다.
  boolean_tolerance_mm: '형상 맞춤 허용오차',
  mesh_repairs: '메시 보정',
  mesh_quality: '요소 품질',
  // 바디마다 요소 차수가 다르면(파트 설정) 요소 차수 칸은 「바디마다 다름」 이고 여기에 바디별로.
  mesh_order_by_body: '바디별 요소 차수',
  // **바디를 어떻게 붙였나**(CalculiX) — 따로 메시하고 구속식(*TIE)으로 묶었나, 절점을 공유했나.
  // 쌍마다 몇 절점이 묶였는지가 그 아래다 — 0 이면 그 바디는 떨어진 채 풀렸다.
  bonding: '본딩 방식',
  bonded_pairs: '쌍별 연결',
  bond_warning: '연결 경고',
  // 접촉을 선언했으면 선언한 쌍만 묶는다 — 맞닿았는데 접촉이 없는 쌍은 떨어진 채로 풀렸다.
  // CompCore 의 경고와 같은 말(「접촉 미정의: 인접 바디」, CompCore v0.26.0 다음 판).
  unbonded_touching: '접촉 미정의: 인접 바디',
  // 못 건 조건 · 다르게 푼 조건(붙은 것으로 · 미끄러지게)과 그 까닭.
  conditions_skipped: '조건 처리 알림',
  // 결과를 읽고 단 경고 — 모달이면 0 Hz 모드(움직인 바디 · 그럴 만한 까닭).
  result_warning: '결과 경고',
  // 정적은 메모리가 모자랄 것 같으면 반복 솔버로 푼다 — 무엇으로 풀었고 얼마를 어림했나.
  linear_solver: '선형 솔버',
  memory_estimate_mb: '메모리 어림',
  memory_warning: '메모리 경고',
  solver_retry: '다시 푼 까닭',
}

/** 작업 상세 맨 위에 띠로 보이는 요약 경고 — 단위가 어긋나면 결과 숫자 전체가 틀린다. */
const UNIT_WARNINGS = ['size_warning', 'mass_warning', 'material_warning'] as const

/** 한 줄을 다 쓰고 접어 보이는 요약 칸 — 바디마다 늘어서는 값. */
const WIDE_SUMMARY = new Set([
  'mass_by_body',
  'deck_materials',
  'material_model',
  'material_card',
  'material_warning',
  'size_warning',
  'mass_warning',
  'mesh_repairs',
  'mesh_order_by_body',
  'memory_warning',
  'solver_retry',
  'bonded_pairs',
  'bond_warning',
  'unbonded_touching',
  'conditions_skipped',
  'result_warning',
])

/** 요약 묶음 — 메시 · 모델 · 해석 · 실행. 모르는 열쇠는 「기타」 로. */
const SUMMARY_GROUPS: [string, string[]][] = [
  [
    '메시',
    [
      'nodes',
      'elements',
      'element_size_mm',
      'mesh_order',
      'mesh_order_by_body',
      'mesh_quality',
      'contact_pairs',
      'bonding',
      'bonded_pairs',
      'bond_warning',
      'unbonded_touching',
      'boolean_tolerance_mm',
      'mesh_repairs',
    ],
  ],
  [
    '모델',
    [
      'bodies',
      'mass_kg',
      'mass_by_body',
      'material',
      'material_from',
      'material_temperature',
      'material_model',
      'material_card',
      'material_warning',
      'deck_materials',
      'solver_mass_kg',
      'size_warning',
      'mass_warning',
      'youngs_modulus_gpa',
      'density_kg_m3',
      'rigid_bodies',
      'suppressed_bodies',
      'shell_bodies',
      'constrained_regions',
      'conditions_skipped',
      'unit_system',
      'input_bytes',
    ],
  ],
  [
    '해석',
    [
      'recipe',
      'large_deflection',
      'large_deflection_from',
      'load_steps',
      'settings_from',
      'modes',
      'modes_requested',
      'rigid_body_modes',
      'first_elastic_hz',
      'result_warning',
      'frequency_range_hz',
      'range_from',
      'mode_search',
      'psd_band_hz',
      'psd_inputs',
      'input_grms',
      'probe_grms',
      'max_displacement_1sigma_mm',
      'damping_ratio',
      'frequency_points',
      'max_displacement',
      'max_von_mises',
      'peak_hz',
      'peak_displacement',
      'mode_shapes',
    ],
  ],
  [
    '실행',
    [
      'solver',
      'ansys_version',
      'solver_unit_system',
      'linear_solver',
      'solver_seconds',
      'memory_estimate_mb',
      'memory_warning',
      'solver_retry',
      'shape_reused',
      'tidied_bytes',
    ],
  ],
]

function groupedSummary(rows: [string, unknown][]): [string, [string, unknown][]][] {
  const known = new Set(SUMMARY_GROUPS.flatMap(([, keys]) => keys))
  const byKey = new Map(rows)
  const out: [string, [string, unknown][]][] = SUMMARY_GROUPS.map(([group, keys]) => [
    group,
    keys.filter((key) => byKey.has(key)).map((key) => [key, byKey.get(key)] as [string, unknown]),
  ])
  out.push(['기타', rows.filter(([key]) => !known.has(key))])
  return out.filter(([, items]) => items.length > 0)
}

const TABS: DetailTab[] = ['result', 'progress', 'checks', 'files']

function shownSummary(key: string, value: unknown): string {
  if (value == null) return '—'
  if ((key === 'input_bytes' || key === 'tidied_bytes') && typeof value === 'number') return shownSize(value)
  if (key === 'first_elastic_hz' && typeof value === 'number') return `${value.toFixed(2)} Hz`
  if (key === 'peak_hz' && typeof value === 'number') return `${value.toFixed(1)} Hz`
  if (key === 'solver_seconds' && typeof value === 'number') return `${value.toFixed(1)}초`
  if (key === 'material_from' || key === 'settings_from' || key === 'large_deflection_from' || key === 'range_from')
    return value === 'cad' ? 'CAD 가 보낸 값' : '사람이 넣은 값'
  if (key === 'solver') return SOLVER_LABELS[String(value)] ?? String(value)
  if (key === 'damping_ratio' && typeof value === 'number') return `${(value * 100).toFixed(1)}%`
  if (key === 'youngs_modulus_gpa' && typeof value === 'number') return `${value} GPa`
  if (key === 'max_displacement_1sigma_mm' && typeof value === 'number') return `${value} mm`
  if ((key === 'element_size_mm' || key === 'boolean_tolerance_mm') && typeof value === 'number')
    return `${value} mm`
  if (key === 'linear_solver') return value === 'iterative' ? '반복 (ITERATIVE CHOLESKY)' : '직접 (SPOOLES)'
  if (key === 'bonding') return value === 'tie' ? '따로 메시 · 구속식 묶음 (*TIE)' : '절점 공유'
  if (key === 'mesh_order')
    return ({ quadratic: '2차', linear: '1차', mixed: '바디마다 다름' } as Record<string, string>)[String(value)] ?? String(value)
  if (key === 'memory_estimate_mb' && typeof value === 'number') return `${value.toLocaleString()} MB`
  if (key === 'contact_pairs') return value ? '있음' : '없음'
  if (key === 'large_deflection') return value ? '켬 (기하 비선형)' : '끔'
  if (key === 'shape_reused') return value ? '다시 씀' : '새로 만듦'
  if ((key === 'mass_kg' || key === 'solver_mass_kg') && typeof value === 'number') return shownMass(value)
  if (key === 'mass_by_body' && value && typeof value === 'object')
    return Object.entries(value as Record<string, unknown>)
      .map(([name, kg]) => `${name} ${typeof kg === 'number' ? shownMass(kg) : '—'}`)
      .join(' · ')
  if (Array.isArray(value)) return value.length === 0 ? '—' : value.join(' · ')
  if (key === 'density_kg_m3' && typeof value === 'number')
    return `${value.toLocaleString()} kg/m³`
  // 버전 번호는 자릿수를 구분하지 않는다 — 252 가 「252」 여야지 「252」 에 쉼표가 붙으면 안 된다.
  if (key === 'ansys_version') return String(value)
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

/** 검증 탭이 읽은 것. */
interface Checked {
  convergence?: Convergence
  measurements?: Measurement[]
}

/**
 * **작업마다 새로 띄운다.** 같은 주소 꼴(`/simulations/:id`)에서 「앞선 시도」 · 「원래 작업」 으로
 * 넘어가면 React 는 화면을 그대로 두고 id 만 바꾼다 — 그러면 앞 작업의 정리 알림 · 오류 · 늦게 온
 * 응답이 새 작업 위에 남고, 새 작업을 못 받으면 앞 작업이 오류 없이 그대로 보였다(그 위의
 * 취소 · 정리 단추는 새 id 에 건다). 열쇠로 묶어 상태 전부를 작업과 함께 버린다(2026-10-05 리뷰).
 */
/** STE 상태 중 Slurm 낱말이 아닌 것 — 이 서버가 적는다(요청서 E-4). */
const STE_STATE_WORDS: Record<string, string> = {
  CANCEL_REQUESTED: '취소를 청함(멈춘 것은 못 봄)',
}

/** STE 잡 한 줄 — 번호 · 끝난 상태 · 대기 · 실행 · 청한 메모리(요청서 E-1 의 단계 기록). 이
 * 서버가 취소했으면 그렇다고, 이미 끝나 있어 결과를 버렸으면 그렇다고 붙인다(E-4). ccx 지문이
 * 이 서버와 다르면 그것도(E-5). */
function steJobLine(job: Record<string, unknown>): string {
  const seconds = (value: unknown) => (typeof value === 'number' ? `${Math.round(value)}초` : '—')
  const state = String(job.ste_state ?? '제출함')
  const parts = [`STE 잡 ${String(job.ste_job_id ?? '?')}`, STE_STATE_WORDS[state] ?? state]
  if (job.canceled_by === 'server') parts.push('이 서버가 취소함')
  if (job.discarded === true) parts.push('결과 버림')
  // 고르기 전 점검을 지나도 STE 앱이 그사이 바뀔 수 있다(E-5) — 결과 끝자리가 갈릴 수 있다.
  if (job.ccx_matches_local === false) parts.push('⚠ ccx 지문이 이 서버와 다름')
  parts.push(`대기 ${seconds(job.queued_s)} · 실행 ${seconds(job.run_s)}`)
  if (typeof job.mem_gb === 'number') parts.push(`메모리 ${job.mem_gb} GB`)
  if (typeof job.max_rss_mb === 'number') parts.push(`최대 ${Math.round(job.max_rss_mb)} MB`)
  return parts.join(' · ')
}

export default function SimulationDetailPage() {
  const { id = '' } = useParams()
  return <SimulationDetail key={id} id={id} />
}

function SimulationDetail({ id }: { id: string }) {
  const initial = useResource(() => simulationApi.get(id), [id])
  // 폴링이 갱신하는 사본. 첫 응답은 `initial` 에서, 그 뒤는 `/status` 에서.
  const [live, setLive] = useState<Simulation | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [busy, setBusy] = useState(false)
  const { user } = useAuth()

  const simulation = live ?? initial.data
  const finished = simulation ? FINAL_STATUSES.has(simulation.status) : true
  const done = simulation?.status === 'done'
  // 결과는 한 번 받아 한눈에 보기 줄과 결과 탭이 함께 쓴다.
  const loaded = useSimulationResult(id, simulation?.status ?? '')

  // **어느 탭을 여나** — 주소에 고른 것이 있으면 그것(못 여는 탭이면 무시), 없으면 상태가 정한다:
  // 끝났으면 결과, 아니면 진행 · 모델. 그래서 도는 동안 보던 화면이 끝나는 순간 결과로 넘어간다.
  const [params, setParams] = useSearchParams()
  const asked = params.get('tab') as DetailTab | null
  const usable = (one: DetailTab) => done || (one !== 'result' && one !== 'checks')
  const tab: DetailTab =
    asked && TABS.includes(asked) && usable(asked) ? asked : done ? 'result' : 'progress'
  function setTab(next: DetailTab) {
    const after = new URLSearchParams(params)
    after.set('tab', next)
    setParams(after, { replace: true })
  }

  // **검증 탭이 새로 읽은 값** — 한눈에 보기의 배지가 그것을 따른다. 배지는 처음 한 번만 읽어서,
  // 점검을 걸거나 실측을 올리고 돌아와도 옛 판정이 남아 있었다(2026-10-05 리뷰).
  const [latest, setLatest] = useState<Checked>({})
  const reportConvergence = useCallback(
    (next: Convergence) => setLatest((was) => ({ ...was, convergence: next })),
    [],
  )
  const reportMeasurements = useCallback(
    (next: Measurement[]) => setLatest((was) => ({ ...was, measurements: next })),
    [],
  )

  useEffect(() => {
    if (finished || !id) return
    let cancelled = false
    const timer = setInterval(async () => {
      try {
        const next = await simulationApi.status(id)
        if (!cancelled) setLive(next)
      } catch (caught) {
        // 잠깐의 네트워크 끊김이면 다음 틱에 다시 — 오류를 화면에 쌓지 않는다.
        if (!cancelled && caught instanceof ApiError && caught.status === 404) {
          setError(caught)
        }
      }
    }, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [id, finished])

  async function cancel() {
    setBusy(true)
    setError(null)
    try {
      setLive(await simulationApi.cancel(id))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    } finally {
      setBusy(false)
    }
  }

  const [tidied, setTidied] = useState<string | null>(null)

  async function tidy() {
    setBusy(true)
    setError(null)
    try {
      const done = await simulationApi.tidy(id)
      setTidied(
        `중간 파일 ${done.files}개 · ${(done.bytes_freed / 1024 / 1024).toFixed(1)}MB 를 정리했습니다.`,
      )
      setLive(await simulationApi.get(id))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    } finally {
      setBusy(false)
    }
  }

  async function setPublished(next: boolean) {
    setError(null)
    setLive(await (next ? simulationApi.publish(id) : simulationApi.unpublish(id)))
  }

  const navigate = useNavigate()
  const [removing, setRemoving] = useState(false)

  async function retry(solveOn?: SolveOn) {
    setBusy(true)
    setError(null)
    try {
      setLive(await simulationApi.retry(id, solveOn))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    } finally {
      setBusy(false)
    }
  }

  async function download(artifact: Artifact) {
    setError(null)
    try {
      await simulationApi.download(id, artifact)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    }
  }

  const [bundling, setBundling] = useState(false)

  /** **산출물 전부를 ZIP 하나로** — 서버가 묶는다(솔버 결과는 수백 MB 라 시간이 걸린다). */
  async function downloadAll() {
    if (!simulation) return
    setBundling(true)
    setError(null)
    try {
      await simulationApi.downloadAll(id, `${simulation.name}_파일.zip`)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('알 수 없는 오류'))
    } finally {
      setBundling(false)
    }
  }

  if (initial.error && !simulation) {
    return (
      <div className="space-y-6">
        <PageHeader title="해석" back={{ to: '/simulations', label: '해석' }} />
        <ErrorNotice error={initial.error} />
      </div>
    )
  }
  if (!simulation) return null

  const summary = Object.entries(simulation.summary ?? {})
  const totalBytes = simulation.artifacts.reduce((sum, one) => sum + (one.size_bytes ?? 0), 0)
  // **남의 게시 결과는 읽기만 한다** — 바꾸는 단추는 건 사람과 시스템 관리자에게만.
  const mine = ownsWork(user, simulation.requested_by_id)

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {simulation.name}
            <StatusBadge kind="simulation" value={simulation.status} />
            {simulation.published_at && <PublishedBadge />}
          </span>
        }
        description={
          <>
            {RECIPE_LABELS[simulation.recipe] ?? simulation.recipe} ·{' '}
            {/* **스펙에서 읽는다** — 요약의 솔버 도장은 CalculiX 만 찍고, 끝나기 전에는 없다. */}
            {SOLVER_LABELS[solverOf(simulation.spec)] ?? solverOf(simulation.spec)} ·{' '}
            {/* **어디서 풀었나**(요청서 E-2) — 이 서버가 기본이라 STE 일 때만 적는다. */}
            {solveOnOf(simulation.spec) === 'ste' && `${SOLVE_ON_LABELS.ste} · `}
            {simulation.owner_workspace_name ?? '전역'} · {simulation.requested_by_name ?? '—'} ·{' '}
            {shownDateTime(simulation.created_at)} · 소요{' '}
            {shownDuration(simulation.started_at, simulation.finished_at)}
            {simulation.attempts > 1 && ` · ${simulation.attempts}번째 시도`}
            {/* **어느 워커가 집었나** — 서버 화면의 워커 표와 잇는 끈이다(같은 `호스트:pid`). */}
            {simulation.worker_id && ` · 워커 ${simulation.worker_id}`}
            {simulation.published_at &&
              ` · ${simulation.published_by_name ?? '—'} 님이 ${shownDateTime(simulation.published_at)}에 게시`}
            {!mine && ' · 다른 사람의 결과라 읽기만 합니다'}
          </>
        }
        // 남의 게시 결과면 공용 작업공간으로 돌아간다 — 개인 작업 목록에는 없다.
        back={backOf(simulation, mine)}
        actions={
          <>
            {/* **끝난 작업만 게시한다** — 실패 · 도는 중인 결과는 남이 믿고 쓸 수 없다. */}
            {mine && simulation.status === 'done' && (
              <PublishControl
                published={Boolean(simulation.published_at)}
                subject="이 작업"
                onPublish={() => setPublished(true)}
                onUnpublish={() => setPublished(false)}
                disabled={busy}
              />
            )}
            {/* **끝나지 않은 작업만 멈출 수 있다** — 끝난 것은 되돌릴 것이 없다. */}
            {mine && !finished && (
              <Button variant="outline" size="sm" onClick={cancel} disabled={busy}>
                <Square className="size-4" />
                취소
              </Button>
            )}
            {/* 다시 가져와 대신한 작업이 있으면 그쪽에서 다시 건다 — 서버도 막는다(SIMULATIONS-0031). */}
            {mine && (simulation.status === 'failed' || simulation.status === 'canceled') && !replacedBy(simulation) && (
              <Button size="sm" onClick={() => void retry()} disabled={busy}>
                <RotateCcw className="size-4" />
                다시 실행
              </Button>
            )}
            {/* **STE 가 안 돼 실패했으면 이 서버에서 다시** — 서버는 몰래 바꾸지 않는다(요청서 E-2). */}
            {mine &&
              simulation.status === 'failed' &&
              solveOnOf(simulation.spec) === 'ste' &&
              STE_FAILURES.has(simulation.error_code ?? '') &&
              !replacedBy(simulation) && (
                <Button variant="outline" size="sm" onClick={() => void retry('local')} disabled={busy}>
                  <RotateCcw className="size-4" />
                  이 서버에서 다시 풀기
                </Button>
              )}
            {mine && finished && (
              <Button variant="outline" size="sm" onClick={tidy} disabled={busy}>
                <Eraser className="size-4" />
                중간 파일 정리
              </Button>
            )}
            {/* **도는 작업은 지우지 않는다** — 워커가 쓰는 폴더를 지우게 된다. 먼저 멈춘다. */}
            {mine && (finished || simulation.status === 'queued') && (
              <Button variant="outline" size="sm" onClick={() => setRemoving(true)} disabled={busy}>
                <Trash2 className="size-4" />
                삭제
              </Button>
            )}
          </>
        }
      />

      <ConfirmDialog
        open={removing}
        title="작업 삭제"
        description={<RemoveNotice simulation={simulation} totalBytes={totalBytes} />}
        confirmLabel="삭제"
        destructive
        onConfirm={async () => {
          await simulationApi.remove(id)
          navigate(afterRemove(simulation), { replace: true })
        }}
        onClose={() => setRemoving(false)}
      />

      <ErrorNotice error={error} />

      <SourceLine simulation={simulation} />

      {tidied && (
        <Alert>
          <AlertTitle>정리했습니다</AlertTitle>
          <AlertDescription>
            {tidied} 결과(결과 요약 · 그림)와 입력은 그대로 남습니다. 정리한 파일이 다시 필요하면
            작업을 다시 실행해야 합니다.
          </AlertDescription>
        </Alert>
      )}

      {simulation.status === 'queued' && simulation.queue && (
        <QueueNotice queue={simulation.queue} />
      )}

      {simulation.status === 'failed' && (
        <Alert variant="destructive">
          <AlertTitle>
            실패 — <span className="font-mono">{simulation.error_code}</span>
          </AlertTitle>
          <AlertDescription>
            <p>{FAILURE_LABELS[simulation.error_code ?? ''] ?? simulation.error_code}</p>
            {simulation.error_message && <p className="mt-1">{simulation.error_message}</p>}
          </AlertDescription>
        </Alert>
      )}

      {/* **단위 경고는 맨 위에** — 형상 크기 · 질량이 어긋나면 결과 숫자 전체가 10³ 배씩 틀린다. */}
      {UNIT_WARNINGS.map((key) => {
        const said = (simulation.summary ?? {})[key]
        return typeof said === 'string' && said ? (
          <p
            key={key}
            role="alert"
            className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
          >
            {SUMMARY_LABELS[key]}: {said}
          </p>
        ) : null
      })}

      {/* **한눈에 보기** — 대표 숫자와 「이 숫자를 믿어도 되나」. 누르면 그 탭으로. */}
      <ResultGlance
        simulation={simulation}
        result={loaded.result}
        onJump={setTab}
        convergence={latest.convergence}
        measurements={latest.measurements}
      />

      <Tabs value={tab} onValueChange={(next) => setTab(next as DetailTab)}>
        <TabsList variant="line">
          <TabsTrigger value="result" disabled={!done} title={done ? undefined : '끝나면 나옵니다'}>
            결과
          </TabsTrigger>
          <TabsTrigger value="progress">진행 · 모델</TabsTrigger>
          <TabsTrigger value="checks" disabled={!done} title={done ? undefined : '끝나면 나옵니다'}>
            검증
          </TabsTrigger>
          <TabsTrigger value="files">파일</TabsTrigger>
        </TabsList>

        <TabsContent value="result" className="space-y-6 pt-4">
          {/* 결과 요약은 **끝난 뒤에 한 번만** 받는다 — 한눈에 보기 줄과 같은 것을 쓴다. */}
          <ResultPanel
            simulationId={id}
            status={simulation.status}
            artifacts={simulation.artifacts}
            loaded={loaded}
          />
        </TabsContent>

        <TabsContent value="progress" className="space-y-6 pt-4">
          <section className="space-y-2">
            <h2 className="text-sm font-medium">단계</h2>
            {/* **가로 진행 막대** — 어디까지 왔고 어디서 멈췄나를 한 줄에. */}
            <ol className="grid gap-2 md:grid-cols-4">
              {simulation.stages.map((stage: Stage, index) => (
                <li
                  key={stage.name}
                  className={`space-y-1 rounded-md border p-3 ${stage.status === 'failed' ? 'border-destructive' : ''}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-muted-foreground text-xs">{index + 1}</span>
                    <StatusBadge kind="stage" value={stage.status} />
                  </div>
                  <p className="font-medium">{STAGE_LABELS[stage.name] ?? stage.name}</p>
                  {stage.started_at && (
                    <p className="text-muted-foreground text-xs">
                      {shownDateTime(stage.started_at)} · {shownDuration(stage.started_at, stage.finished_at)}
                    </p>
                  )}
                  {stage.detail && <p className="text-muted-foreground text-sm">{stage.detail}</p>}
                  {stage.error_message && <p className="text-destructive text-sm">{stage.error_message}</p>}
                  {/* **STE 에 낸 잡** — 재시도 · 모드 찾기면 여럿이다. STE 화면에서 찾을 번호다. */}
                  {(stage.ste_jobs ?? []).length > 0 && (
                    <ul className="text-muted-foreground mt-1 space-y-0.5 text-xs">
                      {(stage.ste_jobs ?? []).map((job) => (
                        <li key={String(job.ste_job_id)}>{steJobLine(job)}</li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          </section>

          {summary.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-medium">요약</h2>
              {/* **묶어서 보인다** — 키 스무 개를 한 판에 늘어놓으면 「절점이 몇이었지」 를 찾기 어렵다. */}
              <div className="grid gap-3 md:grid-cols-2">
                {groupedSummary(summary).map(([group, rows]) => (
                  <div key={group} className="rounded-md border p-3">
                    <h3 className="text-muted-foreground mb-2 text-xs font-medium">{group}</h3>
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                      {rows.map(([key, value]) => (
                        // **바디별 질량은 한 줄을 다 쓰고 접어 보인다** — 잘라 두면 「시편」 다음 몇 개만 보인다.
                        <div key={key} className={WIDE_SUMMARY.has(key) ? 'col-span-2 min-w-0' : 'min-w-0'}>
                          <dt className="text-muted-foreground text-xs">{SUMMARY_LABELS[key] ?? key}</dt>
                          <dd
                            className={WIDE_SUMMARY.has(key) ? 'font-medium break-words' : 'truncate font-medium'}
                            title={shownSummary(key, value)}
                          >
                            {shownSummary(key, value)}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* **조건을 조용히 무시하지 않는다** — 무엇을 반영하고 무엇을 넘겼는지 그대로 보인다. */}
          <ConditionList conditions={simulation.conditions} />
        </TabsContent>

        <TabsContent value="checks" className="space-y-8 pt-4">
          {/* **이 숫자를 믿어도 되나** — 실측과 견주고, 메시에 얼마나 기대는지 본다. */}
          <MeasurementsPanel
            simulationId={id}
            status={simulation.status}
            readOnly={!mine}
            onData={reportMeasurements}
          />
          <ConvergencePanel
            simulationId={id}
            status={simulation.status}
            solver={solverOf(simulation.spec)}
            readOnly={!mine}
            onData={reportConvergence}
          />
        </TabsContent>

        <TabsContent value="files" className="space-y-6 pt-4">
          <section className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-sm font-medium">산출물</h2>
              {simulation.artifacts.length > 0 && (
                <Button variant="outline" size="sm" onClick={downloadAll} disabled={bundling}>
                  <Download className="size-4" />
                  {bundling ? '묶는 중…' : `전체 다운로드 (${shownSize(totalBytes)})`}
                </Button>
              )}
            </div>
            {simulation.artifacts.length === 0 ? (
              <EmptyState title="산출물이 없습니다" hint="단계가 진행되면 여기에 표시됩니다." />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>종류</TableHead>
                    <TableHead>파일</TableHead>
                    <TableHead>단계</TableHead>
                    <TableHead>크기</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {simulation.artifacts.map((artifact: Artifact) => (
                    <TableRow key={artifact.id}>
                      <TableCell>{ARTIFACT_LABELS[artifact.kind] ?? artifact.kind}</TableCell>
                      <TableCell className="font-mono text-xs">{artifact.filename}</TableCell>
                      <TableCell>{STAGE_LABELS[artifact.stage] ?? artifact.stage}</TableCell>
                      <TableCell>{shownSize(artifact.size_bytes)}</TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => download(artifact)}>
                          <Download className="size-4" />
                          다운로드
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </section>

          <details className="rounded-md border">
            <summary className="cursor-pointer px-4 py-2 text-sm font-medium">스펙</summary>
            <pre className="text-muted-foreground overflow-x-auto px-4 pb-3 text-xs">
              {JSON.stringify(simulation.spec, null, 2)}
            </pre>
          </details>
        </TabsContent>
      </Tabs>
    </div>
  )
}

/**
 * **이 작업은 어디서 왔나** — DOE 설계점이면 그 스터디로, 메시 수렴 점검이면 원래 작업으로
 * 가는 길. 없으면 설계점 하나를 보다가 같은 스터디의 다른 점과 견줄 길을 잃는다.
 */
/**
 * **앞선 시도** — 실패 · 취소한 점을 CompCore 가 고쳐 다시 내보낸 폴더에서 다시 가져오면, 새 작업이
 * 옛 작업을 가리킨다(`source_meta.previous`). 옛 작업은 지우지 않는다 — 왜 실패했는지 거기서 읽는다.
 */
/** 이 시도를 대신해 다시 가져온 작업의 id — 없으면 null. */
function replacedBy(simulation: Simulation): string | null {
  const value = (simulation.source_meta ?? {})['superseded_by']
  return typeof value === 'string' && value ? value : null
}

/**
 * 같은 DOE 의 **이웃 설계점으로 ◀ ▶** — 200점짜리 DOE 에서 점마다 목록으로 돌아갔다 오지 않게.
 * 그 DOE 를 읽어 점 번호 차례로 앞뒤를 찾는다(못 읽으면 단추를 안 그린다).
 */
function PointNav({ studyId, current }: { studyId: string; current: string }) {
  const study = useResource(() => simulationApi.study(studyId), [studyId])
  const points = [...(study.data?.points ?? [])].sort((a, b) => a.number - b.number)
  const at = points.findIndex((one) => one.simulation_id === current)
  if (at < 0) return null
  const before = points[at - 1]
  const after = points[at + 1]
  const tag = (number: number) => `p${String(number).padStart(4, '0')}`
  return (
    <span className="flex items-center gap-1 text-xs">
      {before ? (
        <Link to={`/simulations/${before.simulation_id}`} className="hover:text-foreground flex items-center" aria-label={`이전 설계점 ${tag(before.number)}`}>
          <ChevronLeft className="size-3.5" />
          {tag(before.number)}
        </Link>
      ) : null}
      <span>
        {at + 1}/{points.length}
      </span>
      {after ? (
        <Link to={`/simulations/${after.simulation_id}`} className="hover:text-foreground flex items-center" aria-label={`다음 설계점 ${tag(after.number)}`}>
          {tag(after.number)}
          <ChevronRight className="size-3.5" />
        </Link>
      ) : null}
    </span>
  )
}

function PreviousAttempts({ meta }: { meta: Record<string, unknown> }) {
  const previous = Array.isArray(meta.previous) ? meta.previous.map(String) : []
  // **모드 수만 바꿔 다시 건 것**(DOE 의 「모드 수 바꿔 다시 걸기」)은 다시 가져온 것과 다르다 —
  // 같은 입력으로 모드 수만 바꿨다고 말한다.
  const rerun = (meta.rerun ?? null) as { modes?: number; from_modes?: number | null } | null
  const rerunTo = typeof meta.rerun_to === 'number' ? meta.rerun_to : null
  // **옛 시도에서는 새 작업으로 간다** — 실패 목록에서 옛 시도를 열면 이미 다시 가져왔다는 것을
  // 알 길이 없었다.
  const replaced = typeof meta.superseded_by === 'string' && meta.superseded_by ? meta.superseded_by : null
  if (replaced) {
    return (
      <>
        {' '}
        · {rerunTo != null ? `모드 ${rerunTo}개로 다시 걸음` : '다시 가져옴'} —{' '}
        <Link to={`/simulations/${replaced}`} className="font-medium hover:underline">
          새 작업 보기
        </Link>
      </>
    )
  }
  if (previous.length === 0) return null
  return (
    <>
      {' '}
      ·{' '}
      {rerun?.modes != null
        ? `모드 ${rerun.from_modes ?? '?'} → ${rerun.modes}개로 다시 걸음`
        : '다시 가져옴'}{' '}
      — 앞선 시도{' '}
      {previous.map((id, index) => (
        <span key={id}>
          {index > 0 && ', '}
          <Link to={`/simulations/${id}`} className="font-medium hover:underline">
            {previous.length > 1 ? `${index + 1}` : '보기'}
          </Link>
        </span>
      ))}
    </>
  )
}

/** **무엇이 사라지는지 적는다** — 게시한 결과면 남의 화면에서도, DOE 점이면 앞선 시도까지. */
function RemoveNotice({ simulation, totalBytes }: { simulation: Simulation; totalBytes: number }) {
  return (
    <div className="space-y-2">
      <p>
        「{simulation.name}」 과 그 작업 폴더(결과 · 그림 · 중간 파일
        {totalBytes > 0 && ` ${shownSize(totalBytes)}`})를 지웁니다. 메시 수렴
        점검 수준과 이 작업에 올린 실측도 함께 사라집니다. 되돌릴 수 없습니다.
      </p>
      {simulation.published_at && <p>게시된 결과라 다른 사람의 화면에서도 사라집니다.</p>}
      {simulation.source_kind === 'doe_point' && (
        <p>DOE 설계점이면 그 점의 앞선 시도(다시 가져오기 전의 작업)도 함께 지웁니다.</p>
      )}
    </div>
  )
}

/** 지운 뒤 갈 곳 — DOE 설계점이면 그 DOE 로(남은 점을 보러 왔을 것이다), 아니면 목록으로. */
function afterRemove(simulation: Simulation): string {
  const meta = (simulation.source_meta ?? {}) as Record<string, unknown>
  const study = String(meta.study_id ?? meta.study_name ?? '')
  return simulation.source_kind === 'doe_point' && study
    ? `/simulations/studies/${encodeURIComponent(study)}`
    : '/simulations'
}

/**
 * 돌아갈 곳 — **DOE 설계점이면 그 DOE**(설계점은 「해석」 목록에 따로 서지 않는다, ADR 0014),
 * 아니면 「해석」 목록(남의 게시 결과면 공용 작업공간).
 */
function backOf(simulation: Simulation, mine: boolean): { to: string; label: string } {
  const meta = (simulation.source_meta ?? {}) as Record<string, unknown>
  const study = String(meta.study_id ?? meta.study_name ?? '')
  if (simulation.source_kind === 'doe_point' && study) {
    return { to: `/simulations/studies/${encodeURIComponent(study)}`, label: String(meta.study_name ?? 'DOE') }
  }
  return mine ? { to: '/simulations', label: '개인 작업' } : { to: listPath('published'), label: '공용 작업공간' }
}

function SourceLine({ simulation }: { simulation: Simulation }) {
  const meta = (simulation.source_meta ?? {}) as Record<string, unknown>
  if (simulation.source_kind === 'doe_point') {
    const study = String(meta.study_id ?? meta.study_name ?? '')
    const params = Object.entries((meta.params ?? {}) as Record<string, unknown>)
      .map(([name, value]) => `${name} ${String(value)}`)
      .join(' · ')
    if (!study) return null
    return (
      <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        {/* **어느 DOE 의 몇 번 점인가** — 경로로 적는다(DOE › p0003). */}
        <nav aria-label="DOE 경로">
          <Link to={`/simulations/studies/${encodeURIComponent(study)}`} className="font-medium hover:underline">
            {String(meta.study_name ?? study)}
          </Link>{' '}
          › p{String(meta.point ?? 0).padStart(4, '0')}
          {params && ` (${params})`}
          <PreviousAttempts meta={meta} />
        </nav>
        <PointNav studyId={study} current={simulation.id} />
      </div>
    )
  }
  if (simulation.source_kind === 'design') {
    // 설계 하나(CompCore 「해석용으로 내보내기」) — 스터디가 아니라 링크가 없다. 폴더 이름이 그 설계다.
    return (
      <p className="text-muted-foreground text-sm">
        CAD 설계 <span className="font-medium">{String(meta.study_name ?? '—')}</span>
        <PreviousAttempts meta={meta} />
      </p>
    )
  }
  if (simulation.source_kind === 'mesh_check' && typeof meta.convergence_of === 'string') {
    return (
      <p className="text-muted-foreground text-sm">
        <Link to={`/simulations/${meta.convergence_of}`} className="font-medium hover:underline">
          원래 작업
        </Link>
        의 메시 수렴 점검 — 요소 크기 {String(meta.element_size_mm ?? '—')} mm
      </p>
    )
  }
  return null
}
