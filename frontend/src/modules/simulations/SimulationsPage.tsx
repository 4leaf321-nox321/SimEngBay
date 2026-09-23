/**
 * 해석 작업 목록 — **다른 부서 것도 보인다.**
 *
 * 「우리 조직에 이 형상의 모달 해석이 있나」 에 답할 수 있어야 같은 해석을 두 번 안 돌린다.
 * 쓰기는 그것과 무관하게 소유 부서의 일이다 — 서버가 판정한다.
 *
 * 목록은 폴링하지 않는다. 걸면 상세로 가고, 상세가 상태를 폴링한다(그 경로만 접근 로그를 비껴간다).
 */

import { useState } from 'react'
import { FolderInput, Plus, RefreshCw } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { simulationApi } from '@/modules/simulations/api'
import type { DoeImport } from '@/modules/simulations/api'
import { DoeImportDialog } from '@/modules/simulations/DoeImportDialog'
import { RECIPE_LABELS, shownDuration } from '@/modules/simulations/labels'
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
]

export default function SimulationsPage() {
  const navigate = useNavigate()
  // 홈의 「남은 일」 이 `?status=failed` 로 보낸다 — 주소가 필터의 정본이다.
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? ''
  const [offset, setOffset] = useState(0)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [imported, setImported] = useState<DoeImport | null>(null)

  const page = useResource(
    () => simulationApi.list({ status: status || undefined, limit: PER_PAGE, offset }),
    [status, offset],
  )

  function changeStatus(value: string) {
    setOffset(0)
    setParams(value === ALL ? {} : { status: value })
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
        <Select value={status || ALL} onValueChange={changeStatus}>
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
      </div>

      {imported && (
        <Alert>
          <AlertTitle>
            {imported.name} — {imported.created.length}건을 걸었습니다
          </AlertTitle>
          <AlertDescription>
            {imported.skipped.length === 0 ? (
              <p>설계점 전부를 걸었습니다. 차례로 돌며 목록의 상태가 바뀝니다.</p>
            ) : (
              <>
                <p>{imported.skipped.length}건은 걸지 않았습니다:</p>
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
          title={status ? '해당 상태의 작업이 없습니다' : '해석 작업이 없습니다'}
          hint={
            status
              ? '상태 필터를 「전체 상태」 로 바꾸면 다른 작업이 표시됩니다.'
              : 'STEP 형상 하나로 첫 모달 해석을 실행할 수 있습니다.'
          }
          action={
            status ? undefined : (
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
              <TableHead>레시피</TableHead>
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
                  <p className="text-muted-foreground text-xs">{one.source_ref}</p>
                </TableCell>
                <TableCell>{RECIPE_LABELS[one.recipe] ?? one.recipe}</TableCell>
                <TableCell>
                  <StatusBadge kind="simulation" value={one.status} />
                </TableCell>
                <TableCell className="text-sm">
                  {one.status === 'failed' ? (
                    <span className="text-destructive font-mono text-xs">{one.error_code}</span>
                  ) : one.summary?.first_elastic_hz != null ? (
                    <>1차 {Number(one.summary.first_elastic_hz).toFixed(1)} Hz</>
                  ) : (
                    '—'
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
          // 걸린 것을 바로 보여 준다 — N 개가 큐에 들어가 차례로 돈다.
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
