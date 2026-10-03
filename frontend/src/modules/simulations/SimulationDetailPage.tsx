/**
 * 해석 작업 상세 — 단계 타임라인 · 요약 · 산출물.
 *
 * 끝나지 않은 작업은 2초마다 `/status` 를 폴링한다. 그 경로만 접근 로그를 비껴간다
 * (`shared/access_log.py`) — 상세 경로를 그대로 폴링하면 로그가 그 한 줄로 찬다.
 */

import { useEffect, useState } from 'react'
import { Download, Eraser, RotateCcw, Square } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { FINAL_STATUSES, simulationApi } from '@/modules/simulations/api'
import type { Artifact, Simulation, Stage } from '@/modules/simulations/api'
import { ConditionList } from '@/modules/simulations/ConditionList'
import { ConvergencePanel } from '@/modules/simulations/ConvergencePanel'
import { MeasurementsPanel } from '@/modules/simulations/MeasurementsPanel'
import { ResultPanel } from '@/modules/simulations/ResultPanel'
import {
  ARTIFACT_LABELS,
  FAILURE_LABELS,
  RECIPE_LABELS,
  SOLVER_LABELS,
  STAGE_LABELS,
  shownDuration,
  shownSize,
  solverOf,
} from '@/modules/simulations/labels'
import { ApiError } from '@/shared/api/client'
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
  ansys_version: 'Ansys 버전',
  // **CAD 가 선언한 계**로 세션을 세운다(2026-09-24). 숫자가 어느 계로 들어갔는지는 값을
  // 보고 알 수 없어서 — 틀리면 그럴듯한 값이 나온다 — 여기에 적어 둔다.
  unit_system: '단위계',
  solver_unit_system: '솔버 단위계',
  // **무슨 물성으로 돌았나.** 재료를 훑는 DOE 에서는 이것이 결과의 절반이다 — 「CAD 가 보낸
  // 값으로 돈 것인지」 를 값만 보고는 알 수 없다.
  material: '물성',
  material_from: '물성 출처',
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
}

function shownSummary(key: string, value: unknown): string {
  if (value == null) return '—'
  if (key === 'input_bytes' && typeof value === 'number') return shownSize(value)
  if (key === 'first_elastic_hz' && typeof value === 'number') return `${value.toFixed(2)} Hz`
  if (key === 'peak_hz' && typeof value === 'number') return `${value.toFixed(1)} Hz`
  if (key === 'solver_seconds' && typeof value === 'number') return `${value.toFixed(1)}초`
  if (key === 'material_from' || key === 'settings_from')
    return value === 'cad' ? 'CAD 가 보낸 값' : '사람이 넣은 값'
  if (key === 'solver') return SOLVER_LABELS[String(value)] ?? String(value)
  if (key === 'damping_ratio' && typeof value === 'number') return `${(value * 100).toFixed(1)}%`
  if (key === 'youngs_modulus_gpa' && typeof value === 'number') return `${value} GPa`
  if (key === 'element_size_mm' && typeof value === 'number') return `${value} mm`
  if (key === 'contact_pairs') return value ? '있음' : '없음'
  if (key === 'density_kg_m3' && typeof value === 'number')
    return `${value.toLocaleString()} kg/m³`
  // 버전 번호는 자릿수를 구분하지 않는다 — 252 가 「252」 여야지 「252」 에 쉼표가 붙으면 안 된다.
  if (key === 'ansys_version') return String(value)
  if (typeof value === 'number') return value.toLocaleString()
  return String(value)
}

export default function SimulationDetailPage() {
  const { id = '' } = useParams()
  const initial = useResource(() => simulationApi.get(id), [id])
  // 폴링이 갱신하는 사본. 첫 응답은 `initial` 에서, 그 뒤는 `/status` 에서.
  const [live, setLive] = useState<Simulation | null>(null)
  const [error, setError] = useState<ApiError | Error | null>(null)
  const [busy, setBusy] = useState(false)

  const simulation = live ?? initial.data
  const finished = simulation ? FINAL_STATUSES.has(simulation.status) : true

  useEffect(() => {
    setLive(null)
  }, [id])

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

  async function retry() {
    setBusy(true)
    setError(null)
    try {
      setLive(await simulationApi.retry(id))
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

  if (initial.error && !simulation) {
    return (
      <div className="space-y-6">
        <PageHeader title="해석 작업" back={{ to: '/simulations', label: '해석 작업' }} />
        <ErrorNotice error={initial.error} />
      </div>
    )
  }
  if (!simulation) return null

  const summary = Object.entries(simulation.summary ?? {})

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {simulation.name}
            <StatusBadge kind="simulation" value={simulation.status} />
          </span>
        }
        description={
          <>
            {RECIPE_LABELS[simulation.recipe] ?? simulation.recipe} ·{' '}
            {/* **스펙에서 읽는다** — 요약의 솔버 도장은 CalculiX 만 찍고, 끝나기 전에는 없다. */}
            {SOLVER_LABELS[solverOf(simulation.spec)] ?? solverOf(simulation.spec)} ·{' '}
            {simulation.owner_workspace_name ?? '전역'} · {simulation.requested_by_name ?? '—'} ·{' '}
            {shownDateTime(simulation.created_at)} · 소요{' '}
            {shownDuration(simulation.started_at, simulation.finished_at)}
            {simulation.attempts > 1 && ` · ${simulation.attempts}번째 시도`}
          </>
        }
        back={{ to: '/simulations', label: '해석 작업' }}
        actions={
          <>
            {/* **끝나지 않은 작업만 멈출 수 있다** — 끝난 것은 되돌릴 것이 없다. */}
            {!finished && (
              <Button variant="outline" size="sm" onClick={cancel} disabled={busy}>
                <Square className="size-4" />
                취소
              </Button>
            )}
            {(simulation.status === 'failed' || simulation.status === 'canceled') && (
              <Button size="sm" onClick={retry} disabled={busy}>
                <RotateCcw className="size-4" />
                다시 걸기
              </Button>
            )}
            {finished && (
              <Button variant="outline" size="sm" onClick={tidy} disabled={busy}>
                <Eraser className="size-4" />
                중간 파일 정리
              </Button>
            )}
          </>
        }
      />

      <ErrorNotice error={error} />

      {tidied && (
        <Alert>
          <AlertTitle>정리했습니다</AlertTitle>
          <AlertDescription>
            {tidied} 결과(고유진동수 · 모드 형상)와 입력은 그대로 남습니다. 지운 것을 되살리려면
            다시 걸어야 합니다.
          </AlertDescription>
        </Alert>
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

      <section className="space-y-2">
        <h2 className="text-sm font-medium">단계</h2>
        <ol className="divide-y rounded-md border">
          {simulation.stages.map((stage: Stage) => (
            <li key={stage.name} className="flex items-start gap-3 px-4 py-3">
              <StatusBadge kind="stage" value={stage.status} className="mt-0.5 w-16 justify-center" />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{STAGE_LABELS[stage.name] ?? stage.name}</p>
                {stage.detail && <p className="text-muted-foreground text-sm">{stage.detail}</p>}
                {stage.error_message && (
                  <p className="text-destructive text-sm">{stage.error_message}</p>
                )}
              </div>
              <div className="text-muted-foreground shrink-0 text-right text-xs">
                {stage.started_at && <p>{shownDateTime(stage.started_at)}</p>}
                {stage.started_at && <p>{shownDuration(stage.started_at, stage.finished_at)}</p>}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {summary.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium">요약</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-md border p-4 text-sm sm:grid-cols-3">
            {summary.map(([key, value]) => (
              <div key={key}>
                <dt className="text-muted-foreground text-xs">{SUMMARY_LABELS[key] ?? key}</dt>
                <dd className="font-medium">{shownSummary(key, value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {/* **조건을 조용히 무시하지 않는다** — 무엇을 반영하고 무엇을 넘겼는지 그대로 보인다. */}
      <ConditionList conditions={simulation.conditions} />

      {/* 결과 요약은 **끝난 뒤에 한 번만** 받는다. 폴링에 실으면 같은 파일을 2초마다 읽는다. */}
      <ResultPanel
        simulationId={id}
        status={simulation.status}
        artifacts={simulation.artifacts}
      />

      {/* **센서 자리의 실측과 같은 자리에서 견준다** — 차이를 변수(영률 · 감쇠)로 설명한다. */}
      <MeasurementsPanel simulationId={id} status={simulation.status} />

      {/* **이 값이 메시에 얼마나 기대나** — 요소 크기만 바꿔 다시 풀어 본다. */}
      <ConvergencePanel
        simulationId={id}
        status={simulation.status}
        solver={solverOf(simulation.spec)}
      />

      <section className="space-y-2">
        <h2 className="text-sm font-medium">산출물</h2>
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
    </div>
  )
}
