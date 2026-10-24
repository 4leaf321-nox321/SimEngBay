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
 *
 * **탭으로 가른다**(해석 작업 화면과 같은 꼴, 2026-10-20) — 비교(그림 · 행렬) · 설계점(점마다 상태 ·
 * 오류 — 작업 화면의 「진행」) · 검증(실측). 한 장에 다 두면 실측 표가 그림 아래 멀리 밀려 있어
 * 있는 줄도 몰랐다. 탭은 주소의 `?tab=` 이 정본이다.
 */

import { useState } from 'react'
import { ClipboardCopy, Eraser, RefreshCw, RotateCcw, Square, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { StudyPoint } from '@/modules/simulations/api'
import { RECIPE_LABELS, SOLVER_LABELS } from '@/modules/simulations/labels'
import { PublishControl, PublishedBadge } from '@/modules/simulations/Publishing'
import { listPath } from '@/modules/simulations/SimulationsLayout'
import { StudyMeasurements } from '@/modules/simulations/StudyMeasurements'
import { StudyExplorer } from '@/modules/simulations/StudyExplorer'
import { StudyOverview } from '@/modules/simulations/StudyOverview'
import { StudyValues } from '@/modules/simulations/StudyValues'
import { ApiError } from '@/shared/api/client'
import { useAuth } from '@/shared/auth/AuthContext'
import { ownsWork } from '@/shared/auth/roles'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { StatusBadge } from '@/shared/components/StatusBadge'
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
import { copyText, toTsv } from '@/shared/lib/clipboard'

/** DOE 화면의 탭 — 주소의 `?tab=` 이 정본이다. */
type StudyTab = 'compare' | 'explore' | 'points' | 'checks'
const STUDY_TABS: StudyTab[] = ['compare', 'explore', 'points', 'checks']

export default function StudyDetailPage() {
  const { id = '' } = useParams()
  const study = useResource(() => simulationApi.study(id), [id])
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()
  const [failed, setFailed] = useState<ApiError | Error | null>(null)
  const [tidying, setTidying] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [removing, setRemoving] = useState(false)
  const navigate = useNavigate()
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

  /**
   * **비교 표를 클립보드로** — 사내 DRM 으로 파일을 내려받지 못한다. 탭으로 가른 글이라 엑셀 · 시트에
   * 붙이면 칸이 그대로 선다. http 에서도 된다(`copyText`).
   */
  async function copyTable() {
    setFailed(null)
    try {
      const table = await simulationApi.studyTable(id)
      await copyText(toTsv([table.head, ...table.rows]))
      setNotice(`설계점 ${table.rows.length}개 · 열 ${table.head.length}개를 복사했습니다 — 엑셀에 붙여 넣으세요.`)
    } catch (caught) {
      setFailed(caught instanceof Error ? caught : new Error('표를 복사하지 못했습니다.'))
    }
  }

  if (study.error) {
    return (
      <div className="space-y-6">
        <PageHeader title="DOE" back={{ to: listPath('mine', 'doe'), label: '해석 · DOE' }} />
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
  // **남의 게시 DOE 는 읽기만 한다** — 바꾸는 단추는 그 점들을 건 사람과 시스템 관리자에게만.
  const mine = ownsWork(user, study.data.owner_id)
  const finishedPoints = points.filter((one) => one.status === 'done').length
  // **끝난 점이 없으면 비교할 것이 없다** — 그때는 설계점(진행) 탭이 먼저다(작업 화면과 같다).
  const comparable = finishedPoints > 0
  const asked = params.get('tab') as StudyTab | null
  const tab: StudyTab =
    asked && STUDY_TABS.includes(asked) && (asked !== 'compare' || comparable)
      ? asked
      : comparable
        ? 'compare'
        : 'points'
  function setTab(next: StudyTab) {
    const after = new URLSearchParams(params)
    after.set('tab', next)
    setParams(after, { replace: true })
  }
  const running = points.filter((one) => !['done', 'failed', 'canceled'].includes(one.status)).length
  // **도는 점이 있으면 지우지 않는다**(SIMULATIONS-0035) — 대기 중인 점은 서버가 취소로 닫고 지운다.
  const solving = points.filter((one) => !['done', 'failed', 'canceled', 'queued'].includes(one.status)).length
  const failedPoints = points.filter((one) => one.status === 'failed').length
  const published = study.data.published ?? 0

  async function setPublished(next: boolean) {
    const done = await (next ? simulationApi.publishStudy(id) : simulationApi.unpublishStudy(id))
    setNotice(
      next
        ? `설계점 ${done.points}개를 게시했습니다 — 조직의 누구나 읽을 수 있습니다.`
        : `설계점 ${done.points}개의 게시를 해제했습니다.`,
    )
    study.reload()
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            {study.data.name}
            {published > 0 && <PublishedBadge />}
          </span>
        }
        description={
          <>
            {study.data.owner_name ?? '—'} ·{' '}
            {published > 0 && `게시 ${published}/${points.length} · `}
            {!mine && '다른 사람의 결과라 읽기만 합니다 · '}
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
        back={
          mine
            ? { to: listPath('mine', 'doe'), label: '개인 작업 · DOE' }
            : { to: listPath('published', 'doe'), label: '공용 작업공간 · DOE' }
        }
        actions={
          <>
            {/* **끝난 점만 게시한다.** 게시 뒤에 끝난 점이 있으면 「게시」 가 나머지를 마저 게시한다. */}
            {mine && finishedPoints > published && (
              <PublishControl
                published={false}
                subject="이 DOE 의 끝난 설계점"
                onPublish={() => setPublished(true)}
                onUnpublish={() => setPublished(false)}
              />
            )}
            {mine && published > 0 && (
              <PublishControl
                published
                subject="이 DOE 의 게시된 설계점"
                onPublish={() => setPublished(true)}
                onUnpublish={() => setPublished(false)}
              />
            )}
            {mine && retryable > 0 && (
              <Button variant="outline" size="sm" onClick={retryFailed} disabled={retrying}>
                <RotateCcw className="size-4" />
                {retrying ? '다시 실행 중…' : `실패한 점 다시 실행 (${retryable})`}
              </Button>
            )}
            {/* **설계점 200개를 하나씩 멈출 수는 없다** — 대기는 곧바로, 도는 점은 몇 초 안에. */}
            {mine && running > 0 && (
              <Button variant="outline" size="sm" onClick={() => setStopping(true)}>
                <Square className="size-4" />
                모두 멈추기 ({running})
              </Button>
            )}
            {mine && (
              <Button variant="outline" size="sm" onClick={() => setTidying(true)}>
                <Eraser className="size-4" />
                중간 파일 정리
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={copyTable}>
              <ClipboardCopy className="size-4" />
              표 복사
            </Button>
            {mine && (
              <Button variant="outline" size="sm" onClick={() => setRemoving(true)}>
                <Trash2 className="size-4" />
                삭제
              </Button>
            )}
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

      <ConfirmDialog
        open={stopping}
        title="DOE 모두 멈추기"
        description={
          <>
            끝나지 않은 설계점 {running}개를 멈춥니다(내가 건 점만). 대기 중인 점은 곧바로, 도는 점은
            워커가 몇 초 안에 멈춥니다. 멈춘 점은 「실패한 점 다시 실행」 으로 다시 걸 수 있습니다.
          </>
        }
        confirmLabel="모두 멈추기"
        destructive
        onConfirm={async () => {
          const done = await simulationApi.cancelStudy(id)
          setNotice(`설계점 ${done.points}개를 멈추게 했습니다 — 도는 점은 몇 초 안에 멈춥니다.`)
          study.reload()
        }}
        onClose={() => setStopping(false)}
      />

      <ConfirmDialog
        open={removing}
        title="DOE 삭제"
        description={
          solving > 0 ? (
            <>
              도는 설계점 {solving}개가 있어 지울 수 없습니다 — 먼저 「모두 멈추기」 를 누르고, 멈춘
              뒤에 다시 지우세요.
            </>
          ) : (
            <div className="space-y-2">
              <p>
                「{study.data.name}」 의 설계점 {points.length}개(내가 건 점)와 그 작업 폴더(결과 · 그림 ·
                중간 파일)를 모두 지웁니다. 메시 수렴 점검 수준과 올린 실측도 함께 사라집니다. 대기
                중인 점은 취소하고 지웁니다. 되돌릴 수 없습니다.
              </p>
              {published > 0 && <p>게시된 설계점 {published}개는 다른 사람의 화면에서도 사라집니다.</p>}
              <p>같은 DOE 폴더는 지운 뒤 다시 가져올 수 있습니다.</p>
            </div>
          )
        }
        confirmLabel="삭제"
        destructive
        confirmDisabled={solving > 0}
        onConfirm={async () => {
          await simulationApi.removeStudy(id)
          navigate(listPath('mine', 'doe'), { replace: true })
        }}
        onClose={() => setRemoving(false)}
      />

      {solvers.length > 1 && (
        // **솔버가 섞이면 그 차이(몇 %)가 변수의 효과로 읽힌다** — 견주기 전에 말해 둔다.
        <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
          이 스터디는 솔버가 섞여 있습니다({solvers.map((one) => SOLVER_LABELS[one] ?? one).join(' · ')}).
          두 솔버의 값은 몇 % 갈리므로 설계점 사이의 차이가 변수의 효과만은 아닙니다.
        </p>
      )}

      <Tabs value={tab} onValueChange={(next) => setTab(next as StudyTab)}>
        <TabsList variant="line">
          <TabsTrigger
            value="compare"
            disabled={!comparable}
            title={comparable ? undefined : '끝난 설계점이 생기면 나옵니다'}
          >
            비교
          </TabsTrigger>
          <TabsTrigger
            value="explore"
            disabled={!comparable}
            title={comparable ? undefined : '끝난 설계점이 생기면 나옵니다'}
          >
            다변수
          </TabsTrigger>
          <TabsTrigger value="points">
            설계점 ({finishedPoints}/{points.length})
          </TabsTrigger>
          <TabsTrigger value="checks">검증</TabsTrigger>
        </TabsList>

        <TabsContent value="compare" className="space-y-6 pt-4">
          {comparable &&
            (modal ? (
              <StudyOverview study={study.data} />
            ) : (
              // 정적 · 조화는 **모드가 아니라 값**을 견준다 — 모드 지도 · 질량 대 주파수는 뜻이 없다.
              <StudyValues study={study.data} />
            ))}
        </TabsContent>

        <TabsContent value="explore" className="space-y-6 pt-4">
          {/* 변수 하나 대 결과 하나를 넘어서 — 3D 산점도 · 2변수 영향 · 주효과 · 산점도 행렬 · 평행
              좌표 · 상관. 같은 표(끝난 점 · 추적한 모드)를 본다. */}
          {comparable && <StudyExplorer study={study.data} />}
        </TabsContent>

        <TabsContent value="points" className="space-y-3 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-muted-foreground text-sm">
              완료 {finishedPoints}
              {running > 0 && ` · 진행 ${running}`}
              {failedPoints > 0 && <span className="text-destructive"> · 실패 {failedPoints}</span>}
              {!comparable && ' — 설계점이 차례로 돕니다. 한 건에 1~2분 걸리고, 끝난 것부터 비교에 나타납니다.'}
            </p>
            {/* 이 화면은 스스로 다시 묻지 않는다 — 200점을 몇 초마다 묻지 않으려고. */}
            <Button variant="outline" size="sm" onClick={study.reload}>
              <RefreshCw className="size-4" />
              새로 고침
            </Button>
          </div>
          <StudyPoints points={points} factors={study.data.factors} />
        </TabsContent>

        <TabsContent value="checks" className="space-y-6 pt-4">
          {/* **실측에 가장 가까운 설계점** — 물성 · 감쇠를 훑은 DOE 면 그 값이 차이를 설명한다. */}
          <StudyMeasurements studyId={id} factors={study.data.factors} readOnly={!mine} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

/**
 * 설계점마다 **상태 · 오류 · 솔버 · 게시** — 작업 화면의 「진행」 에 해당한다. 결과 값은 비교
 * 탭의 행렬에 있다(여기는 「어느 점이 왜 안 끝났나」 를 보는 자리).
 */
function StudyPoints({ points, factors }: { points: StudyPoint[]; factors: string[] }) {
  if (points.length === 0) {
    return <EmptyState title="설계점이 없습니다" hint="가져온 점이 여기에 표시됩니다." />
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>점</TableHead>
          {factors.map((one) => (
            <TableHead key={one}>{one}</TableHead>
          ))}
          <TableHead>상태</TableHead>
          <TableHead>오류</TableHead>
          <TableHead>솔버</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {points.map((point) => (
          <TableRow key={point.simulation_id}>
            <TableCell>
              <Link to={`/simulations/${point.simulation_id}`} className="font-mono hover:underline">
                p{String(point.number).padStart(4, '0')}
              </Link>
              {point.published && <PublishedBadge className="ml-1" />}
            </TableCell>
            {factors.map((one) => (
              <TableCell key={one} className="font-mono">
                {point.params[one] ?? '—'}
              </TableCell>
            ))}
            <TableCell>
              <StatusBadge kind="simulation" value={point.status} />
            </TableCell>
            <TableCell className="text-destructive font-mono text-xs">{point.error_code ?? ''}</TableCell>
            <TableCell>{SOLVER_LABELS[point.solver] ?? point.solver}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
