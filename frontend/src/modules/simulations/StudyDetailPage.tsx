/**
 * 설계점 비교 — **이것이 DOE 를 돌린 이유다.**
 *
 * 「두께 6 · 12 · 20 중 1차 공진이 가장 높은 것」, 그리고 「그 대가로 질량이 얼마나 늘었나」.
 * CAD 플랫폼은 결과를 받지 않으므로(CompCore 0장) 고르는 일이 여기서 끝나야 한다.
 *
 * 그림은 `StudyOverview` 가 그린다 — **한 장으로 본다.** 모드를 하나씩 눌러 봐야 아는 화면은
 * 「전반적으로 어떤가」 에 답하지 못한다(실제로 그래서 다시 짰다).
 *
 * 아직 안 끝난 점은 안 끝난 대로 보인다. DOE 하나가 다 도는 데 점 수 x 1~2분이 걸리고,
 * 다 끝나야 보여 주면 그동안 아무것도 못 본다.
 */

import { useState } from 'react'
import { Download, Eraser, RotateCcw } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import { RECIPE_LABELS, SOLVER_LABELS } from '@/modules/simulations/labels'
import { StudyMeasurements } from '@/modules/simulations/StudyMeasurements'
import { StudyOverview } from '@/modules/simulations/StudyOverview'
import { StudyValues } from '@/modules/simulations/StudyValues'
import { ApiError } from '@/shared/api/client'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { Button } from '@/shared/components/ui/button'
import { useResource } from '@/shared/hooks/useResource'

export default function StudyDetailPage() {
  const { id = '' } = useParams()
  const study = useResource(() => simulationApi.study(id), [id])
  const [failed, setFailed] = useState<ApiError | Error | null>(null)
  const [tidying, setTidying] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)

  /**
   * **실패한 설계점만 다시 실행한다** — 점마다 재시도를 누르게 하면 200점짜리 DOE 에서는 아무도
   * 안 한다. 서버의 재시도를 점마다 부르고, 못 한 점은 그 까닭을 모아 보여 준다.
   */
  async function retryFailed() {
    if (!study.data) return
    setRetrying(true)
    setFailed(null)
    const targets = study.data.points.filter(
      (one) => one.status === 'failed' || one.status === 'canceled',
    )
    let done = 0
    const problems: string[] = []
    for (const one of targets) {
      try {
        await simulationApi.retry(one.simulation_id)
        done += 1
      } catch (caught) {
        problems.push(`p${String(one.number).padStart(4, '0')}: ${caught instanceof Error ? caught.message : '실패'}`)
      }
    }
    setNotice(
      `실패 · 취소된 설계점 ${done}개를 다시 실행했습니다.` +
        (problems.length ? ` 다시 실행하지 못한 점: ${problems.join(' · ')}` : ''),
    )
    setRetrying(false)
    study.reload()
  }

  async function exportCsv() {
    if (!study.data) return
    setFailed(null)
    try {
      await simulationApi.exportStudy(id, `${study.data.name}.csv`)
    } catch (caught) {
      setFailed(caught instanceof Error ? caught : new Error('CSV 를 내려받지 못했습니다.'))
    }
  }

  if (study.error) {
    return (
      <div className="space-y-6">
        <PageHeader title="DOE 비교" back={{ to: '/simulations/studies', label: 'DOE 비교' }} />
        <ErrorNotice error={study.error} />
      </div>
    )
  }
  if (!study.data) return null

  const points = study.data.points
  const tracked = study.data.tracks ?? []
  const modal = study.data.recipe === 'modal'
  const retryable = points.filter((one) => one.status === 'failed' || one.status === 'canceled').length
  const solvers = study.data.solvers ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        title={study.data.name}
        description={
          <>
            {RECIPE_LABELS[study.data.recipe] ?? study.data.recipe} ·{' '}
            {solvers.map((one) => SOLVER_LABELS[one] ?? one).join(' + ') || '—'} · 설계점{' '}
            {points.length}개 · 변수 {study.data.factors.join(' · ') || '없음'}
            {!modal ? null : tracked.length > 0 ? (
              <>
                {' '}
                · 모드 {tracked.length}개를 형상으로 이어 견줍니다(기준 p
                {String(study.data.reference_point ?? 0).padStart(4, '0')})
              </>
            ) : (
              // **추적이 없으면 그렇다고 말한다** — 순번으로 이은 선은 모드가 뒤바뀌는 순간
              // 서로 다른 모드를 잇는다.
              <> · 모드 지문이 없어 차수로만 견줍니다(다시 걸면 지문이 생깁니다)</>
            )}
          </>
        }
        back={{ to: '/simulations/studies', label: 'DOE 비교' }}
        actions={
          <>
            {retryable > 0 && (
              <Button variant="outline" size="sm" onClick={retryFailed} disabled={retrying}>
                <RotateCcw className="size-4" />
                {retrying ? '다시 실행 중…' : `실패한 점 다시 실행 (${retryable})`}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => setTidying(true)}>
              <Eraser className="size-4" />
              중간 파일 정리
            </Button>
            <Button variant="outline" size="sm" onClick={exportCsv}>
              <Download className="size-4" />
              CSV 내보내기
            </Button>
          </>
        }
      />

      <ErrorNotice error={failed} />
      {notice && (
        <p className="rounded-md border px-4 py-2 text-sm">
          {notice}{' '}
          <button type="button" className="text-muted-foreground underline" onClick={() => setNotice(null)}>
            닫기
          </button>
        </p>
      )}

      <ConfirmDialog
        open={tidying}
        title="중간 파일 정리"
        description={
          <>
            끝난 설계점 전부의 중간 파일(.mechdb · .rst · 솔버 scratch)을 삭제합니다. 결과 요약 · 그림 ·
            입력은 남습니다. 삭제한 중간 파일이 다시 필요하면 그 점을 다시 실행해야 합니다.
          </>
        }
        confirmLabel="정리"
        destructive
        onConfirm={async () => {
          const done = await simulationApi.tidyStudy(id)
          setNotice(
            `설계점 ${done.points}개에서 중간 파일 ${done.files}개 · ${(done.bytes_freed / 1024 / 1024).toFixed(1)}MB 를 정리했습니다.`,
          )
        }}
        onClose={() => setTidying(false)}
      />

      {solvers.length > 1 && (
        // **솔버가 섞이면 그 차이(몇 %)가 변수의 효과로 읽힌다** — 견주기 전에 말해 둔다.
        <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          이 스터디는 솔버가 섞여 있습니다({solvers.map((one) => SOLVER_LABELS[one] ?? one).join(' · ')}).
          두 솔버의 값은 몇 % 갈리므로 설계점 사이의 차이가 변수의 효과만은 아닙니다.
        </p>
      )}

      {points.every((one) => one.status !== 'done') ? (
        <EmptyState
          title="아직 끝난 설계점이 없습니다"
          hint="설계점이 차례로 돕니다. 한 건에 1~2분 걸리고, 끝난 것부터 여기에 나타납니다."
        />
      ) : modal ? (
        <StudyOverview study={study.data} />
      ) : (
        // 정적 · 조화는 **모드가 아니라 값**을 견준다 — 모드 지도 · 질량 대 주파수는 뜻이 없다.
        <StudyValues study={study.data} />
      )}

      {/* **실측에 가장 가까운 설계점** — 물성 · 감쇠를 훑은 DOE 면 그 값이 차이를 설명한다. */}
      <StudyMeasurements studyId={id} factors={study.data.factors} />
    </div>
  )
}
