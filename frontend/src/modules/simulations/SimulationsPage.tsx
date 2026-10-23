/**
 * 「해석」 목록 — **항목은 단일 해석 하나이거나 DOE 한 벌이다**(2026-10-23, ADR 0014).
 *
 * 전에는 「해석 작업」 과 「DOE 비교」 가 따로 있었고, 해석 작업 목록에 DOE 설계점이 낱개로 섞여(200점이면
 * 200줄) 같은 것이 두 곳에 보였다. 이제 한 목록이다:
 *
 * - **DOE 는 한 줄** — 진행(완료 · 실패 수)을 그 줄에 적는다. 이름을 누르면 DOE 화면(비교 · 다변수 ·
 *   설계점 · 검증), ▸ 를 누르면 그 자리에서 설계점이 펼쳐진다(어느 점이 실패했는지 바로 보인다).
 * - 메시 수렴 수준은 줄로 서지 않는다 — 원래 작업의 검증 탭에서 본다.
 * - **상태로 거르면 낱개로 편다** — 「지금 대기 · 실패 중인 작업 전부」 는 설계점 하나하나가 답이다.
 *
 * 어느 작업공간인지(개인 작업 · 공용 작업공간 · 전체)는 위의 탭이 고르고 **주소가 정본이다**
 * (`?scope=`). 폴더는 왼쪽 나무 — 항목 단위로 옮긴다(DOE 의 설계점은 DOE 를 따라간다). 고른 것
 * 여럿에 폴더 이동 · 게시 · 게시 해제 · 삭제를 한꺼번에 한다(바꿀 수 있는 줄만 고른다).
 *
 * 목록은 폴링하지 않는다. 걸면 상세로 가고, 상세가 상태를 폴링한다.
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight, Plus, RefreshCw } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { itemFolders, simulationApi } from '@/modules/simulations/api'
import type { DoeImport, Item, ItemKind, ListScope, StudyPoint } from '@/modules/simulations/api'
import { bulkNotice, eachOf } from '@/modules/simulations/bulk'
import { ChosenActions } from '@/modules/simulations/ChosenActions'
import { shownOutcome, shownValue } from '@/modules/simulations/format'
import { RECIPE_LABELS, SOLVER_LABELS, shownDuration } from '@/modules/simulations/labels'
import { NewSimulationDialog } from '@/modules/simulations/NewSimulationDialog'
import { PublishedBadge } from '@/modules/simulations/Publishing'
import { ScopeTabs, workScope } from '@/modules/simulations/SimulationsLayout'
import { workspaceApi } from '@/modules/workspaces/api'
import { useAuth } from '@/shared/auth/AuthContext'
import { ownsWork } from '@/shared/auth/roles'
import { EmptyState } from '@/shared/components/EmptyState'
import { ErrorNotice } from '@/shared/components/ErrorNotice'
import { PageHeader } from '@/shared/components/PageHeader'
import { Pagination } from '@/shared/components/Pagination'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/shared/components/ui/alert'
import { Button } from '@/shared/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/components/ui/table'
import {
  ChosenBar,
  FolderCrumbs,
  FolderDialogs,
  FolderSelect,
  PickAll,
  PickBox,
  RowFolder,
} from '@/shared/folders/FolderParts'
import { FolderTree } from '@/shared/folders/FolderTree'
import { useFolderSpace } from '@/shared/folders/useFolderSpace'
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'
import { cn } from '@/shared/lib/utils'

const PER_PAGE = 50
const ALL = '__all__'
const COLUMNS = 8

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: ALL, label: '전체 상태' },
  { value: 'queued', label: '대기' },
  { value: 'fetching', label: '형상 준비' },
  { value: 'modeling', label: '모델링' },
  { value: 'solving', label: '솔버' },
  { value: 'extracting', label: '추출' },
  { value: 'done', label: '완료' },
  { value: 'failed', label: '실패' },
  { value: 'canceled', label: '취소됨' },
]

const KINDS: { value: ItemKind | ''; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'job', label: '단일 해석' },
  { value: 'doe', label: 'DOE' },
]

/** 출처 — 어디서 만든 작업인가. 업로드는 따로 표시하지 않는다(가장 흔하다). */
const SOURCE_LABELS: Record<string, string> = {
  doe_point: 'DOE 설계점',
  design: 'CAD 설계',
  mesh_check: '메시 수렴 점검',
}

const DESCRIPTIONS: Record<ListScope, string> = {
  mine: '내가 실행한 해석과 DOE 입니다. 끝난 결과를 게시하면 공용 작업공간에 표시됩니다.',
  published: '게시된 해석 결과입니다. 누구나 읽을 수 있고, 바꾸는 것은 실행한 사람뿐입니다.',
  all: '모든 사람의 해석과 DOE 입니다(시스템 관리자).',
}

export default function SimulationsPage() {
  const [params] = useSearchParams()
  const scope = workScope(params)
  // **작업공간을 바꾸면 새로 시작한다** — 고른 폴더 · 쪽 · 고른 줄은 그 작업공간의 것이다.
  return <ItemList key={scope} scope={scope} />
}

function ItemList({ scope }: { scope: ListScope }) {
  const navigate = useNavigate()
  // 홈의 「남은 일」 이 `?status=failed` 로 보낸다 — 주소가 거르개의 정본이다.
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const workspace = params.get('workspace') ?? ''
  const kind = (params.get('kind') ?? '') as ItemKind | ''
  const [offset, setOffset] = useState(0)
  const workspaces = useResource(() => workspaceApi.options(), [])
  const [creating, setCreating] = useState(false)
  const [imported, setImported] = useState<DoeImport | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const { user } = useAuth()
  const space = useFolderSpace('simulations', itemFolders(scope), { onRefilter: () => setOffset(0) })

  const page = useResource(
    () =>
      simulationApi.items({
        scope,
        kind: kind || undefined,
        status: status || undefined,
        workspaceSlug: workspace || undefined,
        folder: space.folder,
        limit: PER_PAGE,
        offset,
      }),
    [scope, kind, status, workspace, offset, space.folder, space.version],
  )
  const rows = page.data?.items ?? []
  // **바꿀 수 있는 줄만 고른다** — 남의 게시 결과는 읽기만 한다(서버도 막는다).
  const movable = rows.filter((one) => ownsWork(user, ownerOf(one)))

  /** 주소가 거르개의 정본이다 — 한 칸을 바꿔도 다른 칸(작업공간 포함)은 남긴다. */
  function changeFilter(key: 'status' | 'workspace' | 'kind', value: string) {
    setOffset(0)
    const next = new URLSearchParams(params)
    if (value === ALL || value === '') next.delete(key)
    else next.set(key, value)
    setParams(next)
  }
  const filtered = Boolean(status || workspace || kind || space.folder !== null)

  /** 고른 항목 여럿에 같은 일 — DOE 는 DOE 의 API, 단일 해석은 작업의 API(`bulk.ts`). */
  async function bulk(verb: string, onJob: (id: string) => Promise<unknown>, onDoe: (id: string) => Promise<unknown>) {
    const targets = [...space.chosen].map((key) => ({
      id: key,
      name: nameOf(rows.find((one) => one.key === key)) ?? key,
    }))
    const result = await eachOf(targets, (key) =>
      key.startsWith('doe:') ? onDoe(key.slice(4)) : onJob(key.slice(4)),
    )
    setNotice(bulkNotice(verb, '항목', result))
    space.setChosen(new Set())
    page.reload()
    space.refresh()
  }

  function toggleOpen(key: string) {
    const next = new Set(open)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setOpen(next)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="해석"
        description={DESCRIPTIONS[scope]}
        actions={
          <>
            <Button variant="outline" size="sm" onClick={page.reload}>
              <RefreshCw className="size-4" />
              새로 고침
            </Button>
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="size-4" />새 해석
            </Button>
          </>
        }
      />

      <ScopeTabs scope={scope} />

      <div className="flex gap-4">
        {/* 폴더 — 넓은 화면에서 왼쪽에. 좁으면 위의 고르개로. 줄을 끌어다 놓으면 그 폴더로 옮긴다. */}
        <aside className="hidden w-56 shrink-0 md:block">
          <FolderTree space={space} allLabel="모든 항목" noun="항목" />
        </aside>
        <div className="min-w-0 flex-1 space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <FolderSelect space={space} allLabel="모든 항목" />
            <div role="group" aria-label="종류" className="flex rounded-md border p-0.5">
              {KINDS.map((one) => (
                <button
                  key={one.value}
                  type="button"
                  aria-pressed={kind === one.value}
                  onClick={() => changeFilter('kind', one.value)}
                  className={cn(
                    'rounded px-2.5 py-0.5 text-sm',
                    kind === one.value ? 'bg-accent font-medium' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {one.label}
                </button>
              ))}
            </div>
            <Select value={status || ALL} onValueChange={(value) => changeFilter('status', value)}>
              <SelectTrigger className="h-8 w-36" aria-label="상태">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((one) => (
                  <SelectItem key={one.value} value={one.value}>
                    {one.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={workspace || ALL} onValueChange={(value) => changeFilter('workspace', value)}>
              <SelectTrigger className="h-8 w-48" aria-label="부서">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>전체 부서</SelectItem>
                {(workspaces.data ?? []).map((one) => (
                  <SelectItem key={one.slug} value={one.slug}>
                    {' '.repeat(one.depth * 2)}
                    {one.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {status && (
            // **상태로 거르면 낱개로 편다** — 말하지 않으면 DOE 가 왜 갑자기 수백 줄인지 모른다.
            <p className="text-muted-foreground text-xs">
              상태로 거르면 DOE 설계점까지 작업 하나하나로 펼쳐 보입니다.
            </p>
          )}

          <FolderCrumbs space={space} allLabel="모든 항목" />
          <ChosenBar space={space}>
            <ChosenActions
              count={space.chosen.size}
              noun="항목"
              removeNote="DOE 는 내가 건 설계점 전부(앞선 시도 · 메시 수렴 수준까지)가 사라집니다. 같은 DOE 폴더는 지운 뒤 다시 가져올 수 있습니다."
              onPublish={() => bulk('게시', (id) => simulationApi.publish(id), (id) => simulationApi.publishStudy(id))}
              onUnpublish={() =>
                bulk('게시 해제', (id) => simulationApi.unpublish(id), (id) => simulationApi.unpublishStudy(id))
              }
              onRemove={() => bulk('삭제', (id) => simulationApi.remove(id), (id) => simulationApi.removeStudy(id))}
            />
          </ChosenBar>
          {notice && (
            <p className="rounded-md border px-4 py-2 text-sm">
              {notice}{' '}
              <button type="button" className="text-muted-foreground underline" onClick={() => setNotice(null)}>
                닫기
              </button>
            </p>
          )}

          {imported && (
            <Alert>
              <AlertTitle>
                {imported.name} — {imported.created.length}건을 생성했습니다
              </AlertTitle>
              <AlertDescription>
                {imported.skipped.length === 0 ? (
                  <p>고른 설계점을 모두 생성했습니다. 차례로 실행되며 DOE 줄의 진행이 바뀝니다.</p>
                ) : (
                  <>
                    <p>{imported.skipped.length}건은 생성하지 않았습니다:</p>
                    <ul className="mt-1 space-y-0.5 text-xs">
                      {imported.skipped.map((one) => (
                        <li key={one.number}>
                          <span className="font-mono">p{String(one.number).padStart(4, '0')}</span> —{' '}
                          {one.skip_reason}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
                <Button variant="ghost" size="sm" className="mt-2 -ml-2" onClick={() => setImported(null)}>
                  닫기
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <ErrorNotice error={page.error} />

          {page.data && rows.length === 0 ? (
            <EmptyState
              title={
                filtered
                  ? '조건에 맞는 항목이 없습니다'
                  : scope === 'published'
                    ? '게시된 결과가 없습니다'
                    : '해석이 없습니다'
              }
              hint={
                filtered
                  ? '거르개 · 폴더를 「전체」 로 바꾸면 다른 항목이 표시됩니다. 빈 폴더면 항목을 끌어다 놓으세요.'
                  : scope === 'published'
                    ? '끝난 해석 · DOE 를 게시하면 여기에 표시되고, 누구나 읽을 수 있습니다.'
                    : 'CAD 폴더(설계 하나 · DOE)를 고르거나 STEP 형상을 올려 첫 해석을 실행합니다.'
              }
              action={
                filtered || scope === 'published' ? undefined : (
                  <Button size="sm" onClick={() => setCreating(true)}>
                    <Plus className="size-4" />새 해석
                  </Button>
                )
              }
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">
                    <PickAll space={space} ids={movable.map((one) => one.key)} />
                  </TableHead>
                  <TableHead>이름</TableHead>
                  <TableHead>종류</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>결과</TableHead>
                  <TableHead>부서</TableHead>
                  <TableHead>실행한 사람</TableHead>
                  <TableHead>생성</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.flatMap((one) => {
                  const mine = ownsWork(user, ownerOf(one))
                  const unfolded = one.kind === 'doe' && open.has(one.key)
                  return [
                    <TableRow
                      key={one.key}
                      draggable={mine}
                      onDragStart={(event) => space.startDrag(event, one.key)}
                      data-state={space.chosen.has(one.key) ? 'selected' : undefined}
                    >
                      <TableCell>
                        <PickBox space={space} id={one.key} name={nameOf(one) ?? one.key} disabled={!mine} />
                      </TableCell>
                      {one.study ? (
                        <DoeCells item={one} open={unfolded} onToggle={() => toggleOpen(one.key)} space={space} />
                      ) : (
                        <JobCells item={one} space={space} />
                      )}
                    </TableRow>,
                    unfolded && one.study ? <DoePoints key={`${one.key}-points`} studyId={one.study.study_id} /> : null,
                  ]
                })}
              </TableBody>
            </Table>
          )}

          {page.data && (
            <Pagination
              total={page.data.total}
              limit={page.data.limit}
              offset={page.data.offset}
              onChange={setOffset}
            />
          )}
        </div>
      </div>
      <FolderDialogs space={space} noun="항목" />

      {/* 설계 하나든 DOE 든 이 창 하나다 — 1건이면 그 상세로, 여러 건이면 여기서 결과를 말한다.
          **열 때마다 새로 띄운다** — 띄워 둔 채 다시 열면 앞에서 고른 파일 · 폴더 · 체크가 남아
          방금 만든 점을 또 걸거나(0건) 칸에는 안 보이는 파일을 올렸다(2026-10-05 리뷰). */}
      {creating && (
        <NewSimulationDialog
          open
          onClose={() => setCreating(false)}
          onCreated={(created) => {
            setCreating(false)
            navigate(`/simulations/${created.id}`)
          }}
          onImported={(result) => {
            setCreating(false)
            // 만든 것을 바로 보여 준다 — DOE 한 줄로 생기고 점들이 차례로 돈다.
            setOffset(0)
            page.reload()
            space.refresh()
            // **건너뛴 점은 목록에 안 생긴다** — 여기서 말하지 않으면 사라진다.
            setImported(result)
          }}
        />
      )}
    </div>
  )
}

function ownerOf(item: Item): string | null | undefined {
  return item.study ? item.study.owner_id : item.job?.requested_by_id
}

function nameOf(item: Item | undefined): string | undefined {
  return item?.study?.name ?? item?.job?.name
}

type Space = ReturnType<typeof useFolderSpace>

function JobCells({ item, space }: { item: Item; space: Space }) {
  const one = item.job
  if (!one) return null
  return (
    <>
      <TableCell>
        <Link to={`/simulations/${one.id}`} className="font-medium hover:underline">
          {one.name}
        </Link>
        <RowFolder space={space} folder={one.folder ?? ''} />
        <p className="text-muted-foreground text-xs">
          {one.published_at && <PublishedBadge className="mr-1" />}
          {SOURCE_LABELS[one.source_kind] && (
            <span className="bg-muted mr-1 rounded px-1">{SOURCE_LABELS[one.source_kind]}</span>
          )}
          {one.source_ref}
        </p>
      </TableCell>
      <TableCell>
        {RECIPE_LABELS[one.recipe] ?? one.recipe}
        <span className="text-muted-foreground block text-xs">
          {SOLVER_LABELS[one.solver ?? 'ansys'] ?? one.solver}
        </span>
      </TableCell>
      <TableCell>
        <StatusBadge kind="simulation" value={one.status} />
      </TableCell>
      <TableCell className="text-sm">
        {one.status === 'failed' ? (
          <span className="text-destructive font-mono text-xs">{one.error_code}</span>
        ) : (
          (shownOutcome(one) ?? '—')
        )}
      </TableCell>
      <TableCell>{one.owner_workspace_name ?? '전역'}</TableCell>
      <TableCell>{one.requested_by_name ?? '—'}</TableCell>
      <TableCell className="whitespace-nowrap">
        {shownDateTime(one.created_at)}
        <span className="text-muted-foreground block text-xs">
          소요 {shownDuration(one.started_at, one.finished_at)}
        </span>
      </TableCell>
    </>
  )
}

function DoeCells({ item, open, onToggle, space }: { item: Item; open: boolean; onToggle: () => void; space: Space }) {
  const one = item.study
  if (!one) return null
  const doneRatio = one.points ? one.done / one.points : 0
  return (
    <>
      <TableCell>
        <div className="flex items-start gap-1">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={open}
            aria-label={open ? `${one.name} 설계점 접기` : `${one.name} 설계점 펼치기`}
            className="text-muted-foreground hover:text-foreground mt-0.5"
          >
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
          <div>
            <Link to={`/simulations/studies/${encodeURIComponent(one.study_id)}`} className="font-medium hover:underline">
              {one.name}
            </Link>
            <RowFolder space={space} folder={one.folder ?? ''} />
            <p className="text-muted-foreground text-xs">
              {(one.published ?? 0) > 0 && (
                <span className="mr-1">
                  <PublishedBadge /> {one.published}/{one.points}
                </span>
              )}
              변수 {one.factors.join(' · ') || '없음'}
            </p>
          </div>
        </div>
      </TableCell>
      <TableCell>
        <span className="rounded bg-violet-100 px-1 text-xs text-violet-900 dark:bg-violet-950 dark:text-violet-200">
          DOE
        </span>{' '}
        {RECIPE_LABELS[one.recipe] ?? one.recipe}
        <span className="text-muted-foreground block text-xs">
          {(one.solvers ?? []).map((solver) => SOLVER_LABELS[solver] ?? solver).join(' + ') || '—'}
        </span>
      </TableCell>
      <TableCell>
        {/* **진행을 한 줄에** — 설계점 수 · 끝난 수 · 실패 수. 막대는 끝난 몫이다. */}
        <div className="bg-muted h-1.5 w-24 overflow-hidden rounded" aria-hidden>
          <div className="h-full bg-emerald-500" style={{ width: `${Math.round(doneRatio * 100)}%` }} />
        </div>
        <p className="mt-1 text-xs">
          완료 {one.done}/{one.points}
          {one.running > 0 && ` · 진행 ${one.running}`}
          {one.failed > 0 && <span className="text-destructive"> · 실패 {one.failed}</span>}
        </p>
      </TableCell>
      <TableCell className="text-muted-foreground text-sm">설계점 {one.points}개</TableCell>
      <TableCell>{one.workspace_name ?? '전역'}</TableCell>
      <TableCell>{one.owner_name ?? '—'}</TableCell>
      <TableCell className="whitespace-nowrap">{shownDateTime(one.created_at)}</TableCell>
    </>
  )
}

/** 펼친 DOE 의 설계점들 — 펼칠 때 그 DOE 를 읽는다. 줄을 누르면 그 점의 작업 화면. */
function DoePoints({ studyId }: { studyId: string }) {
  const study = useResource(() => simulationApi.study(studyId), [studyId])
  if (study.error) {
    return (
      <TableRow>
        <TableCell colSpan={COLUMNS} className="text-destructive pl-14 text-sm">
          설계점을 읽지 못했습니다: {study.error.message}
        </TableCell>
      </TableRow>
    )
  }
  if (!study.data) {
    return (
      <TableRow>
        <TableCell colSpan={COLUMNS} className="text-muted-foreground pl-14 text-sm">
          설계점을 불러오는 중…
        </TableCell>
      </TableRow>
    )
  }
  return (
    <>
      {study.data.points.map((point) => (
        <TableRow key={point.simulation_id} className="bg-muted/30 hover:bg-muted/50">
          <TableCell />
          <TableCell className="pl-8">
            <Link to={`/simulations/${point.simulation_id}`} className="font-mono text-sm hover:underline">
              p{String(point.number).padStart(4, '0')}
            </Link>{' '}
            <span className="text-muted-foreground text-xs">
              {Object.entries(point.params)
                .map(([name, value]) => `${name} ${value}`)
                .join(' · ')}
            </span>
          </TableCell>
          <TableCell className="text-muted-foreground text-xs">설계점</TableCell>
          <TableCell>
            <StatusBadge kind="simulation" value={point.status} />
          </TableCell>
          <TableCell className="text-sm">
            {point.status === 'failed' ? (
              <span className="text-destructive font-mono text-xs">{point.error_code ?? '—'}</span>
            ) : (
              (pointOutcome(point) ?? '—')
            )}
          </TableCell>
          <TableCell colSpan={COLUMNS - 5} />
        </TableRow>
      ))}
    </>
  )
}

/** 설계점 한 줄의 결과 — 해석 종류마다 대표 숫자 하나(목록 줄과 같은 말). */
function pointOutcome(point: StudyPoint): string | null {
  if (point.recipe === 'static') {
    return point.max_displacement_mm == null ? null : `최대 변형 ${shownValue(point.max_displacement_mm, 'mm')}`
  }
  if (point.recipe === 'harmonic') {
    return point.peak_hz == null ? null : `봉우리 ${point.peak_hz.toFixed(1)} Hz`
  }
  return point.first_elastic_hz == null ? null : `1차 ${point.first_elastic_hz.toFixed(1)} Hz`
}
