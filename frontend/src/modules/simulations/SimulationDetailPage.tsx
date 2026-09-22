/**
 * 해석 작업 상세 — 단계 타임라인 · 요약 · 산출물.
 *
 * 끝나지 않은 작업은 2초마다 `/status` 를 폴링한다. 그 경로만 접근 로그를 비껴간다
 * (`shared/access_log.py`) — 상세 경로를 그대로 폴링하면 로그가 그 한 줄로 찬다.
 */

import { useEffect, useState } from 'react'
import { Download, RotateCcw } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { FINAL_STATUSES, simulationApi } from '@/modules/simulations/api'
import type { Artifact, Simulation, Stage } from '@/modules/simulations/api'
import { ResultPanel } from '@/modules/simulations/ResultPanel'
import {
  ARTIFACT_LABELS,
  FAILURE_LABELS,
  RECIPE_LABELS,
  STAGE_LABELS,
  shownDuration,
  shownSize,
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
  ansys_version: 'Ansys 버전',
}

function shownSummary(key: string, value: unknown): string {
  if (value == null) return '—'
  if (key === 'input_bytes' && typeof value === 'number') return shownSize(value)
  if (key === 'first_elastic_hz' && typeof value === 'number') return `${value.toFixed(2)} Hz`
  if (key === 'solver_seconds' && typeof value === 'number') return `${value.toFixed(1)}초`
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
            {simulation.owner_workspace_name ?? '전역'} · {simulation.requested_by_name ?? '—'} ·{' '}
            {shownDateTime(simulation.created_at)} · 소요{' '}
            {shownDuration(simulation.started_at, simulation.finished_at)}
            {simulation.attempts > 1 && ` · ${simulation.attempts}번째 시도`}
          </>
        }
        back={{ to: '/simulations', label: '해석 작업' }}
        actions={
          simulation.status === 'failed' ? (
            <Button size="sm" onClick={retry} disabled={busy}>
              <RotateCcw className="size-4" />
              재시도
            </Button>
          ) : undefined
        }
      />

      <ErrorNotice error={error} />

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

      {/* 결과 요약은 **끝난 뒤에 한 번만** 받는다. 폴링에 실으면 같은 파일을 2초마다 읽는다. */}
      <ResultPanel
        simulationId={id}
        status={simulation.status}
        artifacts={simulation.artifacts}
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
