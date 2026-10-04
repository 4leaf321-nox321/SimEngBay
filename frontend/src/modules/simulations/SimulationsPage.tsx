/**
 * 해석 작업 목록 — **다른 부서 것도 보인다.**
 *
 * 「우리 조직에 이 형상의 모달 해석이 있나」 에 답할 수 있어야 같은 해석을 두 번 안 돌린다.
 * 쓰기는 그것과 무관하게 소유 부서의 일이다 — 서버가 판정한다.
 *
 * 목록은 폴링하지 않는다. 걸면 상세로 가고, 상세가 상태를 폴링한다(그 경로만 접근 로그를 비껴간다).
 *
 * **결과 칸은 해석 종류마다 다르다** — 모달은 1차 고유진동수, 정적은 최대 변형, 조화는 봉우리.
 * 모달 값만 보이면 정적 · 조화 작업은 끝나도 빈칸으로 보였다.
 */

import { useState } from 'react'
import { FolderInput, Plus, RefreshCw } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { DoeImport } from '@/modules/simulations/api'
import { DoeImportDialog } from '@/modules/simulations/DoeImportDialog'
import { shownOutcome } from '@/modules/simulations/format'
import { RECIPE_LABELS, SOLVER_LABELS, shownDuration } from '@/modules/simulations/labels'
import { workspaceApi } from '@/modules/workspaces/api'
import { NewSimulationDialog } from '@/modules/simulations/NewSimulationDialog'
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
import { useResource } from '@/shared/hooks/useResource'
import { shownDateTime } from '@/shared/lib/datetime'

const PER_PAGE = 50
const ALL = '__all__'

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

/** 출처 — 어디서 만든 작업인가. 업로드는 따로 표시하지 않는다(가장 흔하다). */
const SOURCE_LABELS: Record<string, string> = {
  doe_point: 'DOE 설계점',
  design: 'CAD 설계',
  mesh_check: '메시 수렴 점검',
}


export default function SimulationsPage() {
  const navigate = useNavigate()
  // 홈의 「남은 일」 이 `?status=failed` 로 보낸다 — 주소가 필터의 정본이다.
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const workspace = params.get('workspace') ?? ''
  const [offset, setOffset] = useState(0)
  const workspaces = useResource(() => workspaceApi.options(), [])
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [imported, setImported] = useState<DoeImport | null>(null)

  const page = useResource(
    () =>
      simulationApi.list({
        status: status || undefined,
        workspaceSlug: workspace || undefined,
        limit: PER_PAGE,
        offset,
      }),
    [status, workspace, offset],
  )

  /** 주소가 필터의 정본이다 — 한 칸을 바꿔도 다른 칸은 남긴다. */
  function changeFilter(key: 'status' | 'workspace', value: string) {
    setOffset(0)
    const next = new URLSearchParams(params)
    if (value === ALL) next.delete(key)
    else next.set(key, value)
    setParams(next)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="해석 작업"
        description="형상 · 물성 · 조건을 받아 FE 모델을 만들고 솔버에 넘긴 뒤 결과를 추출하는 작업입니다. 다른 부서의 작업도 표시됩니다."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={page.reload}>
              <RefreshCw className="size-4" />
              새로 고침
            </Button>
            <Button variant="outline" size="sm" onClick={() => setImporting(true)}>
              <FolderInput className="size-4" />
              DOE 가져오기
            </Button>
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus className="size-4" />새 해석 작업
            </Button>
          </>
        }
      />

      <div className="flex items-center gap-3">
        <Select value={status || ALL} onValueChange={(value) => changeFilter('status', value)}>
          <SelectTrigger className="h-8 w-36">
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
          <SelectTrigger className="h-8 w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>전체 부서</SelectItem>
            {(workspaces.data ?? []).map((one) => (
              <SelectItem key={one.slug} value={one.slug}>
                {'\u00a0'.repeat(one.depth * 2)}
                {one.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {imported && (
        <Alert>
          <AlertTitle>
            {imported.name} — {imported.created.length}건을 생성했습니다
          </AlertTitle>
          <AlertDescription>
            {imported.skipped.length === 0 ? (
              <p>고른 설계점을 모두 생성했습니다. 차례로 실행되며 목록의 상태가 바뀝니다.</p>
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
            <Button
              variant="ghost"
              size="sm"
              className="mt-2 -ml-2"
              onClick={() => setImported(null)}
            >
              닫기
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <ErrorNotice error={page.error} />

      {page.data && page.data.items.length === 0 ? (
        <EmptyState
          title={status || workspace ? '조건에 맞는 작업이 없습니다' : '해석 작업이 없습니다'}
          hint={
            status || workspace
              ? '필터를 「전체」 로 바꾸면 다른 작업이 표시됩니다.'
              : 'STEP 형상(과 CAD 점 파일)으로 첫 해석을 실행하거나, DOE 폴더를 가져옵니다.'
          }
          action={
            status || workspace ? undefined : (
              <Button size="sm" onClick={() => setCreating(true)}>
                <Plus className="size-4" />새 해석 작업
              </Button>
            )
          }
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>이름</TableHead>
              <TableHead>해석 종류</TableHead>
              <TableHead>상태</TableHead>
              <TableHead>결과</TableHead>
              <TableHead>부서</TableHead>
              <TableHead>요청자</TableHead>
              <TableHead>생성</TableHead>
              <TableHead>소요</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(page.data?.items ?? []).map((one) => (
              <TableRow key={one.id}>
                <TableCell>
                  <Link to={`/simulations/${one.id}`} className="font-medium hover:underline">
                    {one.name}
                  </Link>
                  <p className="text-muted-foreground text-xs">
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
                <TableCell className="whitespace-nowrap">{shownDateTime(one.created_at)}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {shownDuration(one.started_at, one.finished_at)}
                </TableCell>
              </TableRow>
            ))}
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

      <DoeImportDialog
        open={importing}
        onClose={() => setImporting(false)}
        onImported={(result) => {
          setImporting(false)
          // 만든 것을 바로 보여 준다 — N 개가 큐에 들어가 차례로 돈다.
          setOffset(0)
          page.reload()
          // **건너뛴 점은 목록에 안 생긴다** — 여기서 말하지 않으면 사라진다.
          setImported(result)
        }}
      />

      <NewSimulationDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(created) => {
          setCreating(false)
          navigate(`/simulations/${created.id}`)
        }}
      />
    </div>
  )
}
